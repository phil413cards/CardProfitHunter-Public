from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from valuation_safety import (
    ALLOWED_VERIFICATION_STATUSES,
    VERIFIED_STATUS,
    normalize_verification_status,
    valuation_provenance_flags,
)


VALUATION_REQUIRED_COLUMNS = (
    "keyword",
    "raw_market_value",
    "psa9_value",
    "psa10_value",
    "gem_rate_estimate",
    "psa9_rate_estimate",
    "verification_status",
    "verified_at",
    "expires_at",
    "source_url",
    "comp_count",
    "notes",
)

LISTING_REQUIRED_COLUMNS = (
    "title",
    "price",
    "shipping",
    "currency",
    "buying_options",
    "condition",
)

MAX_CSV_UPLOAD_MB = 5
MAX_CSV_BYTES = MAX_CSV_UPLOAD_MB * 1024 * 1024
MAX_CSV_COLUMNS = 64
MAX_LISTING_ROWS = 1000
MAX_VALUATION_ROWS = 1000

SETTING_NUMBER_RANGES = {
    "ebay_fee_pct": (0.0, 1.0),
    "purchase_tax_pct": (0.0, 1.0),
    "promoted_listing_fee_pct": (0.0, 1.0),
    "return_defect_allowance_pct": (0.0, 1.0),
    "grading_loss_risk_pct": (0.0, 1.0),
    "raw_flip_shipping_allowance": (0.0, None),
    "psa_grading_fee": (0.0, None),
    "psa_shipping_insurance_allowance": (0.0, None),
    "psa_selling_shipping_allowance": (0.0, None),
    "minimum_raw_flip_profit": (0.0, None),
    "minimum_raw_flip_roi_pct": (0.0, None),
    "minimum_psa_expected_profit": (0.0, None),
    "minimum_psa_expected_roi_pct": (0.0, None),
    "offer_safety_margin_pct": (0.0, 1.0),
    "max_offer_market_pct": (0.0, 1.0),
}


class InputValidationError(ValueError):
    """A sanitized input error that is safe to show in the app."""


def validate_search_query(query: Any) -> str:
    if not isinstance(query, str) or not query.strip():
        raise InputValidationError("Search query must be nonempty text.")
    return query.strip()


def validate_category_ids(category_ids: Any) -> str:
    if category_ids is None:
        return ""
    if not isinstance(category_ids, str):
        raise InputValidationError(
            "Category IDs must be blank or comma-separated numeric identifiers."
        )

    normalized = category_ids.strip()
    if not normalized:
        return ""

    identifiers = [identifier.strip() for identifier in normalized.split(",")]
    if any(
        not identifier or re.fullmatch(r"[0-9]+", identifier) is None
        for identifier in identifiers
    ):
        raise InputValidationError(
            "Category IDs must be blank or comma-separated numeric identifiers."
        )
    return ",".join(identifiers)


def validate_search_inputs(query: Any, category_ids: Any) -> tuple[str, str]:
    return validate_search_query(query), validate_category_ids(category_ids)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def validate_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, Mapping):
        raise InputValidationError("Settings must be a JSON object.")

    missing = [
        key
        for key in (*SETTING_NUMBER_RANGES, "raw_only")
        if key not in settings
    ]
    if missing:
        raise InputValidationError(
            "Settings are missing required fields: " + ", ".join(sorted(missing)) + "."
        )

    validated = dict(settings)
    for key, (minimum, maximum) in SETTING_NUMBER_RANGES.items():
        parsed = _finite_number(settings.get(key))
        if (
            parsed is None
            or parsed < minimum
            or (maximum is not None and parsed > maximum)
        ):
            range_text = f"{minimum:g} or greater"
            if maximum is not None:
                range_text = f"between {minimum:g} and {maximum:g}"
            raise InputValidationError(
                f"Setting '{key}' must be a finite number {range_text}."
            )
        validated[key] = parsed

    combined_selling_rate = sum(
        validated[key]
        for key in (
            "ebay_fee_pct",
            "promoted_listing_fee_pct",
            "return_defect_allowance_pct",
        )
    )
    if combined_selling_rate > 1:
        raise InputValidationError(
            "Combined marketplace, promoted-listing, and return/defect rates "
            "must not exceed 1."
        )

    if not isinstance(settings.get("raw_only"), bool):
        raise InputValidationError("Setting 'raw_only' must be true or false.")

    return validated


