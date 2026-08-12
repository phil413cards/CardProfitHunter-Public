from __future__ import annotations

from dataclasses import replace

import pandas as pd

from card_parser import parse_card_identity
from grading_estimator import estimate_grading_candidate
from listing_classifier import UNKNOWN, classify_listing
from market_intelligence import build_market_context
from profit_engine import analyze_listings
from recommendation_engine import rank_recommendations
from text_safety import required_text_issue, safe_text


def enrich_listings(listings: pd.DataFrame, query: str) -> pd.DataFrame:
    if listings is None or listings.empty:
        return pd.DataFrame() if listings is None else listings.copy()

    rows = []
    for _, row in listings.iterrows():
        enriched = row.to_dict()
        raw_title = row.get("title", "")
        raw_condition = row.get("condition", "")
        title = safe_text(raw_title)
        condition = safe_text(raw_condition)
        text_issue = required_text_issue(raw_title, "title")
        if not text_issue:
            text_issue = required_text_issue(raw_condition, "condition")
        classification = classify_listing(title, condition)
        if text_issue:
            classification = replace(
                classification,
                listing_class=UNKNOWN,
                actionable=False,
                raw=False,
                single_card=False,
                exclusion_reason=text_issue,
            )
        identity = parse_card_identity(title, query)
        grading = estimate_grading_candidate(
            title,
            condition,
            classification,
            identity,
        )

        enriched.update(
            {
                f"listing_{key}": value
                for key, value in classification.to_dict().items()
            }
        )
        enriched.update(
            {
                f"parsed_{key}": value
                for key, value in identity.to_dict().items()
            }
        )
        enriched.update(grading.to_dict())
        rows.append(enriched)

    return pd.DataFrame(rows)


def _merge_metadata(
    analyzed: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    metadata_columns = [
        "item_url",
        "listing_listing_class",
        "listing_actionable",
        "listing_exclusion_reason",
        "parsed_player",
        "parsed_year",
        "parsed_manufacturer",
        "parsed_product",
        "parsed_card_number",
        "parsed_parallel",
        "parsed_serial_number",
        "parsed_print_run",
        "parsed_autograph",
        "parsed_rookie",
        "grading_candidate",
        "grading_signal_score",
        "confidence",
        "reasons",
        "warning",
    ]
    metadata = eligible[
        [column for column in metadata_columns if column in eligible.columns]
    ].copy()

    if "item_url" in analyzed.columns and "item_url" in metadata.columns:
        metadata = metadata.drop_duplicates(subset=["item_url"], keep="first")
        return analyzed.merge(metadata, on="item_url", how="left")

    for column in metadata.columns:
        if column != "item_url" and len(metadata) == len(analyzed):
            analyzed[column] = metadata[column].to_numpy()
    return analyzed


def run_scout_engine(
    listings: pd.DataFrame,
    card_values: pd.DataFrame,
    settings: dict,
    query: str,
    recommendation_limit: int,
    include_offers: bool = True,
    include_scout_candidates: bool = True,
    minimum_scout_score: int = 40,
) -> pd.DataFrame:
    """
    Run the hybrid recommendation pipeline.

    Financial recommendations require an exact, actionable valuation match.
    Scout candidates may be returned without a valuation, but are explicitly
    marked as unverified discovery candidates rather than BUY recommendations.
    """
    enriched = enrich_listings(listings, query)
    if enriched.empty:
        return pd.DataFrame()

    eligible = enriched[
        enriched["listing_actionable"] == True  # noqa: E712
    ].copy()
    if eligible.empty:
        return pd.DataFrame()

    analyzed = analyze_listings(eligible, card_values, settings)
    if analyzed.empty:
        return analyzed

    analyzed = _merge_metadata(analyzed, eligible)

    contexts = analyzed.apply(build_market_context, axis=1)
    context_frame = pd.DataFrame(
        [context.to_dict() for context in contexts],
        index=analyzed.index,
    )
    analyzed = pd.concat([analyzed, context_frame], axis=1)
    analyzed = analyzed.loc[
        :, ~analyzed.columns.duplicated(keep="last")
    ].copy()

    return rank_recommendations(
        analyzed,
        recommendation_limit,
        include_offers=include_offers,
        include_scout_candidates=include_scout_candidates,
        minimum_scout_score=minimum_scout_score,
    )
