from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class LocalRuntimeSecurityError(RuntimeError):
    """A sanitized local-runtime security error safe to show in the app."""


def _existing_parent_is_safe(path: Path) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return False
        try:
            metadata = current.stat()
        except FileNotFoundError:
            parent = current.parent
            if parent == current:
                return False
            current = parent
            continue
        except OSError:
            return False
        return stat.S_ISDIR(metadata.st_mode)


def secure_private_directory(path: Path) -> Path:
    directory = Path(path)
    try:
        if not _existing_parent_is_safe(directory):
            raise OSError
        directory.mkdir(
            mode=PRIVATE_DIRECTORY_MODE,
            parents=True,
            exist_ok=True,
        )
        if directory.is_symlink():
            raise OSError
        metadata = directory.stat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        directory.chmod(PRIVATE_DIRECTORY_MODE)
        return directory
    except (OSError, RuntimeError, TypeError, ValueError):
        raise LocalRuntimeSecurityError(
            "Local private directory could not be secured."
        ) from None


def secure_optional_private_file(path: Path) -> bool:
    private_file = Path(path)
    try:
        if private_file.is_symlink():
            raise OSError
        try:
            metadata = private_file.stat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError
        private_file.chmod(PRIVATE_FILE_MODE)
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        raise LocalRuntimeSecurityError(
            "Local private file could not be secured."
        ) from None


def atomic_write_private_bytes(path: Path, payload: bytes) -> Path:
    destination = Path(path)
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        if not isinstance(payload, bytes):
            raise TypeError
        secure_private_directory(destination.parent)
        secure_optional_private_file(destination)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        else:
            temporary_path.chmod(PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        return destination
    except Exception:
        raise LocalRuntimeSecurityError(
            "Local private file could not be saved safely."
        ) from None
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
