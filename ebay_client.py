from __future__ import annotations

import base64
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache"
TOKEN_CACHE = CACHE_DIR / "ebay_token.json"

VALID_ENVIRONMENTS = {"production", "sandbox"}
MAX_REQUEST_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10.0

NORMALIZED_EBAY_COLUMNS = (
    "item_id",
    "title",
    "price",
    "shipping",
    "currency",
    "item_url",
    "image_url",
    "seller_username",
    "seller_feedback",
    "seller_feedback_pct",
    "buying_options",
    "condition",
    "item_end_date",
)


@dataclass
class EbayCredentials:
    client_id: str
    client_secret: str
    environment: str = "sandbox"
    marketplace_id: str = "EBAY_US"


class EbayApiError(RuntimeError):
    pass


def validate_environment(environment: str) -> str:
    env = str(environment or "").lower().strip()
    if env not in VALID_ENVIRONMENTS:
        raise EbayApiError(
            "Invalid eBay environment. Explicitly choose 'production' or 'sandbox'."
        )
    return env


def _base_urls(environment: str) -> tuple[str, str]:
    env = validate_environment(environment)
    if env == "sandbox":
        return (
            "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
            "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
        )
    return (
        "https://api.ebay.com/identity/v1/oauth2/token",
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
    )


def _read_cached_token(environment: str, client_id: str) -> Optional[str]:
    if not TOKEN_CACHE.exists():
        return None

    try:
        if CACHE_DIR.is_symlink() or TOKEN_CACHE.is_symlink():
            return None
        if not CACHE_DIR.is_dir() or not TOKEN_CACHE.is_file():
            return None
        CACHE_DIR.chmod(0o700)
        TOKEN_CACHE.chmod(0o600)
        data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    if data.get("environment") != environment or data.get("client_id") != client_id:
        return None

    try:
        expires_at = float(data.get("expires_at", 0))
    except (TypeError, ValueError):
        return None
    if expires_at <= time.time() + 60:
        return None

    token = data.get("access_token")
    if not isinstance(token, str) or not token.strip():
        return None
    return token


def _secure_cache_directory() -> None:
    try:
        CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        if CACHE_DIR.is_symlink() or not CACHE_DIR.is_dir():
            raise OSError("unsafe cache directory")
        CACHE_DIR.chmod(0o700)
    except OSError as exc:
        raise EbayApiError("Unable to secure the local eBay token cache.") from exc


def _write_cached_token(environment: str, client_id: str, token: str, expires_in: int) -> None:
    _secure_cache_directory()
    data = {
        "environment": environment,
        "client_id": client_id,
        "access_token": token,
        "expires_at": time.time() + int(expires_in or 0),
    }
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CACHE_DIR,
            prefix=".ebay_token.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, TOKEN_CACHE)
        TOKEN_CACHE.chmod(0o600)
    except (OSError, TypeError, ValueError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise EbayApiError("Unable to secure the local eBay token cache.") from exc


def _retry_after_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        seconds = float(text)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None

    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_DELAY_SECONDS)


def _retry_delay(response: requests.Response, attempt: int) -> float:
    headers = getattr(response, "headers", {}) or {}
    retry_after = _retry_after_seconds(headers.get("Retry-After"))
    if retry_after is not None:
        return retry_after
    return min(float(2 ** attempt), MAX_RETRY_DELAY_SECONDS)


def _request_with_retries(
    method: str,
    url: str,
    *,
    operation: str,
    **kwargs: Any,
) -> requests.Response:
    request = requests.post if method.upper() == "POST" else requests.get

    for attempt in range(MAX_REQUEST_ATTEMPTS):
        try:
            response = request(url, **kwargs)
        except requests.Timeout as exc:
            raise EbayApiError(f"eBay {operation} request timed out.") from exc
        except requests.ConnectionError as exc:
            raise EbayApiError(f"Unable to connect to eBay for {operation}.") from exc
        except requests.RequestException as exc:
            raise EbayApiError(f"eBay {operation} request failed.") from exc

        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        if retryable and attempt < MAX_REQUEST_ATTEMPTS - 1:
            time.sleep(_retry_delay(response, attempt))
            continue
        return response

    raise EbayApiError(f"eBay {operation} request failed.")


