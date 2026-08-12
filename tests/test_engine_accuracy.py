import unittest
from datetime import date, timedelta

import pandas as pd

from profit_engine import analyze_listing, find_best_card_value


def settings(raw_only=True):
    return {
        "ebay_fee_pct": 0.1325,
        "purchase_tax_pct": 0.10,
        "promoted_listing_fee_pct": 0.05,
        "return_defect_allowance_pct": 0.05,
        "grading_loss_risk_pct": 0.01,
        "raw_flip_shipping_allowance": 6.0,
        "psa_grading_fee": 25.0,
        "psa_shipping_insurance_allowance": 12.0,
        "psa_selling_shipping_allowance": 8.0,
        "minimum_raw_flip_profit": 25.0,
        "minimum_raw_flip_roi_pct": 20.0,
        "minimum_psa_expected_profit": 50.0,
        "minimum_psa_expected_roi_pct": 25.0,
        "offer_safety_margin_pct": 0.85,
        "max_offer_market_pct": 0.90,
        "raw_only": raw_only,
    }


def values(*keywords, notes="Verified comps"):
    if not keywords:
        keywords = ("Shohei Ohtani Bowman Chrome RC",)
    return pd.DataFrame([
        {
            "keyword": keyword,
            "raw_market_value": 350,
            "psa9_value": 550,
            "psa10_value": 1100,
            "gem_rate_estimate": 0.55,
            "psa9_rate_estimate": 0.35,
            "verification_status": "verified",
            "verified_at": (date.today() - timedelta(days=1)).isoformat(),
            "expires_at": (date.today() + timedelta(days=30)).isoformat(),
            "source_url": "https://example.com/verified-comps",
            "comp_count": 10,
            "notes": notes,
        }
        for keyword in keywords
    ])


def listing(title, price=22.68, shipping=4.99, condition="Ungraded"):
    return pd.Series({
        "title": title,
        "price": price,
        "shipping": shipping,
        "currency": "USD",
        "item_url": "https://www.ebay.com/itm/336682618676",
        "image_url": "",
        "seller_username": "comc",
        "seller_feedback": 1500741,
        "seller_feedback_pct": 99.6,
        "buying_options": "FIXED_PRICE,BEST_OFFER",
        "condition": condition,
        "item_end_date": "",
    })


