from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


RAW_SINGLE_CARD = "RAW_SINGLE_CARD"
RAW_PARALLEL = "RAW_PARALLEL"
RAW_AUTOGRAPH = "RAW_AUTOGRAPH"
GRADED_CARD = "GRADED_CARD"
PLAYER_LOT = "PLAYER_LOT"
TEAM_LOT = "TEAM_LOT"
PICK_YOUR_CARD = "PICK_YOUR_CARD"
BOX_BREAK = "BOX_BREAK"
SEALED_PRODUCT = "SEALED_PRODUCT"
DIGITAL_CARD = "DIGITAL_CARD"
REPRINT_CUSTOM = "REPRINT_CUSTOM"
DAMAGED_CARD = "DAMAGED_CARD"
NON_CARD_MERCHANDISE = "NON_CARD_MERCHANDISE"
MULTI_CARD_LISTING = "MULTI_CARD_LISTING"
CONDITION_AMBIGUOUS = "CONDITION_AMBIGUOUS"
UNKNOWN = "UNKNOWN"

ACTIONABLE_CLASSES = {RAW_SINGLE_CARD, RAW_PARALLEL, RAW_AUTOGRAPH}

HARD_NON_CARD_PATTERNS = (
    r"\bbobblehead\b",
    r"\bfunko\b",
    r"\bpop vinyl\b",
    r"\bfigurine\b",
    r"\baction figure\b",
    r"\bstatue\b",
    r"\bplush\b",
    r"\bposter\b",
    r"\bplaque\b",
    r"\bcanvas\b",
    r"\bwall art\b",
    r"\bphotograph\b",
    r"\bphoto print\b",
    r"\bmagazine\b",
    r"\bcomic book\b",
    r"\bkeychain\b",
    r"\blanyard\b",
    r"\bmug\b",
    r"\btumbler\b",
)

APPAREL_PATTERNS = (
    r"\bhat\b",
    r"\bcap\b",
    r"\b59fifty\b",
    r"\b9fifty\b",
    r"\b9forty\b",
    r"\bnew era\b",
    r"\bsnapback\b",
    r"\bfitted\b",
    r"\bbeanie\b",
    r"\bhoodie\b",
    r"\bsweatshirt\b",
    r"\bt-?shirt\b",
    r"\btee shirt\b",
    r"\bshirt\b",
    r"\bjacket\b",
    r"\bjersey\b",
    r"\bshorts\b",
    r"\bsocks\b",
    r"\bshoes?\b",
    r"\bcleats?\b",
)

TRADING_CARD_EVIDENCE_PATTERNS = (
    r"\b(?:topps|bowman|panini|donruss|prizm|optic|select|mosaic)\b",
    r"\b(?:national treasures|immaculate|flawless|contenders)\b",
    r"\b(?:hoops|upper deck|leaf|fleer|skybox|finest|heritage|stadium club)\b",
    r"\b(?:trading|sports|baseball|football|basketball|hockey) cards?\b",
    r"\b(?:rookie|jersey|patch|relic|autograph|auto|insert) cards?\b",
    r"\bcards?\s*#\s*[a-z0-9-]+\b",
    r"\b(?:refractor|prizm|parallel|mojo|shimmer|rookie card|rc)\b",
)

MULTI_CARD_SEGMENT_EVIDENCE_PATTERNS = (
    r"\b(?:refractor|crackle foil|foil|prizm|parallel|mojo|shimmer|wave|disco)\b",
    r"\b(?:rookie card|rc|autograph|auto|patch|relic|jersey)\b",
    r"\b(?:topps|bowman|panini|donruss|optic|select|mosaic|upper deck)\b",
    r"#\s*[a-z0-9][a-z0-9-]*\b",
    r"(?<!\d)\d{1,4}\s*/\s*\d{1,4}(?!\d)",
)

SINGLE_CARD_MULTI_PLAYER_PATTERNS = (
    r"\b(?:dual|triple|quad)\s+(?:auto(?:graph)?|relic|patch|jersey|memorabilia|signature)s?\b",
    r"\bbooklet\b",
    r"\bcombo card\b",
    r"\bco-?signers?\b",
    r"\bdual player\b",
    r"\bteam tandems?\b",
)

CONDITION_AMBIGUITY_PATTERNS = (
    r"\(\s*read\s*\)",
    r"\bplease read\b",
    r"\bread description\b",
    r"\bsee description\b",
    r"\bas is\b",
)


@dataclass(frozen=True)
class ListingClassification:
    listing_class: str
    actionable: bool
    raw: bool
    graded: bool
    single_card: bool
    autograph: bool
    parallel: bool
    damaged: bool
    exclusion_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalized(value: Any) -> str:
    text = str(value or "").lower().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _is_non_card_merchandise(text: str) -> bool:
    if _has(text, HARD_NON_CARD_PATTERNS):
        return True
    return (
        _has(text, APPAREL_PATTERNS)
        and not _has(text, TRADING_CARD_EVIDENCE_PATTERNS)
    )


