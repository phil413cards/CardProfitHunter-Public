from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from grading_labels import has_grading_language
from text_safety import safe_text


RAW_SINGLE_CARD = "RAW_SINGLE_CARD"
RAW_PARALLEL = "RAW_PARALLEL"
RAW_AUTOGRAPH = "RAW_AUTOGRAPH"
GRADED_CARD = "GRADED_CARD"
PLAYER_LOT = "PLAYER_LOT"
TEAM_LOT = "TEAM_LOT"
PICK_YOUR_CARD = "PICK_YOUR_CARD"
BOX_BREAK = "BOX_BREAK"
SEALED_PRODUCT = "SEALED_PRODUCT"
RANDOMIZED_PRODUCT = "RANDOMIZED_PRODUCT"
DIGITAL_CARD = "DIGITAL_CARD"
REDEMPTION_LISTING = "REDEMPTION_LISTING"
REPRINT_CUSTOM = "REPRINT_CUSTOM"
DAMAGED_CARD = "DAMAGED_CARD"
NON_ACTUAL_OR_PRESALE = "NON_ACTUAL_OR_PRESALE"
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
    r"\b(?:trading\s+)?cards?\s+(?:display\s+)?(?:stands?|frames?|binders?)\b",
    r"\b(?:trading\s+)?cards?\s+storage\s+(?:box(?:es)?|cases?)\b",
    r"\b(?:acrylic|magnetic|protective)\s+(?:trading\s+)?cards?\s+"
    r"(?:displays?|stands?|holders?|frames?|cases?)\b",
    r"\b(?:trading\s+)?cards?\s+(?:holders?|cases?)\s+only\b",
    r"\b(?:penny|card)\s+sleeves\b",
    r"\bteam\s+bags\b",
    r"\b(?:toploaders?|top loaders?)\s+(?:lot|pack|bundle|case|box)\b",
    r"\b(?:lot|pack|bundle|case|box)\s+of\s+(?:\d+\s+)?"
    r"(?:toploaders?|top loaders?|penny sleeves|card sleeves)\b",
    r"\bempty\s+(?:wrappers?|packaging)\b",
    r"\b(?:wrappers?|packages?|packaging|labels?|coa)\s+only\b",
    r"\b(?:cards?\s+not|no\s+(?:actual\s+)?cards?)\s+included\b",
    r"\bwithout\s+(?:an?\s+)?(?:actual\s+)?cards?\b",
    r"\b(?:card|autograph)\s+"
    r"(?:grading|cleaning|authentication|restoration|consignment|submission)\s+"
    r"services?\b",
    r"\breplacement\s+(?:slab\s+)?labels?\b",
)

NO_CARD_TITLE_PATTERNS = (
    r"\bno\s+(?:actual\s+)?cards?\s*$",
)

STRONG_NON_CARD_OBJECT_PATTERNS = (
    r"\b(?:signed|autographed)\s+(?:official\s+)?"
    r"(?:baseballs?|footballs?|basketballs?|softballs?|soccer balls?|"
    r"hockey pucks?|pucks?)\b(?!\s+cards?\b)",
    r"\b(?:baseballs?|footballs?|basketballs?|softballs?|soccer balls?|"
    r"hockey pucks?|pucks?)\s+(?:signed|autographed)\b",
    r"\b(?:signed|autographed)\s+(?:8\s*[x×]\s*10\s+)?"
    r"(?:photos?|photographs?|photo prints?)\b"
    r"(?!\s+(?:variations?|cards?)\b)",
    r"\b8\s*[x×]\s*10\s+(?:photos?|photographs?|prints?)\b",
    r"\b(?:signed|autographed)\s+(?:mini\s+)?helmets?\b"
    r"(?!\s+(?:cards?|patch|relic)\b)",
    r"\b(?:mini\s+)?helmets?\s+(?:signed|autographed)\b",
    r"\bmini\s+helmets?\b(?!\s+(?:cards?|patch|relic)\b)",
    r"\bcoins?\b(?!\s+(?:cards?|relic|insert)\b)",
    r"\bbooks?\b(?!\s+(?:cards?|value)\b)",
    r"\b(?:signed|autographed)\s+(?:game[ -]worn\s+)?"
    r"(?:baseball\s+|football\s+|basketball\s+|hockey\s+)?jerseys?\b"
    r"(?!\s+(?:cards?|patch|relic)\b)",
    r"\bjerseys?\s+(?:signed|autographed)\b",
    r"\b(?:signed|autographed)\s+(?:game[ -]used\s+)?"
    r"(?:bats?|gloves?|cleats?|shoes?)\b"
    r"(?!\s+(?:cards?|patch|relic)\b)",
    r"\b(?:bats?|gloves?|cleats?|shoes?)\s+(?:signed|autographed)\b",
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
    r"\b(?:rookie|jersey|patch|relic|autograph(?:ed|s)?|auto|signed|insert) cards?\b",
    r"\bon[ -]card auto(?:graph)?\b",
    r"\bcards?\s*#\s*[a-z0-9-]+\b",
    r"\b(?:refractor|prizm|parallel|mojo|shimmer|rookie card|rc)\b",
)

