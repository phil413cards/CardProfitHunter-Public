from __future__ import annotations

import logging
import platform
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from local_runtime_security import (
    secure_optional_private_file,
    secure_private_directory,
)


REDACTED = "[REDACTED]"
LOGGER_NAME = "card_profit_hunter.diagnostics"
LOG_FILENAME = "application.log"
LOGGER_WARNING = (
    "Local diagnostic logging is unavailable. "
    "The application will continue without a log file."
)

_SAFE_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
_DEPENDENCIES = ("streamlit", "pandas", "requests", "python-dotenv")
_SENSITIVE_KEY_PARTS = (
    "client_secret",
    "authorization",
    "password",
    "api_key",
    "bearer",
    "token",
    "secret",
)
_ENV_ASSIGNMENT = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*).*$",
    re.IGNORECASE,
)
_AUTHORIZATION_HEADER = re.compile(
    r"^(?P<prefix>\s*authorization\s*:\s*).*$",
    re.IGNORECASE,
)
_KEY_VALUE = re.compile(
    r"(?P<key>[\"']?[A-Za-z_][A-Za-z0-9_.-]*[\"']?)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;\r\n]+)",
)
_BEARER_VALUE = re.compile(
    r"(?i)\bbearer(?P<space>\s+)[A-Za-z0-9._~+/=-]+"
)


class ApplicationStartupError(RuntimeError):
    """A startup failure containing only user-safe diagnostic information."""

    def __init__(self, code: str, public_message: str):
        super().__init__(public_message)
        self.code = _safe_identifier(code, "STARTUP_FAILURE")
        self.public_message = public_message


@dataclass(frozen=True)
class StartupStep:
    key: str
    error_code: str
    public_message: str
    operation: Callable[[], Any]


@dataclass(frozen=True)
class LocalLoggerSetup:
    logger: logging.Logger
    enabled: bool
    warning: str | None = None


def _safe_identifier(value: Any, fallback: str) -> str:
    candidate = str(value) if isinstance(value, str) else ""
    return candidate if _SAFE_IDENTIFIER.fullmatch(candidate) else fallback


def _normalized_key(value: str) -> str:
    return value.strip("\"'").lower().replace("-", "_").replace(".", "_")


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_sensitive_text(value: Any) -> str:
    text = "" if value is None else str(value)
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        ending = ""
        content = line
        if line.endswith("\r\n"):
            content, ending = line[:-2], "\r\n"
        elif line.endswith(("\n", "\r")):
            content, ending = line[:-1], line[-1]

        authorization_match = _AUTHORIZATION_HEADER.match(content)
        if authorization_match:
            lines.append(
                f"{authorization_match.group('prefix')}{REDACTED}{ending}"
            )
            continue

        env_match = _ENV_ASSIGNMENT.match(content)
        if env_match and _is_sensitive_key(env_match.group("key")):
            lines.append(f"{env_match.group('prefix')}{REDACTED}{ending}")
            continue

        content = _BEARER_VALUE.sub(
            lambda match: f"Bearer{match.group('space')}{REDACTED}",
            content,
        )

        def redact_assignment(match: re.Match[str]) -> str:
            if not _is_sensitive_key(match.group("key")):
                return match.group(0)
            return f"{match.group('key')}{match.group('separator')}{REDACTED}"

        lines.append(_KEY_VALUE.sub(redact_assignment, content) + ending)
    return "".join(lines)


def format_exception_diagnostic(
    event_code: str,
    error: BaseException,
    operational_context: str,
) -> str:
    safe_event = _safe_identifier(event_code, "APPLICATION_FAILURE")
    safe_context = _safe_identifier(operational_context, "application.unknown")
    safe_type = _safe_identifier(type(error).__name__, "Exception")
    return (
        f"event={safe_event} "
        f"context={safe_context} "
        f"exception_type={safe_type}"
    )


def _close_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_card_profit_diagnostics", False):
            logger.removeHandler(handler)
            handler.close()