def _looks_like_plus_separated_bundle(text: str) -> bool:
    if "+" not in text:
        return False
    if _has(text, SINGLE_CARD_MULTI_PLAYER_PATTERNS):
        return False

    segments = [
        segment.strip()
        for segment in re.split(r"\s*\+\s*", text)
        if segment.strip()
    ]
    if len(segments) < 2:
        return False

    evidence_segments = sum(
        1
        for segment in segments
        if _has(segment, MULTI_CARD_SEGMENT_EVIDENCE_PATTERNS)
    )
    return evidence_segments >= 2


def _has_ambiguous_condition_language(text: str) -> bool:
    return _has(text, CONDITION_AMBIGUITY_PATTERNS)


def classify_listing(title: str, condition: str = "") -> ListingClassification:
    text = _normalized(f"{title} {condition}")

    graded = _has(text, (
        r"\b(?:psa|bgs|sgc|cgc|tag)\s*-?\s*\d{1,2}(?:\.\d)?\b",
        r"\bgraded\b", r"\bslab(?:bed)?\b", r"\bgem mint\b",
    ))
    damaged = _has(text, (
        r"\bdamag(?:e|ed)\b", r"\bcrease(?:d)?\b", r"\bbent\b",
        r"\bpeel(?:ing)?\b", r"\bstain(?:ed)?\b", r"\bpoor condition\b",
        r"\bwater damage\b", r"\bcorner damage\b", r"\bsurface damage\b",
    ))
    autograph = _has(text, (r"\bauto(?:graph)?\b", r"\bsigned\b", r"\bon card auto\b"))
    parallel = _has(text, (
        r"\brefractor\b", r"\bprizm\b", r"\bparallel\b", r"\bwave\b",
        r"\bmojo\b", r"\bshimmer\b", r"\bdisco\b", r"\bcolor match\b",
        r"\b(?:gold|orange|red|blue|green|purple|black|white|silver)\b",
        r"(?<!\d)\d{1,4}\s*/\s*\d{1,4}(?!\d)", r"\bnumbered\b",
    ))

    if _is_non_card_merchandise(text):
        cls, reason = NON_CARD_MERCHANDISE, "non_card_merchandise"
    elif _looks_like_plus_separated_bundle(text):
        cls, reason = MULTI_CARD_LISTING, "plus_separated_multi_card_listing"
    elif _has_ambiguous_condition_language(text):
        cls, reason = CONDITION_AMBIGUOUS, "condition_ambiguous"
    elif _has(text, (r"\bpick your card\b", r"\byou pick\b", r"\bchoose (?:one|your card)\b")):
        cls, reason = PICK_YOUR_CARD, "pick_your_card"
    elif _has(text, (r"\bbox break\b", r"\bcase break\b", r"\bgroup break\b", r"\blive break\b")):
        cls, reason = BOX_BREAK, "break_listing"
    elif _has(text, (r"\bdigital\b", r"\bnft\b", r"\btopps bunt\b")):
        cls, reason = DIGITAL_CARD, "digital_card"
    elif _has(text, (r"\breprint\b", r"\bfacsimile\b", r"\bproxy\b", r"\bcustom card\b", r"\bart card\b")):
        cls, reason = REPRINT_CUSTOM, "reprint_or_custom"
    elif _has(text, (r"\bteam lot\b", r"\bteam set\b")):
        cls, reason = TEAM_LOT, "team_lot"
    elif _has(text, (r"\bplayer lot\b", r"\blot of \d+\b", r"\b\d+ card lot\b", r"\bcards lot\b")):
        cls, reason = PLAYER_LOT, "player_or_multi_card_lot"
    elif _has(text, (r"\bhobby box\b", r"\bblaster box\b", r"\bmega box\b", r"\bsealed box\b", r"\bfactory sealed\b", r"\bpack\b")):
        cls, reason = SEALED_PRODUCT, "sealed_product"
    elif damaged:
        cls, reason = DAMAGED_CARD, "damage_language"
    elif graded:
        cls, reason = GRADED_CARD, "graded_card"
    elif autograph:
        cls, reason = RAW_AUTOGRAPH, ""
    elif parallel:
        cls, reason = RAW_PARALLEL, ""
    elif text:
        cls, reason = RAW_SINGLE_CARD, ""
    else:
        cls, reason = UNKNOWN, "missing_title"

    actionable = cls in ACTIONABLE_CLASSES and not damaged and not graded
    return ListingClassification(
        listing_class=cls,
        actionable=actionable,
        raw=cls in ACTIONABLE_CLASSES,
        graded=graded,
        single_card=(
            cls in ACTIONABLE_CLASSES
            or cls in {GRADED_CARD, CONDITION_AMBIGUOUS}
        ),
        autograph=autograph,
        parallel=parallel,
        damaged=damaged,
        exclusion_reason=reason,
    )
