from __future__ import annotations

from typing import Any

import pandas as pd

from listing_classifier import ACTIONABLE_CLASSES, classify_listing
from text_safety import required_text_issue, safe_text


ACTION_PRIORITY = {
    "BUY_GRADE_PSA": 4,
    "BUY_RAW_FLIP": 3,
    "OFFER": 2,
    "WATCH": 1,
    "PASS": 0,
}

VERIFIED_ACTIONS = {"BUY_GRADE_PSA", "BUY_RAW_FLIP", "OFFER"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def calculate_scout_score(row: pd.Series) -> int:
    """
    Score both financially verified recommendations and unverified Scout candidates.

    Verified recommendations receive profit, ROI, and market-confidence weight.
    Unverified candidates receive title-based grading, rarity, card-desirability,
    seller-quality, and listing-quality weight. They are never presented as a
    financially verified BUY.
    """
    action = ACTION_PRIORITY.get(str(row.get("recommended_action", "")), 0)
    valuation_available = _truthy(row.get("valuation_available"))

    profit_score = (
        min(max(_num(row.get("best_expected_profit")), 0.0), 250.0)
        / 250.0
        * 25
        if valuation_available
        else 0.0
    )
    roi_score = (
        min(max(_num(row.get("best_expected_roi_pct")), 0.0), 100.0)
        / 100.0
        * 20
        if valuation_available
        else 0.0
    )
    grading_score = (
        min(max(_num(row.get("grading_signal_score")), 0.0), 100.0)
        / 100.0
        * 30
    )
    engine_score = (
        min(max(_num(row.get("total_score")), 0.0), 250.0)
        / 250.0
        * 10
        if valuation_available
        else 0.0
    )

    rarity_score = 0.0
    print_run = _num(row.get("parsed_print_run"), 0.0)
    if print_run:
        rarity_score = (
            20
            if print_run <= 10
            else 16
            if print_run <= 25
            else 12
            if print_run <= 99
            else 6
        )

    desirability_score = 0.0
    if _truthy(row.get("parsed_rookie")):
        desirability_score += 8
    if _truthy(row.get("parsed_autograph")):
        desirability_score += 7
    if str(row.get("parsed_parallel", "")).strip():
        desirability_score += 7
    if str(row.get("parsed_card_number", "")).strip():
        desirability_score += 3

    feedback_pct = _num(row.get("seller_feedback_pct"), 0.0)
    seller_score = (
        8
        if feedback_pct >= 99.8
        else 6
        if feedback_pct >= 99.0
        else 3
        if feedback_pct >= 97.0
        else 0
    )

    market_score = (
        7
        if row.get("market_confidence") == "HIGH"
        else 3
        if row.get("market_confidence") == "MEDIUM"
        else 0
    )

    action_score = action * 1.25 if valuation_available else 0.0
    score = (
        action_score
        + profit_score
        + roi_score
        + grading_score
        + engine_score
        + rarity_score
        + desirability_score
        + seller_score
        + market_score
    )
    return int(round(max(0.0, min(score, 100.0))))


def is_unverified_scout_candidate(
    row: pd.Series,
    minimum_scout_score: int = 40,
) -> bool:
    """
    Identify promising raw single-card listings that lack verified valuation data.

    These rows are discovery candidates only. They require sold-comparable research,
    photo inspection, and seller/return-policy review before purchase.
    """
    if str(row.get("recommended_action", "")) in VERIFIED_ACTIONS:
        return False
    if _truthy(row.get("valuation_available")):
        return False
    if not _truthy(row.get("listing_actionable")):
        return False
    if not _truthy(row.get("grading_candidate")):
        return False
    raw_title = row.get("title", "")
    raw_condition = row.get("condition", "")
    if required_text_issue(raw_title, "title"):
        return False
    if required_text_issue(raw_condition, "condition"):
        return False
    title = safe_text(raw_title)
    condition = safe_text(raw_condition)
    current_classification = classify_listing(title, condition)
    if not current_classification.actionable:
        return False
    if current_classification.listing_class not in ACTIONABLE_CLASSES:
        return False
    if str(row.get("listing_listing_class", "")) not in ACTIONABLE_CLASSES:
        return False
    return calculate_scout_score(row) >= int(minimum_scout_score)


def recommendation_label(row: pd.Series) -> str:
    action = str(row.get("recommended_action", ""))
    score = _num(row.get("scout_score"))

    if action == "BUY_GRADE_PSA" and score >= 75:
        return "ELITE BUY TO GRADE"
    if action == "BUY_GRADE_PSA":
        return "BUY TO GRADE"
    if action == "BUY_RAW_FLIP":
        return "BUY TO RESELL RAW"
    if action == "OFFER":
        return "MAKE OFFER"
    if _truthy(row.get("scout_candidate")):
        if score >= 70:
            return "HIGH-INTEREST SCOUT CANDIDATE"
        return "POTENTIAL GRADING CANDIDATE"
    if action == "WATCH":
        return "WATCH"
    return "PASS"


def _recommendation_basis(row: pd.Series) -> str:
    if _truthy(row.get("financially_verified")):
        return "Verified valuation and modeled profit thresholds"
    return (
        "Discovery only: title/condition signals, rarity, card traits, and seller data; "
        "verify sold comps and inspect photos before buying"
    )


def rank_recommendations(
    frame: pd.DataFrame,
    limit: int,
    include_offers: bool = True,
    include_scout_candidates: bool = True,
    minimum_scout_score: int = 40,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy()

    ranked = frame.copy()
    ranked["scout_score"] = ranked.apply(calculate_scout_score, axis=1)
    ranked["financially_verified"] = ranked["recommended_action"].isin(
        VERIFIED_ACTIONS
    )
    ranked["scout_candidate"] = ranked.apply(
        lambda row: is_unverified_scout_candidate(
            row,
            minimum_scout_score=minimum_scout_score,
        ),
        axis=1,
    )

    allowed = {"BUY_GRADE_PSA", "BUY_RAW_FLIP"}
    if include_offers:
        allowed.add("OFFER")

    keep = ranked["recommended_action"].isin(allowed)
    if include_scout_candidates:
        keep = keep | ranked["scout_candidate"]

    ranked = ranked[keep].copy()
    if ranked.empty:
        return ranked

    ranked["scout_recommendation"] = ranked.apply(
        recommendation_label,
        axis=1,
    )
    ranked["recommendation_basis"] = ranked.apply(
        _recommendation_basis,
        axis=1,
    )
    ranked["requires_comp_verification"] = ~ranked["financially_verified"]

    for column in (
        "best_expected_profit",
        "best_expected_roi_pct",
        "total_score",
        "scout_score",
    ):
        if column in ranked.columns:
            ranked[column] = pd.to_numeric(ranked[column], errors="coerce")

    ranked["_verified_order"] = ranked["financially_verified"].astype(int)
    ranked = ranked.sort_values(
        [
            "_verified_order",
            "scout_score",
            "best_expected_profit",
            "best_expected_roi_pct",
            "grading_signal_score",
            "total_score",
        ],
        ascending=[False, False, False, False, False, False],
        na_position="last",
    ).drop(columns=["_verified_order"])

    return ranked.head(max(int(limit), 1)).reset_index(drop=True)
