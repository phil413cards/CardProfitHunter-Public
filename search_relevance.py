from __future__ import annotations

import re
import unicodedata
from typing import Any

from listing_classifier import (
    CONDITION_AMBIGUOUS,
    MULTI_CARD_LISTING,
    NON_CARD_MERCHANDISE,
    classify_listing,
)


EXCLUDED_PHRASES = (
    "pick your card",
    "pick a card",
    "choose your card",
    "choose one",
    "you pick",
    "team lot",
    "player lot",
    "box break",
    "case break",
    "group break",
    "mystery pack",
    "mystery box",
    "digital card",
    "custom card",
    "reprint",
)

IGNORED_QUERY_TOKENS = {
    "a",
    "an",
    "and",
    "card",
    "cards",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "with",
}

NAME_SUFFIXES = {
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = text.lower()
    text = re.sub(r"[^a-z0-9#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def meaningful_query_tokens(query: str) -> list[str]:
    tokens = normalize_text(query).split()
    return [
        token
        for token in tokens
        if token not in IGNORED_QUERY_TOKENS
        and token not in NAME_SUFFIXES
    ]


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    return bool(
        re.search(
            rf"(?:^|\s){re.escape(normalized_phrase)}(?:\s|$)",
            text,
        )
    )


def excluded_listing_reason(
    title: str,
    query: str = "",
) -> str | None:
    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)

    classification = classify_listing(title)
    if classification.listing_class in {
        NON_CARD_MERCHANDISE,
        MULTI_CARD_LISTING,
        CONDITION_AMBIGUOUS,
    }:
        return (
            classification.exclusion_reason
            or classification.listing_class.lower()
        )

    for phrase in EXCLUDED_PHRASES:
        if (
            _contains_phrase(normalized_title, phrase)
            and not _contains_phrase(normalized_query, phrase)
        ):
            return phrase

    return None


def _looks_like_person_name(tokens: list[str]) -> bool:
    return (
        2 <= len(tokens) <= 3
        and all(token.isalpha() for token in tokens)
    )


def score_search_result(title: str, query: str) -> float:
    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)
    query_tokens = meaningful_query_tokens(query)

    if not normalized_title or not normalized_query or not query_tokens:
        return 0.0

    if excluded_listing_reason(title, query):
        return 0.0

    title_tokens = set(normalized_title.split())
    matched_tokens = [
        token for token in query_tokens if token in title_tokens
    ]
    match_ratio = len(matched_tokens) / len(query_tokens)

    score = match_ratio * 70.0

    if normalized_query in normalized_title:
        score += 20.0

    if len(matched_tokens) == len(query_tokens):
        score += 10.0

    return min(round(score, 2), 100.0)


def is_relevant_search_result(
    title: str,
    query: str,
    minimum_score: float = 60.0,
) -> bool:
    query_tokens = meaningful_query_tokens(query)

    if not query_tokens:
        return False

    if excluded_listing_reason(title, query):
        return False

    normalized_title_tokens = set(normalize_text(title).split())

    if _looks_like_person_name(query_tokens):
        return all(
            token in normalized_title_tokens
            for token in query_tokens
        )

    return score_search_result(title, query) >= float(minimum_score)


def filter_search_results(
    items: list[dict[str, Any]],
    query: str,
    minimum_score: float = 60.0,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    relevant: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not isinstance(title, str):
            continue

        if is_relevant_search_result(
            title,
            query,
            minimum_score,
        ):
            relevant.append(item)

    return relevant