def _json_payload(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise EbayApiError(f"eBay {operation} returned malformed JSON.") from exc
    if not isinstance(payload, dict):
        raise EbayApiError(f"eBay {operation} returned a malformed response.")
    return payload


def _raise_for_api_error(response: requests.Response, operation: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code == 429:
        raise EbayApiError(f"eBay {operation} rate limit was reached after retries.")
    if response.status_code >= 500:
        raise EbayApiError(f"eBay {operation} is temporarily unavailable after retries.")
    if response.status_code == 401:
        raise EbayApiError(f"eBay {operation} authentication was rejected.")
    raise EbayApiError(f"eBay {operation} request failed (HTTP {response.status_code}).")


def get_application_token(credentials: EbayCredentials, use_cache: bool = True) -> str:
    """Get an application token for public marketplace browsing."""
    environment = validate_environment(credentials.environment)
    if not credentials.client_id or not credentials.client_secret:
        raise EbayApiError("Missing eBay Client ID or Client Secret.")

    token_url, _ = _base_urls(environment)

    if use_cache:
        cached = _read_cached_token(environment, credentials.client_id)
        if cached:
            return cached

    basic = base64.b64encode(
        f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")
    ).decode("ascii")

    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }

    response = _request_with_retries(
        "POST",
        token_url,
        operation="OAuth",
        headers=headers,
        data=data,
        timeout=30,
    )
    _raise_for_api_error(response, "OAuth")

    payload = _json_payload(response, "OAuth")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise EbayApiError("eBay OAuth response did not include an access token.")

    try:
        expires_in = int(payload.get("expires_in", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise EbayApiError("eBay OAuth returned a malformed response.") from exc

    _write_cached_token(
        environment,
        credentials.client_id,
        token,
        expires_in,
    )
    return token


def search_ebay(
    credentials: EbayCredentials,
    query: str,
    limit: int = 50,
    sort: str = "newlyListed",
    category_ids: str = "",
    max_price: Optional[float] = None,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    environment = validate_environment(credentials.environment)
    token = get_application_token(credentials, use_cache=use_cache)
    _, search_url = _base_urls(environment)

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": credentials.marketplace_id or "EBAY_US",
        "Content-Type": "application/json",
    }
    params: dict[str, Any] = {
        "q": query,
        "limit": max(1, min(int(limit), 200)),
    }

    if sort:
        params["sort"] = sort

    filters = []
    if max_price is not None and max_price > 0:
        filters.append(f"price:[..{float(max_price)}]")
        filters.append("priceCurrency:USD")

    if filters:
        params["filter"] = ",".join(filters)

    if category_ids.strip():
        params["category_ids"] = category_ids.strip()

    response = _request_with_retries(
        "GET",
        search_url,
        operation="Browse API",
        headers=headers,
        params=params,
        timeout=30,
    )

    if response.status_code == 401:
        token = get_application_token(credentials, use_cache=False)
        headers["Authorization"] = f"Bearer {token}"
        response = _request_with_retries(
            "GET",
            search_url,
            operation="Browse API",
            headers=headers,
            params=params,
            timeout=30,
        )

    _raise_for_api_error(response, "Browse API")
    payload = _json_payload(response, "Browse API")
    summaries = payload.get("itemSummaries")
    if summaries is None:
        return []
    if not isinstance(summaries, list) or not all(
        isinstance(item, dict) for item in summaries
    ):
        raise EbayApiError("eBay Browse API returned malformed item summaries.")
    return summaries


def _money_value(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mapping_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _shipping_value(item: dict[str, Any]) -> Optional[float]:
    options = item.get("shippingOptions")
    if not isinstance(options, list):
        return None
    if not options:
        return None

    first = _mapping_value(options[0])
    cost = _mapping_value(first.get("shippingCost"))
    return _money_value(cost.get("value"))


def normalize_ebay_items(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []

    for item in items:
        if not isinstance(item, dict):
            raise EbayApiError("eBay Browse API returned a malformed listing.")
        price_obj = _mapping_value(item.get("price"))
        seller = _mapping_value(item.get("seller"))
        image = _mapping_value(item.get("image"))
        price = _money_value(price_obj.get("value"))

        rows.append({
            "item_id": _text_value(item.get("itemId")),
            "title": _text_value(item.get("title")),
            "price": price,
            "shipping": _shipping_value(item),
            "currency": _text_value(price_obj.get("currency")),
            "item_url": _text_value(item.get("itemWebUrl")),
            "image_url": _text_value(image.get("imageUrl")),
            "seller_username": _text_value(seller.get("username")),
            "seller_feedback": seller.get("feedbackScore"),
            "seller_feedback_pct": seller.get("feedbackPercentage"),
            "buying_options": ",".join(_text_list(item.get("buyingOptions"))),
            "condition": _text_value(item.get("condition")),
            "item_end_date": _text_value(item.get("itemEndDate")),
        })

    return pd.DataFrame(rows, columns=NORMALIZED_EBAY_COLUMNS)