MULTI_CARD_SEGMENT_EVIDENCE_PATTERNS = (
    r"\b(?:refractor|crackle foil|foil|prizm|parallel|mojo|shimmer|wave|disco)\b",
    r"\b(?:rookie card|rc|autograph(?:ed|s)?|auto|signed|patch|relic|jersey)\b",
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

REDEMPTION_LISTING_PATTERNS = (
    r"\bredemption\b",
    r"\b(?:panini|rewards?|wild card)\s+points?\b",
    r"\bpoints?\s+cards?\b",
    r"\bcode\s+cards?\b",
    r"\bdigital\s+code\b",
    r"\bhome\s+run\s+challenge\b",
    r"\b(?:unused|scratch(?:ed)?)\s+code\b",
    r"\bqr\s+code\b",
)

REPRINT_CUSTOM_PATTERNS = (
    r"\breprint\b",
    r"\brp\b",
    r"\bfacsimile\b",
    r"\bproxy\b",
    r"\bcustom\b",
    r"\bart card\b",
    r"\breplica\b",
    r"\breproduction\b",
    r"\brepro\b",
    r"\bunlicensed\b",
    r"\bunauthorized\b",
    r"\bfan[ -]?art\b",
    r"\baceo\b",
    r"\bnovelty\b",
    r"\bhomemade\b",
    r"\bcounterfeit\b",
    r"\bfake\b",
    r"\bbootleg\b",
    r"\bunofficial\b",
    r"\bnot[ -]+licensed\b",
    r"\bnon[ -]?licensed\b",
    r"\bfan[ -]?made\b",
    r"\bhand[ -]?made\b",
    r"\borica\b",
    r"\bparody\s+cards?\b",
    r"\b(?:ai|artificial intelligence)[ -]?generated\s+cards?\b",
    r"\bconcept\s+cards?\b",
    r"\baftermarket\s+cards?\b",
)

DAMAGE_PATTERNS = (
    r"\bdamag(?:e|ed)\b",
    r"\bcreas(?:e[ds]?|ing)\b",
    r"\bbent\b",
    r"\bpeel(?:ed|ing)?\b",
    r"\bstain(?:ed|s|ing)?\b",
    r"\bscratch(?:ed|es|ing)?\b",
    r"\bprint lines?\b",
    r"\boff[ -]?cent(?:er|re)(?:ed)?\b",
    r"\boc\b",
    r"\bdents?\b",
    r"\bdimples?\b",
    r"\b(?:corner|edge) wear\b",
    r"\bsoft corners?\b",
    r"\brounded corners?\b",
    r"\bcorner dings?\b",
    r"\bsurface issues?\b",
    r"\bwhitening\b",
    r"\bchipp(?:ed|ing)\b",
    r"\bscuff(?:ed|s|ing)?\b",
    r"\bfad(?:ed|ing)\b",
    r"\bpaper loss\b",
    r"\bpoor condition\b",
    r"\bwater damage\b",
    r"\bcorner damage\b",
    r"\bsurface damage\b",
    r"\btrim(?:med|ming)\b",
    r"\baltered\b",
    r"\brestored\b",
    r"\bcolor added\b",
    r"\bevidence of trimming\b",
    r"\bminimum size(?: requirement)?\b",
)

NON_DEFECT_DISCLOSURE_PATTERNS = (
    r"\bno(?: visible| signs? of)? (?:damage|creases?|peeling|stains?|"
    r"scratches?|print lines?|off[ -]?centering|dents?|dimples?|corner wear|"
    r"edge wear|surface issues?|whitening|chipping|scuffs?|fading|paper loss|"
    r"trimming|alteration)\b",
    r"\bnot (?:damaged|creased|bent|peeled|stained|scratched|off[ -]?center|"
    r"dented|dimpled|scuffed|faded|trimmed|altered|restored)\b",
    r"\b(?:damage|crease|scratch|stain|dent|dimple|scuff|whitening|chipping)"
    r"[ -]free\b",
    r"\bscratch[ -](?:free|resistant|proof)\b",
)

NON_ACTUAL_OR_PRESALE_PATTERNS = (
    r"\bpre[ -]?sales?\b",
    r"\bpre[ -]?orders?\b",
    r"\bnot[ -]+in[ -]+hand\b",
    r"\bships?\s+(?:when|once)\s+(?:received|available)\b",
    r"\bships?\s+(?:after|upon)\s+release\b",
    r"\bnot\s+yet\s+released\b",
    r"\b(?:stock|sample|example|representative)\s+"
    r"(?:photos?|images?|pictures?)\b",
    r"\b(?:photos?|images?|pictures?)\s+(?:(?:is|are)\s+)?"
    r"(?:a\s+)?(?:stock|sample|example|representative)\b",
    r"\b(?:photos?|images?|pictures?)\s+(?:(?:is|are)\s+)?not\s+"
    r"(?:of\s+)?(?:the\s+)?actual\s+(?:card|item)\b",
    r"\bactual\s+(?:card|item)\s+(?:is\s+)?not\s+"
    r"(?:shown|pictured)\b",
    r"\b(?:photos?|images?|pictures?)\s+may\s+vary\b",
)

MULTI_CARD_LISTING_PATTERNS = (
    r"\bcomplete (?:baseball |football |basketball |hockey |trading card )?set\b",
    r"\bfactory (?:card )?set\b",
    r"\b\d+\s*cards?\s+(?:bundle|set|collection)\b",
    r"\b(?:bundle|collection)\s+of\s+\d+\s*cards?\b",
    r"\bcards?\s+bundle\b",
    r"\bmulti[ -]card\s+(?:listing|bundle|set|collection)\b",
    r"\buncut\s+(?:trading\s+)?(?:cards?\s+)?(?:sheets?|panels?|strips?)\b",
    r"\b(?:sheets?|panels?|strips?)\s+of\s+(?:\d+\s+)?cards?\b",
    r"\b\d+\s*[- ]\s*cards?\s+(?:sheets?|panels?|strips?)\b",
    r"\b(?:press|sell|proof|promo|sticker|tattoo)\s+sheets?\b",
    r"\b(?:trading\s+)?cards?\s+sheets?\b",
    r"\b(?:mini|souvenir)\s+(?:cards?\s+)?sheets?\b",
)

MULTI_CARD_QUANTITY_COUNT = r"(?:[2-9]|[1-9]\d+)"
MULTI_CARD_QUANTITY_WORD = (
    r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen)"
)

