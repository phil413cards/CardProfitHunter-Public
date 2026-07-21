from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Optional, Any

import pandas as pd


SLAB_WORDS = [
    "psa", "bgs", "sgc", "cgc", "tag", "arena club", "graded", "gem mint",
    "mint 10", "slab", "slabbed"
]

BAD_WORDS = [
    "reprint", "rp", "custom", "facsimile", "digital", "break", "case break",
    "box break", "lot", "lots", "read", "not actual card", "proxy"
]

GOOD_WORDS = [
    "gold", "orange", "red", "black", "white", "green", "blue", "purple",
    "refractor", "prizm", "mosaic", "disco", "shimmer", "wave", "raywave",
    "mojo", "x-fractor", "zebra", "tiger", "elephant", "genesis", "downtown",
    "kaboom", "color match", "auto", "autograph", "rc", "rookie", "ssp", "sp",
    "case hit", "short print", "parallel", "silver", "chrome", "numbered"
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "card", "cards",
    "rookie", "rc", "raw", "psa", "bgs", "sgc", "cgc", "panini", "topps",
    "upper", "deck", "fleer", "donruss", "sports", "trading"
}

IDENTITY_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "card", "cards",
    "raw", "ungraded", "sports", "trading", "sharp", "clean", "nice", "mint",
    "nm", "mt", "condition", "sale", "rare", "authentic", "original", "single",
    "shipping", "free",
}

PRODUCT_SET_TERMS = {
    "bowman", "chrome", "donruss", "finest", "fleer", "mosaic", "optic", "panini",
    "prizm", "select", "topps", "upper", "deck",
}

PARALLEL_TERMS = {
    "base", "black", "blue", "color", "disco", "downtown", "elephant", "genesis",
    "gold", "green", "kaboom", "match", "mojo", "numbered", "orange", "parallel",
    "purple", "raywave", "red", "refractor", "sepia", "shimmer", "short", "silver",
    "sp", "ssp", "tiger", "wave", "white", "xfractor", "zebra",
}

VARIANT_TERMS = {
    "autograph", "custom", "digital", "facsimile", "insert", "proxy", "reprint",
    "rookie",
}

SUPPORTED_BUYING_OPTIONS = {"FIXED_PRICE", "BEST_OFFER"}

ACTIONABLE_ACTIONS = {
    "BUY",
    "OFFER",
    "BUY_RAW_FLIP",
    "BUY_GRADE_PSA",
}

NON_ACTIONABLE_VALUATION_PATTERNS = (
    r"\bexample(?:\s+only)?\b",
    r"\bdemo\b",
    r"\bdemonstration\b",
    r"\bunverified\b",
    r"\bnon[-\s]?actionable\b",
)

REQUIRED_MODELED_COSTS = {
    "ebay_fee_pct": 1.0,
    "raw_flip_shipping_allowance": None,
    "psa_grading_fee": None,
    "psa_shipping_insurance_allowance": None,
    "psa_selling_shipping_allowance": None,
}


@dataclass
class ProfitResult:
    recommended_action: str
    total_score: int
    best_path: str
    best_expected_profit: Optional[float]
    best_expected_roi_pct: Optional[float]

    raw_flip_profit: Optional[float]
    raw_flip_roi_pct: Optional[float]

    psa_expected_profit: Optional[float]
    psa_expected_roi_pct: Optional[float]
    psa_expected_sale_value: Optional[float]

    max_buy_price_raw_flip: Optional[float]
    max_buy_price_psa_flip: Optional[float]
    suggested_offer: Optional[float]

    title: str
    total_price: float
    price: float
    shipping: float
    currency: str
    item_url: str
    image_url: str

    matched_card: str
    match_strength: float
    raw_market_value: Optional[float]
    psa9_value: Optional[float]
    psa10_value: Optional[float]
    gem_rate_estimate: Optional[float]
    psa9_rate_estimate: Optional[float]

    print_run: Optional[int]
    serial_detected: str
    raw_candidate: bool
    flags: str

    seller_username: str
    seller_feedback: Optional[int]
    seller_feedback_pct: Optional[float]
    buying_options: str
    condition: str
    item_end_date: str


