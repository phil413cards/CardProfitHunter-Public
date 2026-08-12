from __future__ import annotations

import unittest

import pandas as pd

from listing_classifier import (
    MULTI_CARD_LISTING,
    RAW_PARALLEL,
    SEALED_PRODUCT,
    classify_listing,
)
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


PRODUCT_EXCLUSIONS = (
    (
        "2024 Topps Chrome Retail Box Shohei Ohtani Rookie Refractor",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Panini Prizm Hanger Box Victor Wembanyama Rookie Silver",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Display Box Shohei Ohtani Rookie Card",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Panini Prizm Booster Box Victor Wembanyama Rookie Silver",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Sealed Case Shohei Ohtani Rookie Cards",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Hobby Case Shohei Ohtani Rookie Cards",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Panini Prizm Mega Tin Victor Wembanyama Rookie Card",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Empty Box Shohei Ohtani Refractor",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Unopened Pack Shohei Ohtani Rookie Card",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Baseball Pack Shohei Ohtani Rookie Card",
        SEALED_PRODUCT,
        "sealed_product",
    ),
    (
        "2024 Topps Chrome Complete Set Shohei Ohtani Rookie Card",
        MULTI_CARD_LISTING,
        "multi_card_set_or_bundle",
    ),
    (
        "2024 Topps Chrome Factory Set Shohei Ohtani Rookie Card",
        MULTI_CARD_LISTING,
        "multi_card_set_or_bundle",
    ),
    (
        "2024 Topps Chrome 10 Card Bundle Shohei Ohtani Rookie",
        MULTI_CARD_LISTING,
        "multi_card_set_or_bundle",
    ),
    (
        "2024 Topps Chrome Collection of 20 Cards Shohei Ohtani",
        MULTI_CARD_LISTING,
        "multi_card_set_or_bundle",
    ),
    (
        "2024 Topps Chrome Shohei Ohtani 5 Card Set",
        MULTI_CARD_LISTING,
        "multi_card_set_or_bundle",
    ),
)


class ScoutProductExclusionTests(unittest.TestCase):
    def test_products_and_bundles_are_nonactionable(self):
        for title, expected_class, expected_reason in PRODUCT_EXCLUSIONS:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, expected_class)
                self.assertEqual(classification.exclusion_reason, expected_reason)
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_products_and_bundles_are_removed_before_scout_analysis(self):
        for title, _, expected_reason in PRODUCT_EXCLUSIONS:
            with self.subTest(title=title):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    expected_reason,
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

    def test_scout_boundary_rechecks_product_type(self):
        row = pd.Series({
            "title": PRODUCT_EXCLUSIONS[0][0],
            "condition": "Ungraded",
            "recommended_action": "PASS",
            "valuation_available": False,
            "listing_actionable": True,
            "grading_candidate": True,
            "listing_listing_class": RAW_PARALLEL,
            "grading_signal_score": 100,
            "parsed_print_run": 25,
            "parsed_rookie": True,
            "parsed_autograph": False,
            "parsed_parallel": "Refractor",
            "parsed_card_number": "1",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_legitimate_single_card_wording_remains_actionable(self):
        titles = (
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Pack Fresh",
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Pack Pulled",
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Fresh From Pack",
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Pulled From a Pack",
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Box Topper Card",
            "2024 Topps Chrome Shohei Ohtani #1 Refractor Single Card",
        )

        for title in titles:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, RAW_PARALLEL)
                self.assertTrue(classification.actionable)
                self.assertTrue(classification.single_card)
                self.assertTrue(
                    is_relevant_search_result(title, "Shohei Ohtani")
                )


if __name__ == "__main__":
    unittest.main()
