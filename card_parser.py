from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Optional

from grading_labels import (
    GRADER_LABEL_PATTERN,
    GRADER_LABELS,
    extract_grading_grade,
)
from text_safety import safe_text


MANUFACTURERS = ("topps", "bowman", "panini", "donruss", "upper deck", "fleer")
PRODUCTS = ("chrome", "prizm", "select", "optic", "mosaic", "finest", "heritage", "update", "stadium club")
PARALLELS = (
    "gold wave", "orange wave", "blue wave", "green wave", "red wave",
    "gold refractor", "orange refractor", "blue refractor", "green refractor",
    "red refractor", "silver prizm", "x-fractor", "xfractor", "mojo",
    "shimmer", "refractor", "atomic", "speckle", "disco", "wave",
    "gold", "orange", "red", "blue", "green", "purple", "black", "silver",
)
GRADERS = GRADER_LABELS


@dataclass(frozen=True)
class CardIdentity:
    player: str
    year: Optional[int]
    manufacturer: str
    product: str
    card_number: str
    parallel: str
    serial_number: str
    print_run: Optional[int]
    autograph: bool
    rookie: bool
    grader: str
    grade: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", safe_text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9#/' .+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_phrase(text: str, phrases: tuple[str, ...]) -> str:
    for phrase in sorted(phrases, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text):
            return phrase
    return ""


def _extract_player_from_query(query: str) -> str:
    text = normalize_text(query)
    removals = [
        r"\b(?:19|20)\d{2}\b", r"(?<!\w)#\s*[a-z0-9.-]+",
        rf"(?<![a-z0-9])(?:{GRADER_LABEL_PATTERN})\s*-?\s*"
        r"\d{1,2}(?:\.\d)?(?![a-z0-9])",
        r"\b(?:rookie|rc|raw|autos?|autographs?|autographed|signed|card|cards)\b",
    ]
    for term in MANUFACTURERS + PRODUCTS + PARALLELS:
        removals.append(rf"\b{re.escape(term)}\b")
    for pattern in removals:
        text = re.sub(pattern, " ", text)
    return re.sub(r"\s+", " ", text).strip().title()


def parse_card_identity(title: str, query: str = "") -> CardIdentity:
    text = normalize_text(title)
    query_text = normalize_text(query)
    year_match = re.search(r"\b((?:19|20)\d{2})\b", text)
    number_match = re.search(r"(?<!\w)#\s*([a-z0-9]+(?:[-.][a-z0-9]+)*)", text)
    if not number_match:
        number_match = re.search(r"\b(?:no|number)\.?\s*#?\s*([a-z0-9]+(?:[-.][a-z0-9]+)*)\b", text)
    serial_match = re.search(r"(?<!\d)(\d{1,4})\s*/\s*(\d{1,4})(?!\d)", text)
    grading_grade = extract_grading_grade(text)

    player = _extract_player_from_query(query_text) if query_text else ""
    return CardIdentity(
        player=player,
        year=int(year_match.group(1)) if year_match else None,
        manufacturer=_first_phrase(text, MANUFACTURERS).title(),
        product=_first_phrase(text, PRODUCTS).title(),
        card_number=number_match.group(1).upper() if number_match else "",
        parallel=_first_phrase(text, PARALLELS).title(),
        serial_number=(f"{serial_match.group(1)}/{serial_match.group(2)}" if serial_match else ""),
        print_run=int(serial_match.group(2)) if serial_match else None,
        autograph=bool(
            re.search(r"\b(?:autos?|autographs?|autographed|signed)\b", text)
        ),
        rookie=bool(re.search(r"\b(?:rookie|rc)\b", text)),
        grader=grading_grade[0] if grading_grade else "",
        grade=grading_grade[1] if grading_grade else None,
    )
