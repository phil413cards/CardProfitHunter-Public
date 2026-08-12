import unittest

import pandas as pd

from recommendation_engine import (
    calculate_scout_score,
    is_unverified_scout_candidate,
    rank_recommendations,
)


def candidate_row(**overrides):
    row = {
        "recommended_action": "PASS",
        "valuation_available": False,
        "listing_actionable": True,
        "listing_listing_class": "RAW_PARALLEL",
        "grading_candidate": True,
        "grading_signal_score": 65,
        "parsed_print_run": 99,
        "parsed_rookie": False,
        "parsed_autograph": False,
        "parsed_parallel": "Refractor",
        "parsed_card_number": "",
        "seller_feedback_pct": 99.9,
        "best_expected_profit": None,
        "best_expected_roi_pct": None,
        "total_score": 20,
        "title": "Shohei Ohtani Refractor /99",
        "condition": "Ungraded",
    }
    row.update(overrides)
    return pd.Series(row)


class HybridRecommendationTests(unittest.TestCase):
    def test_unverified_candidate_can_be_returned_without_becoming_buy(self):
        row = candidate_row()
        self.assertTrue(is_unverified_scout_candidate(row, 40))
        self.assertEqual(row["recommended_action"], "PASS")

    def test_candidate_is_rejected_when_listing_is_not_actionable(self):
        row = candidate_row(listing_actionable=False)
        self.assertFalse(is_unverified_scout_candidate(row, 40))

    def test_verified_buy_ranks_before_unverified_candidate(self):
        frame = pd.DataFrame([
            candidate_row().to_dict(),
            candidate_row(
                recommended_action="BUY_GRADE_PSA",
                valuation_available=True,
                best_expected_profit=60,
                best_expected_roi_pct=35,
                total_score=150,
                grading_signal_score=55,
                title="Verified card",
            ).to_dict(),
        ])
        ranked = rank_recommendations(
            frame,
            10,
            include_scout_candidates=True,
        )
        self.assertEqual(ranked.iloc[0]["recommended_action"], "BUY_GRADE_PSA")
        self.assertTrue(bool(ranked.iloc[0]["financially_verified"]))
        self.assertTrue(bool(ranked.iloc[1]["scout_candidate"]))
        self.assertFalse(bool(ranked.iloc[1]["financially_verified"]))

    def test_scout_score_uses_nonfinancial_signals(self):
        self.assertGreaterEqual(calculate_scout_score(candidate_row()), 40)


if __name__ == "__main__":
    unittest.main()
