from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from valuation_safety import (
    normalize_verification_status,
    valuation_notes_are_non_actionable,
    valuation_provenance_flags,
)


RENEWAL_REPORT_COLUMNS = (
    "keyword",
    "verification_status",
    "freshness_status",
    "expires_at",
    "days_until_expiry",
    "renewal_required",
    "renewal_reason",
)


def _audit_date(as_of: date | datetime | None) -> date:
    if as_of is None:
        return datetime.now(timezone.utc).date()
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Valuation audit timestamps must include a timezone.")
        return as_of.astimezone(timezone.utc).date()
    if isinstance(as_of, date):
        return as_of
    raise TypeError("Valuation audit as-of value must be a date or aware datetime.")


def _renewal_window_days(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Renewal window must be a nonnegative whole number.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Renewal window must be a nonnegative whole number.") from exc
    if parsed < 0 or parsed != value:
        raise ValueError("Renewal window must be a nonnegative whole number.")
    return parsed


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _expiry_date(value: Any) -> date | None:
    text = _text(value)
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def build_valuation_renewal_report(
    valuations: pd.DataFrame,
    *,
    as_of: date | datetime | None = None,
    renewal_window_days: int = 30,
) -> pd.DataFrame:
    """Return a read-only renewal classification for every valuation row."""
    if not isinstance(valuations, pd.DataFrame):
        raise TypeError("Valuations must be provided as a pandas DataFrame.")

    current_date = _audit_date(as_of)
    window_days = _renewal_window_days(renewal_window_days)
    rows: list[dict[str, Any]] = []

    for _, valuation in valuations.iterrows():
        keyword = _text(valuation.get("keyword"))
        status = normalize_verification_status(
            valuation.get("verification_status")
        )
        expires_text = _text(valuation.get("expires_at"))
        expires_at = _expiry_date(expires_text)
        days_until_expiry = (
            (expires_at - current_date).days if expires_at is not None else None
        )

        if valuation_notes_are_non_actionable(valuation.get("notes")):
            freshness = "Non-actionable"
            renewal_required = False
            reason = "non_actionable"
        else:
            flags = valuation_provenance_flags(valuation, as_of=current_date)
            flag = flags[0] if flags else ""
            if flag == "unverified_valuation_status":
                freshness = "Non-actionable"
                renewal_required = False
                reason = "non_actionable"
            elif flag == "missing_valuation_provenance":
                freshness = "Missing provenance"
                renewal_required = True
                reason = "missing_provenance"
            elif flag == "invalid_valuation_provenance":
                freshness = "Invalid provenance"
                renewal_required = True
                reason = "invalid_provenance"
            elif flag == "expired_valuation":
                freshness = "Expired"
                renewal_required = True
                reason = "expired"
            elif days_until_expiry is not None and days_until_expiry <= window_days:
                freshness = "Due soon"
                renewal_required = True
                reason = "expires_within_window"
            else:
                freshness = "Current"
                renewal_required = False
                reason = ""

        rows.append(
            {
                "keyword": keyword,
                "verification_status": status,
                "freshness_status": freshness,
                "expires_at": expires_text,
                "days_until_expiry": days_until_expiry,
                "renewal_required": renewal_required,
                "renewal_reason": reason,
            }
        )

    return pd.DataFrame(rows, columns=RENEWAL_REPORT_COLUMNS)


def summarize_valuation_renewal(report: pd.DataFrame) -> dict[str, int]:
    """Return stable aggregate counts for a renewal report."""
    if not isinstance(report, pd.DataFrame):
        raise TypeError("Valuation renewal report must be a pandas DataFrame.")

    statuses = report.get(
        "freshness_status",
        pd.Series(index=report.index, dtype="object"),
    )
    renewal_required = report.get(
        "renewal_required",
        pd.Series(False, index=report.index, dtype="bool"),
    ).fillna(False).astype(bool)

    return {
        "total": int(len(report)),
        "current": int(statuses.eq("Current").sum()),
        "due_soon": int(statuses.eq("Due soon").sum()),
        "expired": int(statuses.eq("Expired").sum()),
        "missing_provenance": int(statuses.eq("Missing provenance").sum()),
        "invalid_provenance": int(statuses.eq("Invalid provenance").sum()),
        "non_actionable": int(statuses.eq("Non-actionable").sum()),
        "renewal_required": int(renewal_required.sum()),
    }
