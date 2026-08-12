from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from text_safety import is_missing_value, required_text_issue, safe_text


MINIMUM_SELLER_FEEDBACK_COUNT = 100
MINIMUM_SELLER_FEEDBACK_PCT = 99.0


@dataclass(frozen=True)
class SellerEligibility:
    username: str
    feedback_count: int | None
    feedback_pct: float | None
    flags: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.flags


def _finite_float(value: Any) -> float | None:
    if is_missing_value(value) or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _feedback_count(value: Any) -> int | None:
    parsed = _finite_float(value)
    if parsed is None or parsed < 0 or not parsed.is_integer():
        return None
    return int(parsed)


def evaluate_seller_eligibility(values: Mapping[str, Any]) -> SellerEligibility:
    raw_username = values.get("seller_username")
    username_issue = required_text_issue(raw_username, "seller_username")
    username = " ".join(safe_text(raw_username).split())

    raw_feedback = values.get("seller_feedback")
    feedback_count = _feedback_count(raw_feedback)

    raw_feedback_pct = values.get("seller_feedback_pct")
    parsed_feedback_pct = _finite_float(raw_feedback_pct)
    feedback_pct = (
        parsed_feedback_pct
        if parsed_feedback_pct is not None and 0 <= parsed_feedback_pct <= 100
        else None
    )

    flags: list[str] = []
    if username_issue:
        flags.append(username_issue)

    if is_missing_value(raw_feedback):
        flags.append("missing_seller_feedback")
    elif feedback_count is None:
        flags.append("invalid_seller_feedback")
    elif feedback_count < MINIMUM_SELLER_FEEDBACK_COUNT:
        flags.append("insufficient_seller_feedback")

    if is_missing_value(raw_feedback_pct):
        flags.append("missing_seller_feedback_pct")
    elif feedback_pct is None:
        flags.append("invalid_seller_feedback_pct")
    elif feedback_pct < MINIMUM_SELLER_FEEDBACK_PCT:
        flags.append("insufficient_seller_feedback_pct")

    return SellerEligibility(
        username=username,
        feedback_count=feedback_count,
        feedback_pct=feedback_pct,
        flags=tuple(flags),
    )
