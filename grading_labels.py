from __future__ import annotations

import re
from typing import Any

from text_safety import safe_text


GRADER_ACRONYMS = (
    "psa",
    "bgs",
    "sgc",
    "cgc",
    "tag",
    "hga",
    "csg",
    "gma",
    "isa",
    "ksa",
    "ags",
    "mnt",
    "fcg",
    "bvg",
    "bccg",
)

GRADER_NAMES = (
    "beckett",
    "arena club",
    "rare edition",
    "degree grading",
)

GRADER_LABELS = (*GRADER_ACRONYMS, *GRADER_NAMES)
GRADER_LABEL_PATTERN = "|".join(
    re.escape(label)
    for label in sorted(GRADER_LABELS, key=len, reverse=True)
)

_GRADE_PATTERN = re.compile(
    rf"(?<![a-z0-9])(?P<grader>{GRADER_LABEL_PATTERN})"
    rf"\s*-?\s*(?P<grade>\d{{1,2}}(?:\.\d)?)(?![a-z0-9])",
    re.IGNORECASE,
)

_UNQUALIFIED_LABEL_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:psa|bgs|sgc|cgc|tag|arena\s+club)(?![a-z0-9])",
    re.IGNORECASE,
)

_TITLE_GRADING_PATTERNS = (
    r"\bgraded\b",
    r"\bprofessionally graded\b",
    r"\bslab(?:bed)?\b",
    r"\bgem mint\b",
    r"\bmint\s*10\b",
    r"\bencapsulated\b",
)

_CONDITION_GRADING_PATTERNS = (
    *_TITLE_GRADING_PATTERNS,
    r"\bcertified\b",
)


def _normalized(value: Any) -> str:
    text = safe_text(value).lower().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def extract_grading_grade(value: Any) -> tuple[str, float] | None:
    """Return a recognized grader and numeric grade from listing text."""
    match = _GRADE_PATTERN.search(_normalized(value))
    if match is None:
        return None
    return match.group("grader").upper(), float(match.group("grade"))


def has_grading_language(title: Any, condition: Any = "") -> bool:
    """Return whether title or condition identifies a slabbed/graded card."""
    title_text = _normalized(title)
    condition_text = _normalized(condition)
    return (
        _GRADE_PATTERN.search(title_text) is not None
        or _UNQUALIFIED_LABEL_PATTERN.search(title_text) is not None
        or any(re.search(pattern, title_text) for pattern in _TITLE_GRADING_PATTERNS)
        or any(
            re.search(pattern, condition_text)
            for pattern in _CONDITION_GRADING_PATTERNS
        )
    )
