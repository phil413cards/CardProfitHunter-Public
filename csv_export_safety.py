from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import Any

import pandas as pd

from local_runtime_security import atomic_write_private_bytes


_DANGEROUS_SPREADSHEET_PREFIX = re.compile(r"^\s*[=+\-@\t\r]")


class CsvExportError(OSError):
    """A sanitized generated-CSV error safe to show in the app."""


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
    if isinstance(path_or_buf, (str, PathLike)):
        try:
            serialized = safe_frame.to_csv(index=index)
            atomic_write_private_bytes(
                Path(path_or_buf),
                serialized.encode("utf-8"),
            )
            return None
        except Exception:
            raise CsvExportError(
                "Generated CSV could not be saved safely."
            ) from None
    return safe_frame.to_csv(path_or_buf, index=index)


def write_dataframe_spreadsheet_safe_csv(
    frame: pd.DataFrame,
    destination: Path,
    *,
    index: bool = False,
) -> Path:
    """Atomically write a spreadsheet-safe CSV with private local permissions."""
    try:
        result = dataframe_to_spreadsheet_safe_csv(
            frame,
            Path(destination),
            index=index,
        )
        if result is not None:
            raise TypeError
        return Path(destination)
    except Exception:
        raise CsvExportError(
            "Generated CSV could not be saved safely."
        ) from None
