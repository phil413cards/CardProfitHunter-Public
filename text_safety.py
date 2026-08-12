from __future__ import annotations

from typing import Any

import pandas as pd
from pandas.api.types import is_scalar


def is_missing_value(value: Any) -> bool:
    """Return whether a scalar value represents missing or blank input."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if not is_scalar(value):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def safe_text(value: Any) -> str:
    """Return user-controlled scalar text without coercing missing containers."""
    if is_missing_value(value) or not isinstance(value, str):
        return ""
    return value


def required_text_issue(value: Any, field: str) -> str:
    """Return a stable fail-closed flag for a required text field."""
    if is_missing_value(value):
        return f"missing_{field}"
    if not isinstance(value, str):
        return f"invalid_{field}"
    return ""