MULTI_CARD_QUANTITY_PATTERNS = (
    rf"\b(?:qty|quantity)\s*:?\s*(?:[x×]\s*)?{MULTI_CARD_QUANTITY_COUNT}\b",
    r"\blot\s+(?:of\s+)?(?:\(\s*|\[\s*)?"
    rf"{MULTI_CARD_QUANTITY_COUNT}(?:\s*\)|\s*\])?(?:\s|$)",
    rf"\blot\s*[x×]\s*{MULTI_CARD_QUANTITY_COUNT}\b",
    rf"\b{MULTI_CARD_QUANTITY_COUNT}\s+(?:copies|cards)\b",
    r"\b(?:both|pair|duo)\s+(?:cards|copies)\b",
    rf"\b(?:set|bundle|collection)\s+of\s+{MULTI_CARD_QUANTITY_COUNT}\s+cards?\b",
    rf"\b{MULTI_CARD_QUANTITY_COUNT}\s*[- ]\s*cards?\s+"
    r"(?:lot|bundle|set|collection)\b",
    rf"\b{MULTI_CARD_QUANTITY_WORD}\s+(?:copies|cards)\b",
    r"\b(?:pair|duo)\s+of\s+(?=(?:19|20)\d{2}\b)",
    r"\b(?:pair|duo)\s+of\b[^\n]{0,120}\bcards\b",
    r"\b(?:multiple|assorted|various|several)\s+cards?\b",
    r"\b(?:mixed|bulk)\s+(?:trading\s+)?cards?\b",
    r"\b(?:mixed\s+)?(?:trading\s+)?card\s+lot\b",
    r"\blot\s+of\s+(?:trading\s+)?cards\b",
    rf"\b(?:includes?|contains?|receive|gets?)\s+{MULTI_CARD_QUANTITY_COUNT}\s+cards?\b",
    rf"\byou\s+(?:will\s+)?(?:receive|get)\s+{MULTI_CARD_QUANTITY_COUNT}\s+cards?\b",
    rf"\b{MULTI_CARD_QUANTITY_COUNT}\s*[- ]\s*card\s+combo\b",
    rf"\b(?:choose|pick)\s+(?:any\s+)?{MULTI_CARD_QUANTITY_COUNT}\s+cards\b",
)

