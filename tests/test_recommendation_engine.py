import pandas as pd
from recommendation_engine import rank_recommendations


def test_ranks_best_actionable_results():
    frame = pd.DataFrame([
        {"recommended_action": "PASS", "total_score": 100},
        {"recommended_action": "BUY_GRADE_PSA", "total_score": 120, "best_expected_profit": 80, "best_expected_roi_pct": 50, "grading_signal_score": 80, "parsed_print_run": 50, "market_confidence": "HIGH"},
        {"recommended_action": "BUY_RAW_FLIP", "total_score": 110, "best_expected_profit": 40, "best_expected_roi_pct": 35, "grading_signal_score": 30, "parsed_print_run": None, "market_confidence": "HIGH"},
    ])
    ranked = rank_recommendations(frame, 1)
    assert len(ranked) == 1
    assert ranked.iloc[0]["recommended_action"] == "BUY_GRADE_PSA"
