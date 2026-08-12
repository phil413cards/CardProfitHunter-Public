from __future__ import annotations

from pathlib import PurePosixPath
import subprocess
import sys
from typing import Iterable


FORBIDDEN_DIRECTORY_NAMES = {
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "env",
    "htmlcov",
    "logs",
    "output",
    "venv",
}

FORBIDDEN_FILE_NAMES = {
    ".coverage",
    "ebay_token.json",
    "oauth_token.json",
    "token_cache.json",
}

FORBIDDEN_SUFFIXES = {
    ".db",
    ".log",
    ".sqlite",
    ".sqlite3",
}


def is_forbidden_tracked_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parsed = PurePosixPath(normalized)
    name = parsed.name

    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name in FORBIDDEN_FILE_NAMES:
        return True
    if parsed.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return True
    return any(part in FORBIDDEN_DIRECTORY_NAMES for part in parsed.parts)


def find_forbidden_tracked_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(path for path in paths if is_forbidden_tracked_path(path)))


def read_tracked_paths() -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return tuple(
        value.decode("utf-8", errors="surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    )


def main() -> int:
    try:
        forbidden = find_forbidden_tracked_paths(read_tracked_paths())
    except (OSError, subprocess.SubprocessError):
        print("Tracked-artifact check could not be completed.", file=sys.stderr)
        return 2

    if forbidden:
        print("Private runtime artifacts must not be tracked:", file=sys.stderr)
        for path in forbidden:
            print(f"- {path!r}", file=sys.stderr)
        return 1

    print("Tracked private runtime artifact check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