def load_settings_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InputValidationError("Settings file could not be read as valid JSON.") from None
    return validate_settings(payload)


def _validate_frame_shape(
    frame: Any,
    required_columns: tuple[str, ...],
    label: str,
    max_rows: int,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise InputValidationError(f"{label} input must be tabular CSV data.")
    if len(frame.columns) > MAX_CSV_COLUMNS:
        raise InputValidationError(
            f"{label} CSV must contain no more than {MAX_CSV_COLUMNS} columns."
        )
    if frame.columns.duplicated().any():
        raise InputValidationError(f"{label} CSV contains duplicate column names.")

    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise InputValidationError(
            f"{label} CSV is missing required columns: "
            + ", ".join(missing)
            + "."
        )
    if frame.empty:
        raise InputValidationError(f"{label} CSV must contain at least one data row.")
    if len(frame.index) > max_rows:
        raise InputValidationError(
            f"{label} CSV must contain no more than {max_rows} data rows."
        )
    return frame.copy()


def _invalid_row_numbers(mask: pd.Series) -> str:
    rows = [str(position + 2) for position, invalid in enumerate(mask.tolist()) if invalid]
    displayed = rows[:5]
    suffix = "" if len(rows) <= 5 else ", ..."
    return ", ".join(displayed) + suffix


def _required_text(frame: pd.DataFrame, column: str, label: str) -> pd.Series:
    valid = frame[column].map(
        lambda value: isinstance(value, str) and bool(value.strip())
    )
    if not valid.all():
        rows = _invalid_row_numbers(~valid)
        raise InputValidationError(
            f"{label} CSV column '{column}' must contain text on row(s): {rows}."
        )
    return frame[column].map(str.strip)


def _numeric_column(
    frame: pd.DataFrame,
    column: str,
    label: str,
    minimum: float,
    allow_minimum: bool,
    maximum: float | None = None,
) -> pd.Series:
    non_boolean = frame[column].map(lambda value: not isinstance(value, bool))
    parsed = pd.to_numeric(frame[column], errors="coerce")
    finite = parsed.map(
        lambda value: bool(pd.notna(value) and math.isfinite(float(value)))
    )
    in_range = parsed.ge(minimum) if allow_minimum else parsed.gt(minimum)
    if maximum is not None:
        in_range &= parsed.le(maximum)
    invalid = ~(non_boolean & finite & in_range.fillna(False))
    if invalid.any():
        rows = _invalid_row_numbers(invalid)
        range_text = f"at least {minimum:g}" if allow_minimum else f"greater than {minimum:g}"
        if maximum is not None:
            range_text = f"between {minimum:g} and {maximum:g}"
        raise InputValidationError(
            f"{label} CSV column '{column}' must contain finite values "
            f"{range_text} on row(s): {rows}."
        )
    return parsed.astype(float)


def validate_valuation_frame(frame: Any) -> pd.DataFrame:
    validated = _validate_frame_shape(
        frame,
        VALUATION_REQUIRED_COLUMNS,
        "Valuation",
        MAX_VALUATION_ROWS,
    )
    validated["keyword"] = _required_text(validated, "keyword", "Valuation")
    validated["notes"] = _required_text(validated, "notes", "Valuation")
    validated["verification_status"] = _required_text(
        validated,
        "verification_status",
        "Valuation",
    ).map(normalize_verification_status)

    invalid_status = ~validated["verification_status"].isin(
        ALLOWED_VERIFICATION_STATUSES
    )
    if invalid_status.any():
        rows = _invalid_row_numbers(invalid_status)
        raise InputValidationError(
            "Valuation CSV column 'verification_status' contains an unsupported "
            f"status on row(s): {rows}."
        )

    for column in ("verified_at", "expires_at", "source_url"):
        validated[column] = validated[column].map(
            lambda value: value.strip() if isinstance(value, str) else value
        )

    identity_keys = (
        validated["keyword"]
        .str.replace(r"\s+", " ", regex=True)
        .str.casefold()
    )
    duplicate_identities = identity_keys.duplicated(keep=False)
    if duplicate_identities.any():
        rows = _invalid_row_numbers(duplicate_identities)
        raise InputValidationError(
            "Valuation CSV contains duplicate card identities on row(s): " + rows + "."
        )

    for column in ("raw_market_value", "psa9_value", "psa10_value"):
        validated[column] = _numeric_column(
            validated,
            column,
            "Valuation",
            minimum=0.0,
            allow_minimum=False,
        )

    for column in ("gem_rate_estimate", "psa9_rate_estimate"):
        validated[column] = _numeric_column(
            validated,
            column,
            "Valuation",
            minimum=0.0,
            allow_minimum=True,
            maximum=1.0,
        )

    rate_total = validated["gem_rate_estimate"] + validated["psa9_rate_estimate"]
    invalid_total = rate_total.gt(1.0)
    if invalid_total.any():
        rows = _invalid_row_numbers(invalid_total)
        raise InputValidationError(
            "Valuation CSV grading probabilities must total 1 or less on row(s): "
            + rows
            + "."
        )

    verified_mask = validated["verification_status"].eq(VERIFIED_STATUS)
    missing_provenance = pd.Series(False, index=validated.index)
    invalid_provenance = pd.Series(False, index=validated.index)
    for index in validated.index[verified_mask]:
        flags = valuation_provenance_flags(validated.loc[index])
        missing_provenance.loc[index] = "missing_valuation_provenance" in flags
        invalid_provenance.loc[index] = "invalid_valuation_provenance" in flags

    if missing_provenance.any():
        rows = _invalid_row_numbers(missing_provenance)
        raise InputValidationError(
            "Verified valuation rows are missing required provenance on row(s): "
            + rows
            + "."
        )
    if invalid_provenance.any():
        rows = _invalid_row_numbers(invalid_provenance)
        raise InputValidationError(
            "Verified valuation provenance is malformed on row(s): " + rows + "."
        )

    for index in validated.index[verified_mask]:
        validated.loc[index, "comp_count"] = int(
            float(validated.loc[index, "comp_count"])
        )
    return validated


def validate_listing_frame(frame: Any) -> pd.DataFrame:
    validated = _validate_frame_shape(
        frame,
        LISTING_REQUIRED_COLUMNS,
        "Listings",
        MAX_LISTING_ROWS,
    )
    for column in ("title", "currency", "buying_options", "condition"):
        validated[column] = _required_text(validated, column, "Listings")

    validated["currency"] = validated["currency"].str.upper()
    validated["price"] = _numeric_column(
        validated,
        "price",
        "Listings",
        minimum=0.0,
        allow_minimum=False,
    )
    validated["shipping"] = _numeric_column(
        validated,
        "shipping",
        "Listings",
        minimum=0.0,
        allow_minimum=True,
    )
    return validated


def _load_csv(
    source: Any,
    label: str,
    validator: Callable[[Any], pd.DataFrame],
    max_rows: int,
) -> pd.DataFrame:
    source_size = _csv_source_size_bytes(source)
    if source_size is not None and source_size > MAX_CSV_BYTES:
        raise InputValidationError(
            f"{label} CSV must be {MAX_CSV_UPLOAD_MB} MB or smaller."
        )
    try:
        frame = pd.read_csv(source, nrows=max_rows + 1)
    except (
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
    ):
        raise InputValidationError(f"{label} CSV could not be read.") from None
    return validator(frame)


def _csv_source_size_bytes(source: Any) -> int | None:
    try:
        if isinstance(source, (str, Path)):
            return Path(source).stat().st_size

        declared_size = getattr(source, "size", None)
        if isinstance(declared_size, int) and not isinstance(declared_size, bool):
            return max(declared_size, 0)

        getbuffer = getattr(source, "getbuffer", None)
        if callable(getbuffer):
            return int(getbuffer().nbytes)

        getvalue = getattr(source, "getvalue", None)
        if callable(getvalue):
            value = getvalue()
            if isinstance(value, str):
                return len(value.encode("utf-8"))
            if isinstance(value, bytes):
                return len(value)
    except (OSError, OverflowError, TypeError, ValueError):
        return None
    return None


def load_valuation_csv(source: Any) -> pd.DataFrame:
    return _load_csv(
        source,
        "Valuation",
        validate_valuation_frame,
        MAX_VALUATION_ROWS,
    )


def load_listing_csv(source: Any) -> pd.DataFrame:
    return _load_csv(
        source,
        "Listings",
        validate_listing_frame,
        MAX_LISTING_ROWS,
    )
