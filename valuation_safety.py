from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

import pandas as pd


VALUATION_PROVENANCE_COLUMNS = (
    "verification_status",
    "verified_at",
    "expires_at",
    "source_url",
    "comp_count",
)

VERIFIED_STATUS = "verified"
NON_ACTIONABLE_STATUSES = {
    "demonstration",
    "unverified",
    "non_actionable",
}
ALLOWED_VERIFICATION_STATUSES = {VERIFIED_STATUS, *NON_ACTIONABLE_STATUSES}

NON_ACTIONABLE_VALUATION_PATTERNS = (
    r"\bexample(?:\s+only)?\b",
    r"\bdemo\b",
    r"\bdemonstration\b",
    r"\bunverified\b",
    r"\bnon[-\s]?actionable\b",
)


def is_missing_valuation_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def normalize_verification_status(value: Any) -> str:
    if is_missing_valuation_value(value):
        return ""
    return re.sub(r"[-\s]+", "_", str(value).strip().casefold())


def valuation_notes_are_non_actionable(notes: Any) -> bool:
    if is_missing_valuation_value(notes):
        return False
    normalized_notes = re.sub(r"\s+", " ", str(notes)).strip().casefold()
    return any(
        re.search(pattern, normalized_notes)
        for pattern in NON_ACTIONABLE_VALUATION_PATTERNS
    )


def _strict_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized) is None:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool) or is_missing_valuation_value(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0 or not parsed.is_integer():
        return None
    return int(parsed)


def _valid_source_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
        and not any(character.isspace() for character in value)
    )


def _utc_date(as_of: date | datetime | None) -> date:
    if as_of is None:
        return datetime.now(timezone.utc).date()
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Valuation as-of timestamps must include a timezone.")
        return as_of.astimezone(timezone.utc).date()
    if isinstance(as_of, date):
        return as_of
    raise TypeError("Valuation as-of value must be a date or timezone-aware datetime.")


def valuation_provenance_flags(
    valuation: Mapping[str, Any],
    *,
    as_of: date | datetime | None = None,
) -> tuple[str, ...]:
    """Return non-actionable provenance/freshness flags for one valuation row."""
    status = normalize_verification_status(valuation.get("verification_status"))
    if not status:
        return ("missing_valuation_provenance",)
    if status in NON_ACTIONABLE_STATUSES:
        return ("unverified_valuation_status",)
    if status != VERIFIED_STATUS:
        return ("invalid_valuation_provenance",)

    required_values = (
        valuation.get("verified_at"),
        valuation.get("expires_at"),
        valuation.get("source_url"),
        valuation.get("comp_count"),
    )
    if any(is_missing_valuation_value(value) for value in required_values):
        return ("missing_valuation_provenance",)

    verified_at = _strict_iso_date(valuation.get("verified_at"))
    expires_at = _strict_iso_date(valuation.get("expires_at"))
    source_is_valid = _valid_source_url(valuation.get("source_url"))
    comp_count = _positive_integer(valuation.get("comp_count"))
    if (
        verified_at is None
        or expires_at is None
        or not source_is_valid
        or comp_count is None
        or expires_at < verified_at
    ):
        return ("invalid_valuation_provenance",)

    current_date = _utc_date(as_of)
    if verified_at > current_date:
        return ("invalid_valuation_provenance",)
    if expires_at < current_date:
        return ("expired_valuation",)
    return ()


def valuation_freshness_label(
    valuation: Mapping[str, Any],
    *,
    as_of: date | datetime | None = None,
) -> str:
    if valuation_notes_are_non_actionable(valuation.get("notes")):
        return "Non-actionable"
    flags = valuation_provenance_flags(valuation, as_of=as_of)
    if not flags:
        return "Current"
    return {
        "expired_valuation": "Expired",
        "missing_valuation_provenance": "Missing provenance",
        "invalid_valuation_provenance": "Invalid provenance",
        "unverified_valuation_status": "Non-actionable",
    }.get(flags[0], "Non-actionable")
