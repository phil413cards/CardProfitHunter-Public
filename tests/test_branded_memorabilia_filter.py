from __future__ import annotations

import unittest

import pandas as pd

from listing_classifier import (
    NON_CARD_MERCHANDISE,
    RAW_AUTOGRAPH,
    RAW_PARALLEL,
    RAW_SINGLE_CARD,
    classify_listing,
)
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


BRANDED_MEMORABILIA_TITLES = (
    "Topps Authentics Shohei Ohtani Signed Baseball Auto 1/25",
    "Panini Shohei Ohtani Signed 8x10 Photo Auto /25",
    "Topps Shohei Ohtani Autographed Mini Helmet /10",
    "Panini Shohei Ohtani Gold Coin /50 Rookie",
    "Topps Shohei Ohtani Rookie Book Japanese Edition",
    "Panini Shohei Ohtani Autographed Jersey /25",
    "Topps Shohei Ohtani Signed Bat /10",
    "Panini Shohei Ohtani Autographed Basketball /25",
    "Upper Deck Shohei Ohtani Signed Hockey Puck /10",
)


class BrandedMemorabiliaFilterTests(unittest.TestCase):
    def test_card_brands_do_not_override_strong_non_card_objects(self):
        for title in BRANDED_MEMORABILIA_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(
                    classification.listing_class,
                    NON_CARD_MERCHANDISE,
                )
                self.assertEqual(
                    classification.exclusion_reason,
                    "non_card_merchandise",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_branded_memorabilia_is_removed_before_analysis(self):
        for title in BRANDED_MEMORABILIA_TITLES:
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
                    minimum_scout_score=25,
                )
                self.assertTrue(results.empty)

    def test_scout_boundary_rejects_spoofed_memorabilia_metadata(self):
        for title in BRANDED_MEMORABILIA_TITLES:
            with self.subTest(title=title):
                row = pd.Series({
                    "title": title,
                    "condition": "Ungraded",
                    "recommended_action": "PASS",
                    "valuation_available": False,
                    "listing_actionable": True,
                    "grading_candidate": True,
                    "listing_listing_class": RAW_AUTOGRAPH,
                    "grading_signal_score": 100,
                    "parsed_print_run": 25,
                    "parsed_rookie": True,
                    "parsed_autograph": True,
                    "parsed_parallel": "Gold",
                    "parsed_card_number": "1",
                    "seller_feedback_pct": 100,
                })

                self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_legitimate_card_object_terms_remain_actionable(self):
        cases = (
            (
                "2024 Topps Shohei Ohtani Signed Baseball Card #1",
                RAW_AUTOGRAPH,
            ),
            (
                "2024 Panini Shohei Ohtani Jersey Patch Auto Card /25",
                RAW_AUTOGRAPH,
            ),
            (
                "2024 Topps Shohei Ohtani Gold Coin Card Insert #1",
                RAW_PARALLEL,
            ),
            (
                "2024 Topps Shohei Ohtani Photo Variation Card #1",
                RAW_SINGLE_CARD,
            ),
            (
                "2024 National Treasures Shohei Ohtani Game Used Baseball Relic Card /10",
                RAW_SINGLE_CARD,
            ),
            (
                "2024 Topps Shohei Ohtani Bat Relic Card #1",
                RAW_SINGLE_CARD,
            ),
            (
                "2024 National Treasures Shohei Ohtani Dual Relic Booklet /10",
                RAW_SINGLE_CARD,
            ),
        )

        for title, expected_class in cases:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, expected_class)
                self.assertTrue(classification.actionable)
                self.assertTrue(classification.single_card)
                self.assertTrue(
                    is_relevant_search_result(title, "Shohei Ohtani")
                )


if __name__ == "__main__":
    unittest.main()
