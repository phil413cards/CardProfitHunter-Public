from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Callable, Mapping
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from input_validation import (
    load_settings_file,
    load_valuation_csv,
    validate_settings,
    validate_valuation_frame,
)


class LocalPersistenceError(OSError):
    """A sanitized local persistence error safe to show in the app."""


def _existing_file_mode(path: Path) -> int | None:
    if path.is_symlink():
        raise LocalPersistenceError("Local file could not be saved safely.")
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        raise LocalPersistenceError("Local file could not be saved safely.") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise LocalPersistenceError("Local file could not be saved safely.")
    return stat.S_IMODE(metadata.st_mode)


def _atomic_write_bytes(
    destination: Path,
    payload: bytes,
    verifier: Callable[[Path], Any],
) -> None:
    destination = Path(destination)
    parent = destination.parent
    mode = _existing_file_mode(destination)
    descriptor: int | None = None
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(temporary_name)
        if mode is not None:
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        verifier(temporary_path)
        os.replace(temporary_path, destination)
        temporary_path = None
    except Exception:
        raise LocalPersistenceError("Local file could not be saved safely.") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def save_settings_atomically(path: Path, settings: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_settings(settings)
    try:
        payload = json.dumps(validated, indent=2).encode("utf-8")
    except Exception:
        raise LocalPersistenceError("Local file could not be saved safely.") from None
    _atomic_write_bytes(Path(path), payload, load_settings_file)
    return validated


def save_valuation_frame_atomically(
    path: Path,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    validated = validate_valuation_frame(frame)
    try:
        output = StringIO()
        validated.to_csv(output, index=False)
        payload = output.getvalue().encode("utf-8")
    except Exception:
        raise LocalPersistenceError("Local file could not be saved safely.") from None
    _atomic_write_bytes(
        Path(path),
        payload,
        load_valuation_csv,
    )
    return validated
