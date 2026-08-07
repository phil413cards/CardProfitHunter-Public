from __future__ import annotations

import unittest
from pathlib import Path

from card_parser import parse_card_identity
from grading_estimator import estimate_grading_candidate
from listing_classifier import (
    CONDITION_AMBIGUOUS,
    MULTI_CARD_LISTING,
    RAW_AUTOGRAPH,
    classify_listing,
)
from search_relevance import (
    excluded_listing_reason,
    is_relevant_search_result,
)


class MixedCardSafetyTests(unittest.TestCase):
    def test_ohtani_murakami_plus_listing_is_rejected(self):
        title = (
            "Shohei Ohtani Refractor + Munetaka Murakami "
            "Crackle Foil #91b2-12 RC (READ)"
        )
        classification = classify_listing(title)

        self.assertEqual(
            classification.listing_class,
            MULTI_CARD_LISTING,
        )
        self.assertFalse(classification.actionable)
        self.assertFalse(classification.single_card)
        self.assertEqual(
            classification.exclusion_reason,
            "plus_separated_multi_card_listing",
        )
        self.assertFalse(
            is_relevant_search_result(title, "Shohei Ohtani")
        )

    def test_mixed_card_listing_is_not_a_grading_candidate(self):
        title = (
            "Shohei Ohtani Refractor + Munetaka Murakami "
            "Crackle Foil #91b2-12 RC (READ)"
        )
        classification = classify_listing(title)
        identity = parse_card_identity(title, "Shohei Ohtani")
        estimate = estimate_grading_candidate(
            title,
            "",
            classification,
            identity,
        )

        self.assertFalse(estimate.grading_candidate)

    def test_dual_player_single_card_remains_eligible(self):
        title = "Shohei Ohtani + Aaron Judge Dual Auto /10"
        classification = classify_listing(title)

        self.assertEqual(classification.listing_class, RAW_AUTOGRAPH)
        self.assertTrue(classification.actionable)
        self.assertTrue(classification.single_card)
        self.assertTrue(
            is_relevant_search_result(title, "Shohei Ohtani")
        )

    def test_dual_relic_booklet_remains_eligible(self):
        title = (
            "2023 National Treasures Shohei Ohtani / "
            "Mike Trout Dual Relic Booklet /10"
        )
        classification = classify_listing(title)

        self.assertTrue(classification.actionable)
        self.assertTrue(classification.single_card)
        self.assertTrue(
            is_relevant_search_result(title, "Shohei Ohtani")
        )

    def test_read_condition_blocks_automatic_grading(self):
        title = "2024 Topps Chrome Shohei Ohtani Refractor (READ)"
        classification = classify_listing(title)

        self.assertEqual(
            classification.listing_class,
            CONDITION_AMBIGUOUS,
        )
        self.assertFalse(classification.actionable)
        self.assertTrue(classification.single_card)
        self.assertEqual(
            excluded_listing_reason(title, "Shohei Ohtani"),
            "condition_ambiguous",
        )

    def test_plus_marketing_text_does_not_create_false_bundle(self):
        title = "2024 Topps Chrome Shohei Ohtani Refractor + Free Shipping"
        classification = classify_listing(title)

        self.assertTrue(classification.actionable)
        self.assertTrue(classification.single_card)

    def test_ui_counts_financial_pass_and_uses_neutral_download_label(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn(
            'pass_count = int(counts.get("PASS", 0))',
            source,
        )
        self.assertIn(
            'c5.metric("Financial Pass", pass_count)',
            source,
        )
        self.assertIn('"Download Search Results CSV"', source)
        self.assertIn('"live_ebay_search_results.csv"', source)


if __name__ == "__main__":
    unittest.main()