@dataclass
class _CardValueMatch:
    row: Optional[pd.Series]
    strength: float
    reason: str = ""


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        if pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _finite_float(value: Any) -> Optional[float]:
    if _is_missing(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _buying_option_set(value: Any) -> set[str]:
    return set(re.findall(r"[A-Z][A-Z0-9_]*", normalize(value).upper()))


def _modeled_cost_flags(settings: dict) -> list[str]:
    flags = []
    for key, maximum in REQUIRED_MODELED_COSTS.items():
        raw_value = settings.get(key)
        if _is_missing(raw_value):
            flags.append(f"missing_modeled_cost_{key}")
            continue

        value = _finite_float(raw_value)
        if value is None or value < 0 or (maximum is not None and value > maximum):
            flags.append(f"invalid_modeled_cost_{key}")
    return flags


def _valuation_is_non_actionable(notes: str) -> bool:
    normalized_notes = normalize(notes).lower()
    return any(
        re.search(pattern, normalized_notes)
        for pattern in NON_ACTIONABLE_VALUATION_PATTERNS
    )


def _floor_currency(value: float) -> float:
    return math.floor(max(value, 0) * 100) / 100


def tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9/ ]", " ", text.lower())
    return {t for t in cleaned.split() if len(t) >= 2 and t not in STOPWORDS}


def contains_term(text: str, terms: list[str]) -> bool:
    """
    Phrase-aware matching.
    Important: avoids false positives like BAD_WORD 'rp' matching 'sharp'.
    """
    lower = text.lower()

    for term in terms:
        t = term.lower().strip()
        if not t:
            continue

        if " " in t or "-" in t:
            if t in lower:
                return True
        else:
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", lower):
                return True

    return False


def _is_slab_listing(title: str, condition: str = "") -> bool:
    compact_grade = re.search(
        r"(?<![a-z0-9])(?:psa|bgs|sgc|cgc)\s*-?\s*\d{1,2}(?:\.\d)?(?![a-z0-9])",
        title.lower(),
    )
    condition_is_graded = contains_term(
        condition,
        ["graded", "slabbed", "certified", "professionally graded"],
    )
    return contains_term(title, SLAB_WORDS) or compact_grade is not None or condition_is_graded


