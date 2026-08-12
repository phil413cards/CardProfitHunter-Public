from __future__ import annotations

import unittest

from card_parser import parse_card_identity
from listing_classifier import (
    RAW_AUTOGRAPH,
    classify_listing,
    has_trading_card_evidence,
)
from profit_engine import _evaluate_card_identity


class AutographTermConsistencyTests(unittest.TestCase):
    def test_autograph_terms_are_classified_and_parsed_consistently(self):
        for term in ("Auto", "Autograph", "Autographed", "Signed"):
            title = f"2024 Topps Chrome Shohei Ohtani {term} Card #17"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")
                identity = parse_card_identity(title, "Shohei Ohtani")

                self.assertTrue(has_trading_card_evidence(title, "Ungraded"))
                self.assertEqual(classification.listing_class, RAW_AUTOGRAPH)
                self.assertTrue(classification.actionable)
                self.assertTrue(classification.autograph)
                self.assertTrue(identity.autograph)

    def test_autograph_query_terms_are_not_part_of_player_identity(self):
        title = "2024 Topps Chrome Shohei Ohtani Autographed Card #17"

        for term in ("auto", "autograph", "autographed", "signed"):
            with self.subTest(term=term):
                identity = parse_card_identity(
                    title,
                    f"Shohei Ohtani {term} card",
                )
                self.assertEqual(identity.player, "Shohei Ohtani")

    def test_autographed_wording_is_a_hard_variant_from_base(self):
        matched, strength, reason, *_ = _evaluate_card_identity(
            "2024 Topps Chrome Shohei Ohtani Autographed Card #17",
            "2024 Topps Chrome Shohei Ohtani #17",
        )

        self.assertFalse(matched)
        self.assertEqual(strength, 0.0)
        self.assertEqual(reason, "card_identity_conflict_variant")

    def test_signed_and_manufacturer_autograph_wording_remain_distinct(self):
        matched, strength, reason, *_ = _evaluate_card_identity(
            "2024 Topps Chrome Shohei Ohtani Signed Card #17",
            "2024 Topps Chrome Shohei Ohtani Autograph #17",
        )

        self.assertFalse(matched)
        self.assertEqual(strength, 0.0)
        self.assertEqual(reason, "card_identity_conflict_variant")

    def test_exact_autographed_identity_remains_matchable(self):
        matched, strength, reason, *_ = _evaluate_card_identity(
            "2024 Topps Chrome Shohei Ohtani Autographed Card #17",
            "2024 Topps Chrome Shohei Ohtani Autographed #17",
        )

        self.assertTrue(matched)
        self.assertEqual(strength, 1.0)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