MULTIPLIER_DESCRIPTOR_PREFIXES = (
    r"mvp\b",
    r"all[ -]?star\b",
    r"world series\b",
    r"cy young\b",
    r"rookie of the year\b",
    r"super bowl\b",
    r"champion\b",
    r"time\b",
    r"way\b",
    r"sport\b",
)

SEALED_PRODUCT_PATTERNS = (
    r"\b(?:hobby|blaster|mega|retail|hanger|display|booster|value|collector|empty)"
    r"\s+(?:box|case)\b",
    r"\b(?:sealed|factory sealed)\s+(?:box|case|pack|product)\b",
    r"\bfactory sealed\b",
    r"\b(?:mega|collector)\s+tin\b",
    r"\b(?:unopened|sealed|single|hobby|retail|fat|cello|value|rack|jumbo|booster)"
    r"\s+packs?\b",
    r"\b(?:box|case)\s+of\s+\d+\s+packs?\b",
    r"(?<!/)\b\d+\s+(?:unopened\s+|sealed\s+)?packs?\b",
)

RANDOMIZED_PRODUCT_PATTERNS = (
    r"\bmystery\s+(?:box(?:es)?|packs?|cards?|hits?|lots?|bundles?|repacks?)\b",
    r"\brepacks?\b",
    r"\brepacked\b",
    r"\bgrab[ -]?bags?\b",
    r"\bblind\s+(?:bags?|packs?|box(?:es)?)\b",
    r"\brandom(?:ly selected)?\s+"
    r"(?:cards?|hits?|players?|teams?|packs?|lots?)\b",
    r"\bone\s+(?:random|mystery)\s+(?:cards?|hits?)\b",
    r"\bsurprise\s+(?:cards?|hits?|packs?|box(?:es)?)\b",
    r"\b(?:hot|chase)\s+packs?\b",
    r"\byou\s+(?:will|may)\s+receive\s+(?:a|one)\s+random\b",
)

BREAK_LISTING_PATTERNS = (
    r"\b(?:box|case|group|live|team|player|division|conference|personal)\s+breaks?\b",
    r"\bbreaks?\s+(?:spot|slot|entry|filler|credit|auction|stream|service)s?\b",
    r"\b(?:player|team|division|conference)\s+(?:break\s+)?(?:spot|slot)s?\b",
    r"\bspots?\s+in\s+(?:the\s+)?(?:box|case|group|team|player|division)?\s*break\b",
    r"\bpick\s+your\s+(?:team|player)\b",
    r"\bpyt\b",
    r"\brip\s*(?:and|&|n)\s*ship\b",
    r"\blive\s+rips?\b",
    r"\bgroup\s+rip\b",
    r"\b(?:box|case|pack)\s+opening\b",
)

CHOICE_LISTING_PATTERNS = (
    r"\b(?:u|you)\s+(?:pick|choose|select)\b",
    r"\b(?:pick|choose|select)\s+(?:your|a)\s+cards?\b",
    r"\b(?:pick|choose|select)\s+one\b",
    r"\b(?:pick|choose|select)\s+from\s+(?:the\s+)?"
    r"(?:list|menu|drop[ -]?down)\b",
    r"\bcards?\s+of\s+your\s+choice\b",
    r"\bchoice\s+of\s+(?:cards?|items?)\b",
    r"\bcomplete\s+your\s+set\b",
    r"\bprice\s+per\s+card\b",
    r"\bcards?\s+(?:sold\s+)?individually\b",
    r"\bone\s+card\s+per\s+(?:purchase|order)\b",
    r"\beach\s+card\s+(?:is\s+)?(?:sold\s+)?separately\b",
    r"\b(?:multiple|many)\s+cards?\s+available\b",
)

