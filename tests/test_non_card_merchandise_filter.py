from __future__ import annotations

import unittest

from listing_classifier import (
    NON_CARD_MERCHANDISE,
    RAW_PARALLEL,
    classify_listing,
)
from search_relevance import (
    excluded_listing_reason,
    is_relevant_search_result,
)


class NonCardMerchandiseFilterTests(unittest.TestCase):
    def test_ohtani_hat_is_rejected_as_non_card_merchandise(self):
        title = (
            "Hat Club Los Angeles Dodgers New Era Cap 7 1/8 "
            "59FIFTY Blue Shohei Ohtani Anime"
        )
        classification = classify_listing(title)

        self.assertEqual(
            classification.listing_class,
            NON_CARD_MERCHANDISE,
        )
        self.assertFalse(classification.actionable)
        self.assertFalse(classification.raw)
        self.assertFalse(classification.single_card)
        self.assertEqual(
            classification.exclusion_reason,
            "non_card_merchandise",
        )

    def test_ohtani_hat_is_removed_by_search_relevance(self):
        title = (
            "Hat Club Los Angeles Dodgers New Era Cap 7 1/8 "
            "59FIFTY Blue Shohei Ohtani Anime"
        )

        self.assertEqual(
            excluded_listing_reason(title, "Shohei Ohtani"),
            "non_card_merchandise",
        )
        self.assertFalse(
            is_relevant_search_result(title, "Shohei Ohtani")
        )

    def test_topps_chrome_refractor_remains_actionable(self):
        title = "2024 Topps Chrome Shohei Ohtani #1 Refractor"
        classification = classify_listing(title)

        self.assertEqual(classification.listing_class, RAW_PARALLEL)
        self.assertTrue(classification.actionable)
        self.assertTrue(classification.single_card)
        self.assertTrue(
            is_relevant_search_result(title, "Shohei Ohtani")
        )

    def test_national_treasures_jersey_patch_remains_actionable(self):
        title = (
            "2023 National Treasures Shohei Ohtani "
            "Game Used Jersey Patch /25"
        )
        classification = classify_listing(title)

        self.assertNotEqual(
            classification.listing_class,
            NON_CARD_MERCHANDISE,
        )
        self.assertTrue(classification.actionable)
        self.assertTrue(classification.single_card)
        self.assertTrue(
            is_relevant_search_result(title, "Shohei Ohtani")
        )


if __name__ == "__main__":
    unittest.main()