def detect_print_run(title: str) -> tuple[Optional[int], str]:
    t = title.lower()

    if re.search(r"\b1\s*/\s*1\b|\bone\s+of\s+one\b|\btrue\s+1/1\b", t):
        return 1, "1/1"

    patterns = [
        r"(?:^|\s|#)(?:\d{1,4})\s*/\s*(\d{1,4})(?:\s|$|[^\d])",
        r"(?:^|\s|#)/\s*(\d{1,4})(?:\s|$|[^\d])",
        r"\b\d{1,4}\s+of\s+(\d{1,4})\b",
        r"\bout\s+of\s+(\d{1,4})\b",
        r"\bnumbered\s+to\s+(\d{1,4})\b",
        r"\bserial\s+numbered\s+to\s+(\d{1,4})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            try:
                return int(match.group(1)), match.group(0).strip()
            except ValueError:
                continue

    return None, ""


def _normalize_identity_text(text: str) -> str:
    normalized = normalize(text).lower()
    replacements = [
        (r"\bx[\s-]?fractor\b", "xfractor"),
        (r"\brc\b", "rookie"),
        (r"\bautos?\b|\bautographs?\b", "autograph"),
        (r"\binserts?\b", "insert"),
        (r"\breprints?\b", "reprint"),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def _identity_tokens(text: str) -> set[str]:
    normalized = _normalize_identity_text(text)
    return {
        token for token in re.findall(r"[a-z0-9]+", normalized)
        if not token.isdigit() and token not in IDENTITY_STOPWORDS
    }


def _normalize_two_digit_year(value: str) -> str:
    year = int(value)
    return str(2000 + year if year <= 39 else 1900 + year)


def _extract_years(text: str) -> tuple[set[str], bool]:
    normalized = normalize(text).lower().replace("’", "'")
    years = set()
    consumed_spans = []

    for match in re.finditer(r"\b((?:19|20)\d{2})[-/](\d{2})\b", normalized):
        first_year = int(match.group(1))
        second_year = (first_year // 100) * 100 + int(match.group(2))
        if second_year < first_year:
            second_year += 100
        years.update({str(first_year), str(second_year)})
        consumed_spans.append(match.span())

    for match in re.finditer(r"\b(?:19|20)\d{2}\b", normalized):
        if not any(start <= match.start() < end for start, end in consumed_spans):
            years.add(match.group(0))
            consumed_spans.append(match.span())

    for match in re.finditer(r"(?<![a-z0-9])'(\d{2})(?!\d)", normalized):
        years.add(_normalize_two_digit_year(match.group(1)))
        consumed_spans.append(match.span())

    leading_year = re.match(r"^\s*(\d{2})(?=\s)", normalized)
    if leading_year:
        years.add(_normalize_two_digit_year(leading_year.group(1)))
        consumed_spans.append(leading_year.span(1))

    ambiguous = False
    for match in re.finditer(r"(?<!\d)(\d{2})(?!\d)", normalized):
        if any(start <= match.start() and match.end() <= end for start, end in consumed_spans):
            continue
        before = normalized[:match.start()]
        after = normalized[match.end():]
        explicit_number = re.search(r"(?:#|\bno\.?\s*|\bnumber\s*)$", before)
        grader = re.search(r"\b(?:psa|bgs|sgc|cgc)\s*-?\s*$", before)
        excluded_punctuation = before.endswith(("$", "/", ".")) or after.startswith(("/", "."))
        quantity = after.startswith(("x", "×"))
        if int(match.group(1)) <= 39 and not (
            explicit_number or grader or excluded_punctuation or quantity
        ):
            ambiguous = True

    return years, ambiguous


def _extract_card_numbers(text: str) -> tuple[set[str], bool]:
    normalized = normalize(text).lower().replace("’", "'")
    numbers = set(re.findall(r"(?<!\w)#\s*([a-z0-9]+(?:[-.][a-z0-9]+)*)", normalized))
    numbers.update(re.findall(r"\b(?:no|number)\.?\s*#?\s*([a-z0-9]+(?:[-.][a-z0-9]+)*)\b", normalized))

    cleaned = normalized
    removal_patterns = [
        r"(?<!\w)#\s*[a-z0-9]+(?:[-.][a-z0-9]+)*",
        r"\b(?:no|number)\.?\s*#?\s*[a-z0-9]+(?:[-.][a-z0-9]+)*\b",
        r"(?<![a-z0-9])(?:psa|bgs|sgc|cgc)\s*-?\s*\d{1,2}(?:\.\d)?(?![a-z0-9])",
        r"\b(?:19|20)\d{2}(?:[-/]\d{2})?\b",
        r"(?<![a-z0-9])'\d{2}(?!\d)",
        r"^\s*\d{2}(?=\s)",
        r"(?<!\w)\d{1,4}\s*/\s*\d{1,4}(?!\w)",
        r"(?<!\w)/\s*\d{1,4}(?!\w)",
        r"\b\d{1,4}\s+of\s+\d{1,4}\b",
        r"\b(?:out\s+of|numbered\s+to|serial\s+numbered\s+to)\s+\d{1,4}\b",
        r"(?:\$|\busd\s*)\d+(?:\.\d{1,2})?",
        r"\b(?:qty|quantity)\s*:?\s*\d+\b",
        r"\b(?:\d+\s*[x×]|[x×]\s*\d+)\b",
        r"\b\d+\.\d+\b",
    ]
    for pattern in removal_patterns:
        cleaned = re.sub(pattern, " ", cleaned)

    standalone = set(re.findall(r"(?<![a-z0-9])\d{1,3}(?![a-z0-9])", cleaned))
    ambiguous = len(numbers) > 1 or len(standalone) > 1 or (bool(numbers) and bool(standalone))
    if not ambiguous:
        numbers.update(standalone)
    return numbers, ambiguous


def _evaluate_card_identity(title: str, keyword: str) -> tuple[bool, float, str, int, int, bool]:
    title_normalized = _normalize_identity_text(title)
    keyword_normalized = _normalize_identity_text(keyword)
    title_tokens = _identity_tokens(title)
    keyword_tokens = _identity_tokens(keyword)
    overlap_count = len(title_tokens & keyword_tokens)
    specificity = len(keyword_tokens)
    exact_phrase = keyword_normalized in title_normalized

    if specificity < 3:
        return False, 0.0, "insufficient_card_identity", overlap_count, specificity, exact_phrase

    title_years, title_years_ambiguous = _extract_years(title)
    keyword_years, keyword_years_ambiguous = _extract_years(keyword)
    if title_years_ambiguous or keyword_years_ambiguous:
        return False, 0.0, "insufficient_card_identity", overlap_count, specificity, exact_phrase
    if title_years != keyword_years:
        return False, 0.0, "card_identity_conflict_year", overlap_count, specificity, exact_phrase

    title_numbers, title_numbers_ambiguous = _extract_card_numbers(title)
    keyword_numbers, keyword_numbers_ambiguous = _extract_card_numbers(keyword)
    if title_numbers_ambiguous or keyword_numbers_ambiguous:
        return False, 0.0, "insufficient_card_identity", overlap_count, specificity, exact_phrase
    if title_numbers != keyword_numbers:
        return False, 0.0, "card_identity_conflict_number", overlap_count, specificity, exact_phrase

    title_print_run, _ = detect_print_run(title)
    keyword_print_run, _ = detect_print_run(keyword)
    if title_print_run != keyword_print_run:
        return False, 0.0, "card_identity_conflict_print_run", overlap_count, specificity, exact_phrase

    if (title_tokens & PRODUCT_SET_TERMS) != (keyword_tokens & PRODUCT_SET_TERMS):
        return False, 0.0, "card_identity_conflict_set", overlap_count, specificity, exact_phrase

    if (title_tokens & PARALLEL_TERMS) != (keyword_tokens & PARALLEL_TERMS):
        return False, 0.0, "card_identity_conflict_parallel", overlap_count, specificity, exact_phrase

    if (title_tokens & VARIANT_TERMS) != (keyword_tokens & VARIANT_TERMS):
        return False, 0.0, "card_identity_conflict_variant", overlap_count, specificity, exact_phrase

    if title_tokens - keyword_tokens:
        return False, 0.0, "card_identity_conflict_modifier", overlap_count, specificity, exact_phrase

    if not keyword_tokens.issubset(title_tokens):
        return False, 0.0, "insufficient_card_identity", overlap_count, specificity, exact_phrase

    return True, 1.0, "", overlap_count, specificity, exact_phrase


def _find_card_value_match(
    title: str,
    card_values: pd.DataFrame,
    condition: str = "",
) -> _CardValueMatch:
    if _is_slab_listing(title, condition):
        return _CardValueMatch(None, 0.0, "graded_or_slabbed")
    if contains_term(title, BAD_WORDS):
        return _CardValueMatch(None, 0.0, "bad_listing_language")

    qualified = []
    rejected = []

    for _, row in card_values.iterrows():
        keyword = normalize(row.get("keyword", ""))
        if not keyword:
            continue

        valid, strength, reason, overlap, specificity, exact = _evaluate_card_identity(title, keyword)
        if valid:
            qualified.append((row, strength, specificity, exact))
        else:
            rejected.append((overlap, specificity, reason))

    if qualified:
        qualified.sort(key=lambda candidate: (candidate[3], candidate[2]), reverse=True)
        best_key = (qualified[0][3], qualified[0][2])
        best = [candidate for candidate in qualified if (candidate[3], candidate[2]) == best_key]
        if len(best) != 1:
            return _CardValueMatch(None, 0.0, "ambiguous_card_value_match")
        return _CardValueMatch(best[0][0], best[0][1])

    plausible = [candidate for candidate in rejected if candidate[0] >= min(3, candidate[1])]
    if len(plausible) > 1:
        return _CardValueMatch(None, 0.0, "ambiguous_card_value_match")
    if plausible:
        return _CardValueMatch(None, 0.0, plausible[0][2])
    return _CardValueMatch(None, 0.0, "insufficient_card_identity")


def find_best_card_value(title: str, card_values: pd.DataFrame) -> tuple[Optional[pd.Series], float]:
    """Return the single valuation row whose identity safely matches the title."""
    match = _find_card_value_match(title, card_values)
    return match.row, match.strength


def calc_raw_flip(purchase_total: float, raw_market_value: float, settings: dict) -> tuple[float, float]:
    ebay_fee_pct = safe_float(settings.get("ebay_fee_pct"), 0.1325)
    shipping_allowance = safe_float(settings.get("raw_flip_shipping_allowance"), 6)

    fees = raw_market_value * ebay_fee_pct
    total_modeled_cost = purchase_total + fees + shipping_allowance
    profit = raw_market_value - total_modeled_cost
    roi = (profit / total_modeled_cost) * 100 if total_modeled_cost > 0 else 0
    return round(profit, 2), round(roi, 1)


def _normalized_grade_rates(gem_rate: float, psa9_rate: float) -> tuple[float, float]:
    gem_rate = max(0, min(gem_rate, 1))
    psa9_rate = max(0, min(psa9_rate, 1))

    if gem_rate + psa9_rate > 1:
        total = gem_rate + psa9_rate
        gem_rate = gem_rate / total
        psa9_rate = psa9_rate / total

    return gem_rate, psa9_rate


def calc_psa_flip(
    purchase_total: float,
    raw_market_value: float,
    psa9_value: float,
    psa10_value: float,
    gem_rate: float,
    psa9_rate: float,
    settings: dict,
) -> tuple[float, float, float]:
    ebay_fee_pct = safe_float(settings.get("ebay_fee_pct"), 0.1325)
    psa_grading_fee = safe_float(settings.get("psa_grading_fee"), 25)
    psa_shipping_insurance = safe_float(settings.get("psa_shipping_insurance_allowance"), 12)
    psa_selling_shipping = safe_float(settings.get("psa_selling_shipping_allowance"), 8)

    gem_rate, psa9_rate = _normalized_grade_rates(gem_rate, psa9_rate)

    lower_rate = max(0.0, 1.0 - gem_rate - psa9_rate)

    expected_sale_value = (
        psa10_value * gem_rate
        + psa9_value * psa9_rate
        + raw_market_value * lower_rate
    )

    fees = expected_sale_value * ebay_fee_pct

    total_cost = (
        purchase_total
        + psa_grading_fee
        + psa_shipping_insurance
        + psa_selling_shipping
        + fees
    )

    profit = expected_sale_value - total_cost
    roi = (profit / total_cost) * 100 if total_cost > 0 else 0

    return round(expected_sale_value, 2), round(profit, 2), round(roi, 1)


def _max_purchase_total(
    sale_value: float,
    fixed_modeled_costs: float,
    minimum_profit: float,
    minimum_roi_pct: float,
) -> float:
    roi_rate = max(minimum_roi_pct, 0) / 100
    profit_limited = sale_value - fixed_modeled_costs - minimum_profit
    roi_limited = (sale_value / (1 + roi_rate)) - fixed_modeled_costs
    return max(min(profit_limited, roi_limited), 0)


def calc_max_buy_prices(row: pd.Series, settings: dict) -> tuple[float, float]:
    """Return maximum total acquisition costs that satisfy profit and ROI thresholds."""
    raw_market_value = safe_float(row.get("raw_market_value"))
    psa9_value = safe_float(row.get("psa9_value"))
    psa10_value = safe_float(row.get("psa10_value"))
    gem_rate = safe_float(row.get("gem_rate_estimate"))
    psa9_rate = safe_float(row.get("psa9_rate_estimate"))

    ebay_fee_pct = safe_float(settings.get("ebay_fee_pct"), 0.1325)

    min_raw_profit = safe_float(settings.get("minimum_raw_flip_profit"), 25)
    min_raw_roi = safe_float(settings.get("minimum_raw_flip_roi_pct"), 20)
    raw_shipping = safe_float(settings.get("raw_flip_shipping_allowance"), 6)

    min_psa_profit = safe_float(settings.get("minimum_psa_expected_profit"), 50)
    min_psa_roi = safe_float(settings.get("minimum_psa_expected_roi_pct"), 25)
    psa_grading_fee = safe_float(settings.get("psa_grading_fee"), 25)
    psa_shipping = safe_float(settings.get("psa_shipping_insurance_allowance"), 12)
    psa_sell_ship = safe_float(settings.get("psa_selling_shipping_allowance"), 8)

    raw_fixed_costs = (raw_market_value * ebay_fee_pct) + raw_shipping
    raw_max_buy = _max_purchase_total(
        raw_market_value,
        raw_fixed_costs,
        min_raw_profit,
        min_raw_roi,
    )

    gem_rate, psa9_rate = _normalized_grade_rates(gem_rate, psa9_rate)
    lower_rate = max(0.0, 1.0 - gem_rate - psa9_rate)
    psa_expected_sale_value = (
        psa10_value * gem_rate
        + psa9_value * psa9_rate
        + raw_market_value * lower_rate
    )

    psa_fixed_costs = (
        (psa_expected_sale_value * ebay_fee_pct)
        + psa_grading_fee
        + psa_shipping
        + psa_sell_ship
    )
    psa_max_buy = _max_purchase_total(
        psa_expected_sale_value,
        psa_fixed_costs,
        min_psa_profit,
        min_psa_roi,
    )

    return max(raw_max_buy, 0), max(psa_max_buy, 0)


def analyze_listing(listing: pd.Series, card_values: pd.DataFrame, settings: dict) -> ProfitResult:
    title = normalize(listing.get("title", ""))
    raw_price = listing.get("price")
    raw_shipping = listing.get("shipping")
    parsed_price = _finite_float(raw_price)
    parsed_shipping = _finite_float(raw_shipping)
    price = parsed_price if parsed_price is not None else 0.0
    shipping = parsed_shipping if parsed_shipping is not None else 0.0
    total_price = round(price + shipping, 2)
    raw_currency = listing.get("currency")
    currency = "" if _is_missing(raw_currency) else normalize(raw_currency).upper()
    item_url = normalize(listing.get("item_url", ""))
    image_url = normalize(listing.get("image_url", ""))
    seller_username = normalize(listing.get("seller_username", ""))
    seller_feedback = safe_int(listing.get("seller_feedback"))
    seller_feedback_pct = safe_float(listing.get("seller_feedback_pct"), default=None)
    raw_buying_options = listing.get("buying_options")
    buying_options = (
        "" if _is_missing(raw_buying_options) else normalize(raw_buying_options)
    )
    buying_option_values = (
        set() if _is_missing(raw_buying_options) else _buying_option_set(buying_options)
    )
    offer_compatible = "BEST_OFFER" in buying_option_values
    raw_condition = listing.get("condition")
    condition = "" if _is_missing(raw_condition) else normalize(raw_condition)
    item_end_date = normalize(listing.get("item_end_date", ""))

    print_run, serial_detected = detect_print_run(title)

    is_slab = _is_slab_listing(title, condition)
    is_bad = contains_term(title, BAD_WORDS)
    has_good_words = contains_term(title, GOOD_WORDS)
    raw_candidate = not is_slab

    eligibility_flags = []
    if _is_missing(raw_price):
        eligibility_flags.append("missing_price")
    elif parsed_price is None or parsed_price <= 0:
        eligibility_flags.append("invalid_price")

    if _is_missing(raw_shipping):
        eligibility_flags.append("missing_shipping")
    elif parsed_shipping is None or parsed_shipping < 0:
        eligibility_flags.append("invalid_shipping")

    if _is_missing(raw_currency):
        eligibility_flags.append("missing_currency")
    elif currency != "USD":
        eligibility_flags.append("unsupported_currency")

    if _is_missing(raw_buying_options):
        eligibility_flags.append("missing_buying_option")
    elif not buying_option_values.issubset(SUPPORTED_BUYING_OPTIONS):
        eligibility_flags.append("unsupported_buying_option")

    if _is_missing(raw_condition):
        eligibility_flags.append("missing_condition")

    eligibility_flags.extend(_modeled_cost_flags(settings))
    listing_eligible = not eligibility_flags and not is_slab

    flags = list(eligibility_flags)
    score = 0

    if is_bad:
        flags.append("bad_listing_language")
        score -= 80

    if is_slab:
        flags.append("graded_or_slabbed")
        score -= 40

    if settings.get("raw_only", True) and is_slab:
        score -= 100

    if has_good_words:
        score += 15

    if raw_candidate:
        score += 15

    if print_run is not None:
        if print_run == 1:
            score += 90
        elif print_run <= 5:
            score += 70
        elif print_run <= 10:
            score += 55
        elif print_run <= 25:
            score += 40
        elif print_run <= 50:
            score += 30
        elif print_run <= 99:
            score += 20
        else:
            score += 8
    else:
        flags.append("no_print_run_detected")

    if len(title.split()) <= 8:
        flags.append("thin_title_opportunity")
        score += 8

    card_match = _find_card_value_match(title, card_values, condition)
    card = card_match.row
    match_strength = card_match.strength

    raw_flip_profit = None
    raw_flip_roi_pct = None
    psa_expected_profit = None
    psa_expected_roi_pct = None
    psa_expected_sale_value = None
    max_buy_price_raw_flip = None
    max_buy_price_psa_flip = None
    suggested_offer = None
    offer_candidate = None
    raw_max_total = None
    psa_max_total = None
    raw_meets_thresholds = False
    psa_meets_thresholds = False

    matched_card = ""
    raw_market_value = None
    psa9_value = None
    psa10_value = None
    gem_rate = None
    psa9_rate = None

    best_path = "NONE"
    best_expected_profit = None
    best_expected_roi_pct = None
    valuation_is_non_actionable = False

    if card is not None and listing_eligible:
        matched_card = normalize(card.get("keyword"))
        valuation_notes = normalize(card.get("notes", ""))
        valuation_is_non_actionable = _valuation_is_non_actionable(valuation_notes)

        if valuation_is_non_actionable:
            flags.append("non_actionable_valuation")
            if re.search(r"\bexample(?:\s+only)?\b", valuation_notes.lower()):
                flags.append("unverified_example_valuation")
            score -= 60
        else:
            raw_market_value = safe_float(card.get("raw_market_value"))
            psa9_value = safe_float(card.get("psa9_value"))
            psa10_value = safe_float(card.get("psa10_value"))
            gem_rate = safe_float(card.get("gem_rate_estimate"))
            psa9_rate = safe_float(card.get("psa9_rate_estimate"))

            raw_flip_profit, raw_flip_roi_pct = calc_raw_flip(
                total_price,
                raw_market_value,
                settings,
            )

            psa_expected_sale_value, psa_expected_profit, psa_expected_roi_pct = calc_psa_flip(
                total_price,
                raw_market_value,
                psa9_value,
                psa10_value,
                gem_rate,
                psa9_rate,
                settings,
            )

            raw_max_total, psa_max_total = calc_max_buy_prices(card, settings)
            raw_meets_thresholds = total_price <= raw_max_total
            psa_meets_thresholds = total_price <= psa_max_total
            max_buy_price_raw_flip = _floor_currency(raw_max_total - shipping)
            max_buy_price_psa_flip = _floor_currency(psa_max_total - shipping)
            offer_margin = _finite_float(settings.get("offer_safety_margin_pct"))
            offer_margin = 0.85 if offer_margin is None else max(0, min(offer_margin, 1))
            candidate_offer_total = max(raw_max_total, psa_max_total) * offer_margin
            candidate_offer = max(candidate_offer_total - shipping, 0)
            # A sourcing offer should not exceed the verified raw market value.
            # This guard also prevents PSA assumptions from creating absurd offers.
            market_cap_pct = _finite_float(settings.get("max_offer_market_pct"))
            market_cap_pct = 0.90 if market_cap_pct is None else max(0, min(market_cap_pct, 1))
            market_cap = raw_market_value * market_cap_pct
            offer_candidate = _floor_currency(min(candidate_offer, market_cap))
            if offer_candidate <= 0:
                offer_candidate = None
            if offer_compatible:
                suggested_offer = offer_candidate

            if raw_meets_thresholds:
                score += 70
                flags.append("raw_flip_profitable")
            elif raw_flip_profit > 0:
                score += 25
                flags.append("raw_flip_small_profit")
            else:
                score -= 20
                flags.append("raw_flip_negative")

            if psa_meets_thresholds:
                score += 85
                flags.append("psa_flip_profitable")
            elif psa_expected_profit > 0:
                score += 25
                flags.append("psa_flip_small_profit")
            else:
                score -= 20
                flags.append("psa_flip_negative")

            if raw_flip_profit >= psa_expected_profit:
                best_path = "RAW_FLIP"
                best_expected_profit = raw_flip_profit
                best_expected_roi_pct = raw_flip_roi_pct
            else:
                best_path = "PSA_FLIP"
                best_expected_profit = psa_expected_profit
                best_expected_roi_pct = psa_expected_roi_pct

        flags.append(f"match_strength_{match_strength:.2f}")
    elif card is None:
        if card_match.reason and card_match.reason not in flags:
            flags.append(card_match.reason)
        flags.append("no_card_value_match")

    valuation_reliable = (
        card is not None
        and listing_eligible
        and not valuation_is_non_actionable
    )

    raw_buy = (
        valuation_reliable
        and raw_meets_thresholds
    )

    psa_buy = (
        valuation_reliable
        and psa_meets_thresholds
    )

    if not listing_eligible or is_bad or is_slab or card is None:
        action = "PASS"
    elif card is not None and not valuation_reliable:
        action = "PASS"
    elif raw_buy and (not psa_buy or (raw_flip_profit or 0) >= (psa_expected_profit or 0) * 0.75):
        action = "BUY_RAW_FLIP"
    elif psa_buy:
        action = "BUY_GRADE_PSA"
    elif valuation_reliable and offer_candidate and price > offer_candidate:
        if offer_compatible and suggested_offer:
            action = "OFFER"
        else:
            flags.append("offer_not_supported")
            action = "PASS"
    elif score >= 70:
        action = "WATCH"
    else:
        action = "PASS"

    if action not in ACTIONABLE_ACTIONS:
        best_path = "NONE"
        best_expected_profit = None
        best_expected_roi_pct = None
        raw_flip_profit = None
        raw_flip_roi_pct = None
        psa_expected_profit = None
        psa_expected_roi_pct = None
        psa_expected_sale_value = None
        max_buy_price_raw_flip = None
        max_buy_price_psa_flip = None
        suggested_offer = None
        raw_market_value = None
        psa9_value = None
        psa10_value = None
        gem_rate = None
        psa9_rate = None

    return ProfitResult(
        recommended_action=action,
        total_score=int(score),
        best_path=best_path,
        best_expected_profit=(
            round(best_expected_profit, 2)
            if best_expected_profit is not None
            else None
        ),
        best_expected_roi_pct=(
            round(best_expected_roi_pct, 1)
            if best_expected_roi_pct is not None
            else None
        ),

        raw_flip_profit=raw_flip_profit,
        raw_flip_roi_pct=raw_flip_roi_pct,

        psa_expected_profit=psa_expected_profit,
        psa_expected_roi_pct=psa_expected_roi_pct,
        psa_expected_sale_value=psa_expected_sale_value,

        max_buy_price_raw_flip=max_buy_price_raw_flip,
        max_buy_price_psa_flip=max_buy_price_psa_flip,
        suggested_offer=suggested_offer,

        title=title,
        total_price=total_price,
        price=price,
        shipping=shipping,
        currency=currency,
        item_url=item_url,
        image_url=image_url,

        matched_card=matched_card,
        match_strength=round(match_strength, 2),
        raw_market_value=raw_market_value,
        psa9_value=psa9_value,
        psa10_value=psa10_value,
        gem_rate_estimate=gem_rate,
        psa9_rate_estimate=psa9_rate,

        print_run=print_run,
        serial_detected=serial_detected,
        raw_candidate=raw_candidate,
        flags=";".join(flags),

        seller_username=seller_username,
        seller_feedback=seller_feedback,
        seller_feedback_pct=seller_feedback_pct,
        buying_options=buying_options,
        condition=condition,
        item_end_date=item_end_date,
    )


def analyze_listings(listings: pd.DataFrame, card_values: pd.DataFrame, settings: dict) -> pd.DataFrame:
    if listings.empty:
        return pd.DataFrame()

    results = [asdict(analyze_listing(row, card_values, settings)) for _, row in listings.iterrows()]
    df = pd.DataFrame(results)

    if df.empty:
        return df

    action_order = {
        "BUY_RAW_FLIP": 0,
        "BUY_GRADE_PSA": 1,
        "OFFER": 2,
        "WATCH": 3,
        "PASS": 4,
    }

    df["_action_order"] = df["recommended_action"].map(action_order).fillna(99)
    df = df.sort_values(
        by=["_action_order", "total_score", "best_expected_profit", "best_expected_roi_pct"],
        ascending=[True, False, False, False]
    ).drop(columns=["_action_order"])

    return df