SINGLE_CARD_PACK_CONTEXT_PATTERNS = (
    r"\bpack[ -](?:fresh|pulled)\b",
    r"\b(?:fresh|pulled)\s+from\s+(?:a\s+)?pack\b",
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
    text = safe_text(value).lower().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _combined_text(title: Any, condition: Any = "") -> str:
    return _normalized(f"{safe_text(title)} {safe_text(condition)}")


def _has(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _is_non_card_merchandise(text: str) -> bool:
    if _has(text, HARD_NON_CARD_PATTERNS + STRONG_NON_CARD_OBJECT_PATTERNS):
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


def _starts_with_multiplier_descriptor(text: str) -> bool:
    return any(
        re.match(pattern, text)
        for pattern in MULTIPLIER_DESCRIPTOR_PREFIXES
    )


def _looks_like_multi_quantity_listing(text: str) -> bool:
    if _has(text, MULTI_CARD_QUANTITY_PATTERNS):
        return True

    multiplier = re.match(
        rf"^\s*{MULTI_CARD_QUANTITY_COUNT}\s*[x×]\s+(.+)$",
        text,
    )
    if multiplier:
        remainder = multiplier.group(1)
        if not _starts_with_multiplier_descriptor(remainder):
            return _has(text, TRADING_CARD_EVIDENCE_PATTERNS)

    reverse_multiplier = re.match(
        rf"^\s*[x×]\s*{MULTI_CARD_QUANTITY_COUNT}\s+",
        text,
    )
    if reverse_multiplier and _has(text, TRADING_CARD_EVIDENCE_PATTERNS):
        return True

    parenthesized_quantity = re.match(
        rf"^\s*[\[(]\s*{MULTI_CARD_QUANTITY_COUNT}\s*[\])]\s+",
        text,
    )
    if parenthesized_quantity and _has(text, TRADING_CARD_EVIDENCE_PATTERNS):
        return True

    word_quantity = re.match(
        rf"^\s*{MULTI_CARD_QUANTITY_WORD}\s+(.+)$",
        text,
    )
    if word_quantity:
        remainder = word_quantity.group(1)
        if not _starts_with_multiplier_descriptor(remainder):
            return _has(text, TRADING_CARD_EVIDENCE_PATTERNS)

    return False


def _has_ambiguous_condition_language(text: str) -> bool:
    return _has(text, CONDITION_AMBIGUITY_PATTERNS)


def _looks_like_sealed_product(text: str) -> bool:
    if _has(text, SEALED_PRODUCT_PATTERNS):
        return True
    return bool(
        re.search(r"\bpack\b", text)
        and not _has(text, SINGLE_CARD_PACK_CONTEXT_PATTERNS)
    )


def has_trading_card_evidence(title: Any, condition: Any = "") -> bool:
    """Return whether listing text contains positive trading-card evidence."""
    text = _combined_text(title, condition)
    return _has(text, TRADING_CARD_EVIDENCE_PATTERNS) or _has(
        text,
        SINGLE_CARD_MULTI_PLAYER_PATTERNS,
    )


def has_non_card_merchandise_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text identifies merchandise instead of a card."""
    return _is_non_card_merchandise(_combined_text(title, condition)) or _has(
        _normalized(title),
        NO_CARD_TITLE_PATTERNS,
    )


def has_non_actual_or_presale_language(
    title: Any,
    condition: Any = "",
) -> bool:
    """Return whether the listing lacks an immediately inspectable actual item."""
    text = _combined_text(title, condition)
    return _has(text, NON_ACTUAL_OR_PRESALE_PATTERNS)


def has_damage_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text affirmatively discloses a material defect."""
    text = _combined_text(title, condition)
    for pattern in NON_DEFECT_DISCLOSURE_PATTERNS:
        text = re.sub(pattern, " ", text)
    return _has(text, DAMAGE_PATTERNS)


def has_reprint_custom_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text identifies a reproduction or custom card."""
    text = _combined_text(title, condition)
    return _has(text, REPRINT_CUSTOM_PATTERNS)


def has_randomized_product_language(title: Any, condition: Any = "") -> bool:
    """Return whether the buyer receives an unspecified randomized product."""
    text = _combined_text(title, condition)
    return _has(text, RANDOMIZED_PRODUCT_PATTERNS)


def has_break_listing_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text sells access to a break or opening service."""
    text = _combined_text(title, condition)
    return _has(text, BREAK_LISTING_PATTERNS)


def has_choice_listing_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text requires choosing an item from inventory."""
    text = _combined_text(title, condition)
    return _has(text, CHOICE_LISTING_PATTERNS)


def has_multi_card_listing_language(title: Any, condition: Any = "") -> bool:
    """Return whether listing text describes more than one purchased card."""
    text = _combined_text(title, condition)
    return (
        _looks_like_plus_separated_bundle(text)
        or _looks_like_multi_quantity_listing(text)
        or _has(text, MULTI_CARD_LISTING_PATTERNS)
        or _has(
            text,
            (
                r"\bteam (?:lot|set)\b",
                r"\bplayer lot\b",
                r"\blot of \d+\b",
                r"\b\d+ card lot\b",
                r"\bcards lot\b",
            ),
        )
    )


def classify_listing(title: Any, condition: Any = "") -> ListingClassification:
    normalized_title = _normalized(title)
    text = _combined_text(title, condition)

    graded = has_grading_language(title, condition)
    damaged = has_damage_language(title, condition)
    autograph = _has(
        text,
        (r"\b(?:autos?|autographs?|autographed|signed)\b", r"\bon card auto\b"),
    )
    parallel = _has(text, (
        r"\brefractor\b", r"\bprizm\b", r"\bparallel\b", r"\bwave\b",
        r"\bmojo\b", r"\bshimmer\b", r"\bdisco\b", r"\bcolor match\b",
        r"\b(?:gold|orange|red|blue|green|purple|black|white|silver)\b",
        r"(?<!\d)\d{1,4}\s*/\s*\d{1,4}(?!\d)", r"\bnumbered\b",
    ))

    if not normalized_title:
        cls, reason = UNKNOWN, "missing_title"
    elif has_non_card_merchandise_language(title, condition):
        cls, reason = NON_CARD_MERCHANDISE, "non_card_merchandise"
    elif _looks_like_plus_separated_bundle(text):
        cls, reason = MULTI_CARD_LISTING, "plus_separated_multi_card_listing"
    elif _has_ambiguous_condition_language(text):
        cls, reason = CONDITION_AMBIGUOUS, "condition_ambiguous"
    elif has_choice_listing_language(title, condition):
        cls, reason = PICK_YOUR_CARD, "pick_your_card"
    elif has_break_listing_language(title, condition):
        cls, reason = BOX_BREAK, "break_listing"
    elif has_randomized_product_language(title, condition):
        cls, reason = RANDOMIZED_PRODUCT, "randomized_product"
    elif _has(text, REDEMPTION_LISTING_PATTERNS):
        cls, reason = REDEMPTION_LISTING, "redemption_or_code_listing"
    elif _has(text, (r"\bdigital\b", r"\bnft\b", r"\btopps bunt\b")):
        cls, reason = DIGITAL_CARD, "digital_card"
    elif has_reprint_custom_language(title, condition):
        cls, reason = REPRINT_CUSTOM, "reprint_or_custom"
    elif has_non_actual_or_presale_language(title, condition):
        cls, reason = NON_ACTUAL_OR_PRESALE, "presale_or_non_actual_item"
    elif _has(text, (r"\bteam lot\b", r"\bteam set\b")):
        cls, reason = TEAM_LOT, "team_lot"
    elif _has(text, (r"\bplayer lot\b",)):
        cls, reason = PLAYER_LOT, "player_or_multi_card_lot"
    elif _has(text, MULTI_CARD_LISTING_PATTERNS):
        cls, reason = MULTI_CARD_LISTING, "multi_card_set_or_bundle"
    elif _looks_like_multi_quantity_listing(text):
        cls, reason = MULTI_CARD_LISTING, "multi_card_quantity"
    elif _has(text, (r"\blot of \d+\b", r"\b\d+ card lot\b", r"\bcards lot\b")):
        cls, reason = PLAYER_LOT, "player_or_multi_card_lot"
    elif _looks_like_sealed_product(text):
        cls, reason = SEALED_PRODUCT, "sealed_product"
    elif damaged:
        cls, reason = DAMAGED_CARD, "damage_language"
    elif graded:
        cls, reason = GRADED_CARD, "graded_card"
    elif not has_trading_card_evidence(title, condition):
        cls, reason = UNKNOWN, "insufficient_trading_card_evidence"
    elif autograph:
        cls, reason = RAW_AUTOGRAPH, ""
    elif parallel:
        cls, reason = RAW_PARALLEL, ""
    elif normalized_title:
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
