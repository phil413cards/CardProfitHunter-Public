from __future__ import annotations

import re
from typing import Any

import pandas as pd


_DANGEROUS_SPREADSHEET_PREFIX = re.compile(r"^\s*[=+\-@\t\r]")


def sanitize_csv_cell(value: Any) -> Any:
    """Neutralize formula-like strings while preserving non-string values."""
    if not isinstance(value, str) or not value:
        return value
    if value.startswith("'"):
        return value
    if _DANGEROUS_SPREADSHEET_PREFIX.match(value):
        return "'" + value
    return value


def make_dataframe_spreadsheet_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a spreadsheet-safe copy without changing the source frame."""
    return frame.copy(deep=True).map(sanitize_csv_cell)


def dataframe_to_spreadsheet_safe_csv(
    frame: pd.DataFrame,
    path_or_buf: Any = None,
    *,
    index: bool = False,
) -> str | None:
    """Serialize a sanitized copy for generated files and downloads."""
    safe_frame = make_dataframe_spreadsheet_safe(frame)
    return safe_frame.to_csv(path_or_buf, index=index)
