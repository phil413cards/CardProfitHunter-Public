from __future__ import annotations

import unittest

import pandas as pd

from listing_classifier import (
    NON_CARD_MERCHANDISE,
    RAW_AUTOGRAPH,
    RAW_PARALLEL,
    RAW_SINGLE_CARD,
    classify_listing,
    has_trading_card_evidence,
)
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


NON_CARD_SCOUT_TITLES = (
    "Shohei Ohtani Signed Baseball Auto 1/25 Rookie Mint",
    "Shohei Ohtani Gold Coin 12/50 Rookie",
    "Shohei Ohtani Signed 8x10 Photo Auto 12/25 Rookie",
    "Shohei Ohtani Autographed Mini Helmet 4/10 Rookie",
    "Shohei Ohtani Rookie Book Japanese Edition",
)


class ScoutCardEvidenceTests(unittest.TestCase):
    def test_non_card_collectibles_are_explicitly_classified(self):
        for title in NON_CARD_SCOUT_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertFalse(has_trading_card_evidence(title))
                self.assertEqual(
                    classification.listing_class,
                    NON_CARD_MERCHANDISE,
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertEqual(
                    classification.exclusion_reason,
                    "non_card_merchandise",
                )

    def test_non_card_collectibles_are_removed_before_scout_analysis(self):
        for title in NON_CARD_SCOUT_TITLES:
            with self.subTest(title=title):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "non_card_merchandise",
                )
                self.assertFalse(
                    is_relevant_search_result(title, "Shohei Ohtani")
                )

                results = run_scout_engine(
                    pd.DataFrame([{"title": title, "condition": "Ungraded"}]),
                    pd.DataFrame(),
                    {},
                    "Shohei Ohtani",
                    recommendation_limit=10,
                )
                self.assertTrue(results.empty)

    def test_scout_candidate_check_does_not_trust_spoofed_actionable_flags(self):
        row = pd.Series({
            "title": NON_CARD_SCOUT_TITLES[0],
            "recommended_action": "PASS",
            "valuation_available": False,
            "listing_actionable": True,
            "listing_listing_class": RAW_AUTOGRAPH,
            "grading_candidate": True,
            "grading_signal_score": 100,
            "parsed_print_run": 25,
            "parsed_rookie": True,
            "parsed_autograph": True,
            "parsed_parallel": "Gold",
            "parsed_card_number": "1",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_valid_card_evidence_remains_eligible(self):
        cases = (
            (
                "2024 Topps Chrome Shohei Ohtani #1 Refractor",
                RAW_PARALLEL,
            ),
            (
                "2023 National Treasures Shohei Ohtani Game Used Jersey Patch /25",
                RAW_SINGLE_CARD,
            ),
            ("Shohei Ohtani On Card Auto", RAW_AUTOGRAPH),
            ("Shohei Ohtani + Aaron Judge Dual Auto /10", RAW_AUTOGRAPH),
        )

        for title, expected_class in cases:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertTrue(has_trading_card_evidence(title))
                self.assertEqual(classification.listing_class, expected_class)
                self.assertTrue(classification.actionable)
                self.assertTrue(
                    is_relevant_search_result(title, "Shohei Ohtani")
                )


if __name__ == "__main__":
    unittest.main()
