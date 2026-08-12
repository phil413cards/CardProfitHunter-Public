import unittest

from listing_classifier import (
    BOX_BREAK,
    GRADED_CARD,
    PICK_YOUR_CARD,
    RAW_AUTOGRAPH,
    RAW_PARALLEL,
    classify_listing,
)


class ListingClassifierTests(unittest.TestCase):
    def test_classifies_parallel_as_actionable(self):
        result = classify_listing(
            "2024 Topps Chrome Shohei Ohtani Gold Refractor /50"
        )

        self.assertEqual(result.listing_class, RAW_PARALLEL)
        self.assertTrue(result.actionable)

    def test_rejects_pick_your_card(self):
        result = classify_listing(
            "2024 Topps Chrome Pick Your Card Shohei Ohtani"
        )

        self.assertEqual(result.listing_class, PICK_YOUR_CARD)
        self.assertFalse(result.actionable)

    def test_rejects_break(self):
        self.assertEqual(
            classify_listing("Shohei Ohtani Case Break").listing_class,
            BOX_BREAK,
        )

    def test_recognizes_graded(self):
        self.assertEqual(
            classify_listing("Shohei Ohtani PSA 10").listing_class,
            GRADED_CARD,
        )

    def test_recognizes_raw_autograph(self):
        self.assertEqual(
            classify_listing("Shohei Ohtani On Card Auto").listing_class,
            RAW_AUTOGRAPH,
        )


if __name__ == "__main__":
    unittest.main()