class CardIdentityAccuracyTests(unittest.TestCase):
    def assert_non_actionable(
        self,
        title,
        card_values,
        expected_flag,
        raw_only=True,
        condition="Ungraded",
        title_match_should_reject=True,
    ):
        if title_match_should_reject:
            row, strength = find_best_card_value(title, card_values)
            self.assertIsNone(row)
            self.assertEqual(strength, 0.0)

        result = analyze_listing(
            listing(title, condition=condition),
            card_values,
            settings(raw_only=raw_only),
        )

        self.assertEqual(result.matched_card, "")
        self.assertIsNone(result.suggested_offer)
        self.assertIsNone(result.raw_market_value)
        self.assertIsNone(result.psa9_value)
        self.assertIsNone(result.psa10_value)
        self.assertIsNone(result.raw_flip_profit)
        self.assertIsNone(result.psa_expected_profit)
        self.assertEqual(result.best_path, "NONE")
        self.assertEqual(result.recommended_action, "PASS")
        self.assertIn(expected_flag, result.flags.split(";"))

    def test_wrong_or_ambiguous_identity_is_non_actionable(self):
        cases = [
            (
                "cross-set mismatch",
                "Shohei Ohtani Bowman Chrome Refractor Raw",
                values("Shohei Ohtani Topps Chrome Refractor"),
                "card_identity_conflict_set",
                True,
            ),
            (
                "cross-year mismatch",
                "2019 Shohei Ohtani Topps Chrome #150 Refractor Raw",
                values("2018 Shohei Ohtani Topps Chrome #150 Refractor"),
                "card_identity_conflict_year",
                True,
            ),
            (
                "cross-card-number mismatch",
                "2018 Shohei Ohtani Topps Chrome #55 Refractor Raw",
                values("2018 Shohei Ohtani Topps Chrome #150 Refractor"),
                "card_identity_conflict_number",
                True,
            ),
            (
                "cross-parallel mismatch",
                "2018 Shohei Ohtani Topps Chrome #150 Base Raw",
                values("2018 Shohei Ohtani Topps Chrome #150 Refractor"),
                "card_identity_conflict_parallel",
                True,
            ),
            (
                "cross-print-run mismatch",
                "Victor Wembanyama Mosaic Blue 10/199 Raw",
                values("Victor Wembanyama Mosaic Blue /99"),
                "card_identity_conflict_print_run",
                True,
            ),
            (
                "insert mismatch",
                "Michael Jordan Finest Refractor Insert Raw",
                values("Michael Jordan Finest Refractor"),
                "card_identity_conflict_variant",
                True,
            ),
            (
                "reprint listing",
                "Shohei Ohtani Bowman Chrome RC Reprint",
                values(),
                "bad_listing_language",
                True,
            ),
            (
                "ambiguous missing set",
                "Shohei Ohtani Chrome Refractor Raw",
                values(
                    "Shohei Ohtani Topps Chrome Refractor",
                    "Shohei Ohtani Bowman Chrome Refractor",
                ),
                "ambiguous_card_value_match",
                True,
            ),
            (
                "graded listing even when raw-only is disabled",
                "Shohei Ohtani Bowman Chrome RC PSA 10",
                values(),
                "graded_or_slabbed",
                False,
            ),
        ]

        for name, title, card_values, expected_flag, raw_only in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(
                    title,
                    card_values,
                    expected_flag,
                    raw_only=raw_only,
                )

    def test_insufficient_identity_is_non_actionable(self):
        self.assert_non_actionable(
            "Shohei Ohtani",
            values(),
            "insufficient_card_identity",
        )

    def test_compact_and_condition_only_slabs_are_non_actionable(self):
        cases = [
            ("compact PSA grade", "Shohei Ohtani Bowman Chrome RC PSA10", "Ungraded", True),
            ("hyphenated PSA grade", "Shohei Ohtani Bowman Chrome RC PSA-10", "Ungraded", True),
            ("spaced PSA grade", "Shohei Ohtani Bowman Chrome RC PSA 10", "Ungraded", True),
            ("compact BGS decimal grade", "Shohei Ohtani Bowman Chrome RC BGS9.5", "Ungraded", True),
            ("spaced BGS decimal grade", "Shohei Ohtani Bowman Chrome RC BGS 9.5", "Ungraded", True),
            ("compact SGC grade", "Shohei Ohtani Bowman Chrome RC SGC10", "Ungraded", True),
            ("spaced SGC grade", "Shohei Ohtani Bowman Chrome RC SGC 10", "Ungraded", True),
            ("compact CGC grade", "Shohei Ohtani Bowman Chrome RC CGC10", "Ungraded", True),
            ("spaced CGC grade", "Shohei Ohtani Bowman Chrome RC CGC 10", "Ungraded", True),
            ("condition-only graded", "Shohei Ohtani Bowman Chrome RC Raw", "Graded", False),
        ]

        for name, title, condition, title_match_should_reject in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(
                    title,
                    values(),
                    "graded_or_slabbed",
                    raw_only=False,
                    condition=condition,
                    title_match_should_reject=title_match_should_reject,
                )

    def test_parallel_and_unknown_modifier_conflicts_are_non_actionable(self):
        cases = [
            (
                "sepia refractor versus refractor",
                "2018 Shohei Ohtani Topps Chrome #150 Sepia Refractor Raw",
                "card_identity_conflict_parallel",
            ),
            (
                "base versus refractor",
                "2018 Shohei Ohtani Topps Chrome #150 Base Raw",
                "card_identity_conflict_parallel",
            ),
            (
                "unrecognized material modifier",
                "2018 Shohei Ohtani Topps Chrome #150 Refractor MysteryFoil Raw",
                "card_identity_conflict_modifier",
            ),
        ]
        card_values = values("2018 Shohei Ohtani Topps Chrome #150 Refractor")

        for name, title, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(title, card_values, expected_flag)

    def test_closest_rejection_reason_wins_without_a_qualified_match(self):
        card_values = values(
            "2018 Topps Chrome Shohei Ohtani #150 Refractor Rookie "
            "Pitching Angels",
            "Shohei Ohtani Topps Chrome Refractor",
        )

        self.assert_non_actionable(
            "2018 Topps Chrome Shohei Ohtani #150 Sepia Refractor Rookie "
            "Pitching Angels",
            card_values,
            "card_identity_conflict_parallel",
        )

    def test_alternate_year_and_card_number_conflicts_are_non_actionable(self):
        cases = [
            (
                "bare two-digit year mismatch",
                "24 Shohei Ohtani Topps Chrome 150 Refractor Raw",
                values("23 Shohei Ohtani Topps Chrome 150 Refractor"),
                "card_identity_conflict_year",
            ),
            (
                "apostrophe two-digit year mismatch",
                "'24 Shohei Ohtani Topps Chrome 150 Refractor Raw",
                values("'23 Shohei Ohtani Topps Chrome 150 Refractor"),
                "card_identity_conflict_year",
            ),
            (
                "bare card-number mismatch",
                "2018 Shohei Ohtani Topps Chrome 55 Refractor Raw",
                values("2018 Shohei Ohtani Topps Chrome 150 Refractor"),
                "card_identity_conflict_number",
            ),
            (
                "explicit card-number mismatch",
                "2018 Shohei Ohtani Topps Chrome #55 Refractor Raw",
                values("2018 Shohei Ohtani Topps Chrome #150 Refractor"),
                "card_identity_conflict_number",
            ),
        ]

        for name, title, card_values, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(title, card_values, expected_flag)

    def test_valid_refractor_and_bare_card_number_matches_still_work(self):
        cases = [
            (
                "2018 Shohei Ohtani Topps Chrome #150 Refractor Raw",
                values("2018 Shohei Ohtani Topps Chrome #150 Refractor"),
            ),
            (
                "23 Shohei Ohtani Topps Chrome 150 Refractor Raw Sharp",
                values("23 Shohei Ohtani Topps Chrome 150 Refractor"),
            ),
        ]

        for title, card_values in cases:
            with self.subTest(title=title):
                row, strength = find_best_card_value(title, card_values)
                result = analyze_listing(listing(title), card_values, settings())

                self.assertIsNotNone(row)
                self.assertGreater(strength, 0.0)
                self.assertEqual(result.matched_card, card_values.iloc[0]["keyword"])
                self.assertIsNotNone(result.suggested_offer)
                self.assertNotEqual(result.recommended_action, "PASS")

    def test_valid_exact_and_near_exact_matches_still_work(self):
        cases = [
            "Shohei Ohtani Bowman Chrome RC Raw",
            "Bowman Chrome Shohei Ohtani Rookie Raw Sharp",
        ]

        for title in cases:
            with self.subTest(title=title):
                row, strength = find_best_card_value(title, values())
                result = analyze_listing(listing(title), values(), settings())

                self.assertIsNotNone(row)
                self.assertGreater(strength, 0.0)
                self.assertEqual(result.matched_card, "Shohei Ohtani Bowman Chrome RC")
                self.assertIsNotNone(result.suggested_offer)
                self.assertNotEqual(result.recommended_action, "PASS")

    def test_example_valuation_is_never_actionable(self):
        result = analyze_listing(
            listing("Shohei Ohtani Bowman Chrome RC Raw", price=200, shipping=5),
            values(notes="Example only - replace with real comps"),
            settings(),
        )
        self.assertEqual(result.matched_card, "Shohei Ohtani Bowman Chrome RC")
        self.assertIsNone(result.suggested_offer)
        self.assertEqual(result.recommended_action, "PASS")
        self.assertIn("unverified_example_valuation", result.flags)

    def test_offer_is_capped_below_raw_market_value(self):
        result = analyze_listing(
            listing("Shohei Ohtani Bowman Chrome RC Raw", price=500, shipping=0),
            values(),
            settings(),
        )
        self.assertIsNotNone(result.suggested_offer)
        self.assertLessEqual(result.suggested_offer, 315.00)


if __name__ == "__main__":
    unittest.main()