def configure_local_logger(log_directory: Path) -> LocalLoggerSetup:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = Path(log_directory) / LOG_FILENAME
    handler: logging.FileHandler | None = None
    try:
        secure_private_directory(target.parent)
        secure_optional_private_file(target)

        for existing_handler in logger.handlers:
            if (
                getattr(existing_handler, "_card_profit_diagnostics", False)
                and isinstance(existing_handler, logging.FileHandler)
                and Path(existing_handler.baseFilename) == target
            ):
                return LocalLoggerSetup(logger=logger, enabled=True)

        _close_managed_handlers(logger)
        handler = logging.FileHandler(target, encoding="utf-8")
        secure_optional_private_file(target)
        handler._card_profit_diagnostics = True
        formatter = logging.Formatter(
            "%(asctime)sZ level=%(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception:
        if handler is not None and handler not in logger.handlers:
            handler.close()
        _close_managed_handlers(logger)
        null_handler = logging.NullHandler()
        null_handler._card_profit_diagnostics = True
        logger.addHandler(null_handler)
        return LocalLoggerSetup(
            logger=logger,
            enabled=False,
            warning=LOGGER_WARNING,
        )
    return LocalLoggerSetup(logger=logger, enabled=True)


def log_sanitized_exception(
    logger: logging.Logger,
    event_code: str,
    error: BaseException,
    operational_context: str,
) -> None:
    try:
        logger.error(
            format_exception_diagnostic(
                event_code,
                error,
                operational_context,
            )
        )
    except Exception:
        return


def run_startup_steps(
    steps: Iterable[StartupStep],
    on_error: Callable[[str, BaseException, str], None] | None = None,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for step in steps:
        try:
            results[step.key] = step.operation()
        except Exception as exc:
            if on_error is not None:
                try:
                    on_error(step.error_code, exc, f"startup.{step.key}")
                except Exception:
                    pass
            raise ApplicationStartupError(
                step.error_code,
                step.public_message,
            ) from None
    return results


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_path_exists(path: Path) -> bool:
    try:
        return Path(path).exists()
    except (OSError, TypeError):
        return False


def _read_application_version(path: Path) -> str:
    try:
        candidate = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, TypeError, UnicodeError):
        return "unknown"
    return candidate if _SAFE_VERSION.fullmatch(candidate) else "unknown"


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in _DEPENDENCIES:
        try:
            candidate = version(package)
        except Exception:
            candidate = "unavailable"
        versions[package] = (
            candidate if _SAFE_VERSION.fullmatch(candidate) else "unavailable"
        )
    return versions


def _configured(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _environment_state(value: Any) -> str:
    if not _configured(value):
        return "missing"
    normalized = value.strip().lower()
    return normalized if normalized in {"sandbox", "production"} else "invalid"


def build_sanitized_diagnostics(
    *,
    environ: Mapping[str, str],
    version_path: Path,
    database_path: Path,
    settings_path: Path,
    valuation_path: Path,
    output_path: Path,
    supported_schema_version: int,
    local_logging_enabled: bool,
) -> dict[str, Any]:
    return {
        "generated_at_utc": _generated_at(),
        "startup_status": "ready",
        "application_version": _read_application_version(version_path),
        "python_version": platform.python_version(),
        "dependencies": _dependency_versions(),
        "ebay_environment": _environment_state(environ.get("EBAY_ENVIRONMENT")),
        "ebay_client_id_configured": _configured(
            environ.get("EBAY_CLIENT_ID")
        ),
        "ebay_client_secret_configured": _configured(
            environ.get("EBAY_CLIENT_SECRET")
        ),
        "database_present": _safe_path_exists(database_path),
        "settings_file_present": _safe_path_exists(settings_path),
        "valuation_file_present": _safe_path_exists(valuation_path),
        "output_directory_present": _safe_path_exists(output_path),
        "supported_schema_version": int(supported_schema_version),
        "local_diagnostic_logging": (
            "enabled" if local_logging_enabled else "unavailable"
        ),
    }


def startup_failure_diagnostics(error: ApplicationStartupError) -> dict[str, str]:
    return {
        "generated_at_utc": _generated_at(),
        "startup_status": "failed",
        "diagnostic_code": error.code,
    }
