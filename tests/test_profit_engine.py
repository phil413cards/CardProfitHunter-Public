import json
import unittest
from pathlib import Path

import pandas as pd

from ebay_client import normalize_ebay_items
from profit_engine import (
    analyze_listing,
    analyze_listings,
    calc_psa_flip,
    calc_raw_flip,
    contains_term,
    detect_print_run,
)


ROOT = Path(__file__).resolve().parents[1]


def engine_settings(**overrides):
    result = {
        "ebay_fee_pct": 0.1325,
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
        "raw_only": True,
    }
    result.update(overrides)
    return result


def verified_values():
    return pd.DataFrame([{
        "keyword": "Shohei Ohtani Bowman Chrome RC",
        "raw_market_value": 350,
        "psa9_value": 550,
        "psa10_value": 1100,
        "gem_rate_estimate": 0.55,
        "psa9_rate_estimate": 0.35,
        "notes": "Verified comps",
    }])


def complete_listing(**overrides):
    data = {
        "title": "Shohei Ohtani Bowman Chrome RC Raw",
        "price": 100.0,
        "shipping": 5.0,
        "currency": "USD",
        "item_url": "https://www.ebay.com/itm/test",
        "image_url": "",
        "seller_username": "test",
        "seller_feedback": 100,
        "seller_feedback_pct": 100.0,
        "buying_options": "FIXED_PRICE",
        "condition": "Ungraded",
        "item_end_date": "",
    }
    data.update(overrides)
    return pd.Series(data)


class ProfitEngineTests(unittest.TestCase):
    def assert_no_financial_fields(self, result):
        self.assertEqual(result.best_path, "NONE")
        for field in (
            "best_expected_profit",
            "best_expected_roi_pct",
            "raw_flip_profit",
            "raw_flip_roi_pct",
            "psa_expected_profit",
            "psa_expected_roi_pct",
            "psa_expected_sale_value",
            "max_buy_price_raw_flip",
            "max_buy_price_psa_flip",
            "suggested_offer",
            "raw_market_value",
            "psa9_value",
            "psa10_value",
            "gem_rate_estimate",
            "psa9_rate_estimate",
        ):
            self.assertIsNone(getattr(result, field), field)

    def assert_non_actionable(self, listing, expected_flag, settings=None):
        result = analyze_listing(
            listing,
            verified_values(),
            settings or engine_settings(),
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.matched_card, "")
        self.assert_no_financial_fields(result)
        self.assertIn(expected_flag, result.flags.split(";"))

    def test_non_actionable_valuation_notes_are_nonfinancial(self):
        cases = [
            ("example", "Example only - replace with real comps"),
            ("demo", "Demo valuation"),
            ("demonstration", "Demonstration data"),
            ("unverified", "Unverified estimate"),
            ("non-actionable", "Non-actionable placeholder"),
        ]

        for name, notes in cases:
            with self.subTest(name=name):
                card_values = verified_values()
                card_values.loc[0, "notes"] = notes
                result = analyze_listing(
                    complete_listing(),
                    card_values,
                    engine_settings(),
                )

                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(
                    result.matched_card,
                    "Shohei Ohtani Bowman Chrome RC",
                )
                self.assertIn("non_actionable_valuation", result.flags.split(";"))
                self.assert_no_financial_fields(result)

    def test_verified_actionable_valuation_retains_financial_fields(self):
        result = analyze_listing(
            complete_listing(),
            verified_values(),
            engine_settings(),
        )

        self.assertIn(
            result.recommended_action,
            {"BUY", "OFFER", "BUY_RAW_FLIP", "BUY_GRADE_PSA"},
        )
        self.assertNotEqual(result.best_path, "NONE")
        self.assertIsNotNone(result.best_expected_profit)
        self.assertIsNotNone(result.best_expected_roi_pct)
        self.assertIsNotNone(result.raw_market_value)
        self.assertIsNotNone(result.raw_flip_profit)

    def test_watch_result_is_nonfinancial(self):
        card_values = verified_values()
        card_values.loc[0, "keyword"] = "Shohei Ohtani Bowman Chrome RC 1/1"
        for field in ("raw_market_value", "psa9_value", "psa10_value"):
            card_values.loc[0, field] = 0
        result = analyze_listing(
            complete_listing(title="Shohei Ohtani Bowman Chrome RC 1/1 Raw"),
            card_values,
            engine_settings(),
        )

        self.assertEqual(result.recommended_action, "WATCH")
        self.assert_no_financial_fields(result)

    def test_roi_uses_total_modeled_cost(self):
        settings = engine_settings(
            ebay_fee_pct=0.10,
            raw_flip_shipping_allowance=6.0,
            psa_grading_fee=25.0,
            psa_shipping_insurance_allowance=12.0,
            psa_selling_shipping_allowance=8.0,
        )

        raw_profit, raw_roi = calc_raw_flip(110.0, 200.0, settings)
        raw_total_cost = 110.0 + 20.0 + 6.0
        self.assertEqual(raw_profit, 64.0)
        self.assertAlmostEqual(raw_roi, round((64.0 / raw_total_cost) * 100, 1))

        expected_sale, psa_profit, psa_roi = calc_psa_flip(
            110.0,
            raw_market_value=100.0,
            psa9_value=200.0,
            psa10_value=400.0,
            gem_rate=0.5,
            psa9_rate=0.5,
            settings=settings,
        )
        psa_total_cost = 110.0 + 25.0 + 12.0 + 8.0 + 30.0
        self.assertEqual(expected_sale, 300.0)
        self.assertEqual(psa_profit, 115.0)
        self.assertAlmostEqual(psa_roi, round((115.0 / psa_total_cost) * 100, 1))

    def test_incomplete_or_incompatible_listings_are_non_actionable(self):
        cases = [
            ("missing price", {"price": None}, "missing_price"),
            ("nan price", {"price": float("nan")}, "missing_price"),
            ("zero price", {"price": 0}, "invalid_price"),
            ("negative price", {"price": -1}, "invalid_price"),
            ("invalid price", {"price": "unknown"}, "invalid_price"),
            ("missing shipping", {"shipping": None}, "missing_shipping"),
            ("nan shipping", {"shipping": float("nan")}, "missing_shipping"),
            ("negative shipping", {"shipping": -1}, "invalid_shipping"),
            ("invalid shipping", {"shipping": "unknown"}, "invalid_shipping"),
            ("missing currency", {"currency": ""}, "missing_currency"),
            ("nan currency", {"currency": float("nan")}, "missing_currency"),
            ("pd.NA currency", {"currency": pd.NA}, "missing_currency"),
            ("unsupported currency", {"currency": "EUR"}, "unsupported_currency"),
            ("missing buying option", {"buying_options": ""}, "missing_buying_option"),
            (
                "nan buying option",
                {"buying_options": float("nan")},
                "missing_buying_option",
            ),
            (
                "pd.NA buying option",
                {"buying_options": pd.NA},
                "missing_buying_option",
            ),
            ("auction", {"buying_options": "AUCTION"}, "unsupported_buying_option"),
            ("classified", {"buying_options": "CLASSIFIED_AD"}, "unsupported_buying_option"),
            ("unknown option", {"buying_options": "SOMETHING_NEW"}, "unsupported_buying_option"),
            ("missing condition", {"condition": ""}, "missing_condition"),
            ("nan condition", {"condition": float("nan")}, "missing_condition"),
            ("pd.NA condition", {"condition": pd.NA}, "missing_condition"),
            ("graded condition", {"condition": "Graded"}, "graded_or_slabbed"),
        ]

        for name, overrides, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(complete_listing(**overrides), expected_flag)

    def test_missing_or_invalid_modeled_cost_is_non_actionable(self):
        cases = [
            (
                "missing grading fee",
                engine_settings(psa_grading_fee=None),
                "missing_modeled_cost_psa_grading_fee",
            ),
            (
                "invalid raw shipping allowance",
                engine_settings(raw_flip_shipping_allowance=-1),
                "invalid_modeled_cost_raw_flip_shipping_allowance",
            ),
            (
                "invalid fee percentage",
                engine_settings(ebay_fee_pct=1.5),
                "invalid_modeled_cost_ebay_fee_pct",
            ),
        ]

        for name, settings, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(
                    complete_listing(),
                    expected_flag,
                    settings,
                )

    def test_explicit_free_shipping_and_complete_usd_listing_can_proceed(self):
        cases = [
            ("explicit free shipping", complete_listing(shipping=0.0)),
            ("complete paid shipping", complete_listing(shipping=5.0)),
        ]

        for name, listing in cases:
            with self.subTest(name=name):
                result = analyze_listing(listing, verified_values(), engine_settings())
                self.assertIn(
                    result.recommended_action,
                    {"BUY_RAW_FLIP", "BUY_GRADE_PSA"},
                )
                self.assertIsNotNone(result.raw_flip_roi_pct)
                self.assertIsNotNone(result.psa_expected_roi_pct)

    def test_offer_requires_best_offer_support(self):
        best_offer = analyze_listing(
            complete_listing(price=600.0, buying_options="BEST_OFFER"),
            verified_values(),
            engine_settings(),
        )
        fixed_price = analyze_listing(
            complete_listing(price=600.0, buying_options="FIXED_PRICE"),
            verified_values(),
            engine_settings(),
        )

        self.assertEqual(best_offer.recommended_action, "OFFER")
        self.assertIsNotNone(best_offer.suggested_offer)
        self.assertGreater(best_offer.suggested_offer, 0)
        self.assertEqual(fixed_price.recommended_action, "PASS")
        self.assertIsNone(fixed_price.suggested_offer)
        self.assertIn("offer_not_supported", fixed_price.flags.split(";"))

    def test_max_buy_and_offer_satisfy_total_cost_roi_threshold(self):
        offer_result = analyze_listing(
            complete_listing(price=600.0, shipping=5.0, buying_options="BEST_OFFER"),
            verified_values(),
            engine_settings(),
        )
        self.assertIsNotNone(offer_result.max_buy_price_psa_flip)
        self.assertIsNotNone(offer_result.suggested_offer)

        at_psa_cap = analyze_listing(
            complete_listing(
                price=offer_result.max_buy_price_psa_flip,
                shipping=5.0,
                buying_options="FIXED_PRICE",
            ),
            verified_values(),
            engine_settings(),
        )
        self.assertGreaterEqual(at_psa_cap.psa_expected_profit, 50.0)
        self.assertGreaterEqual(at_psa_cap.psa_expected_roi_pct, 25.0)
        self.assertIn(at_psa_cap.recommended_action, {"BUY_RAW_FLIP", "BUY_GRADE_PSA"})

        above_psa_cap = analyze_listing(
            complete_listing(
                price=offer_result.max_buy_price_psa_flip + 0.01,
                shipping=5.0,
                buying_options="FIXED_PRICE",
            ),
            verified_values(),
            engine_settings(),
        )
        self.assertEqual(above_psa_cap.recommended_action, "PASS")
        self.assertIn("offer_not_supported", above_psa_cap.flags.split(";"))

        at_offer = analyze_listing(
            complete_listing(
                price=offer_result.suggested_offer,
                shipping=5.0,
                buying_options="FIXED_PRICE",
            ),
            verified_values(),
            engine_settings(),
        )
        self.assertIn(at_offer.recommended_action, {"BUY_RAW_FLIP", "BUY_GRADE_PSA"})

    def test_ebay_normalization_preserves_unknown_and_free_shipping(self):
        result = normalize_ebay_items([
            {
                "itemId": "unknown-shipping",
                "title": "Unknown shipping",
                "price": {"value": "10", "currency": "USD"},
                "buyingOptions": ["FIXED_PRICE"],
            },
            {
                "itemId": "free-shipping",
                "title": "Free shipping",
                "price": {"value": "10", "currency": "USD"},
                "shippingOptions": [{"shippingCost": {"value": "0", "currency": "USD"}}],
                "buyingOptions": ["FIXED_PRICE"],
            },
            {
                "itemId": "missing-price",
                "title": "Missing price",
                "price": {},
                "shippingOptions": [{"shippingCost": {"value": "5", "currency": "USD"}}],
                "buyingOptions": ["FIXED_PRICE"],
            },
        ]).set_index("item_id")

        self.assertTrue(pd.isna(result.loc["unknown-shipping", "shipping"]))
        self.assertEqual(result.loc["free-shipping", "shipping"], 0.0)
        self.assertTrue(pd.isna(result.loc["missing-price", "price"]))
        self.assertEqual(result.loc["missing-price", "currency"], "")

    def test_print_run_detection(self):
        self.assertEqual(detect_print_run("Card 07/25")[0], 25)
        self.assertEqual(detect_print_run("Card 1/1")[0], 1)
        self.assertEqual(detect_print_run("Card 5 of 99")[0], 99)

    def test_bad_word_does_not_match_sharp(self):
        self.assertFalse(contains_term("Shohei Ohtani Bowman Chrome RC Raw Sharp", ["rp"]))

    def test_reprint_is_bad(self):
        self.assertTrue(contains_term("custom art reprint card", ["reprint"]))

    def test_sample_analysis_has_buy_candidates(self):
        settings = json.loads((ROOT / "config" / "settings.json").read_text())
        listings = pd.read_csv(ROOT / "sample_data" / "sample_listings.csv")
        values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")

        result = analyze_listings(listings, values, settings)

        self.assertGreater(len(result), 0)
        # Bundled valuations are explicitly marked as examples and must never
        # create actionable buy recommendations.
        self.assertEqual(set(result["recommended_action"]), {"PASS"})
        self.assertEqual(set(result["best_path"]), {"NONE"})
        for field in (
            "best_expected_profit",
            "best_expected_roi_pct",
            "raw_flip_profit",
            "raw_flip_roi_pct",
            "psa_expected_profit",
            "psa_expected_roi_pct",
            "psa_expected_sale_value",
            "max_buy_price_raw_flip",
            "max_buy_price_psa_flip",
            "suggested_offer",
            "raw_market_value",
            "psa9_value",
            "psa10_value",
        ):
            self.assertTrue(result[field].isna().all(), field)

    def test_custom_reprint_passes(self):
        settings = json.loads((ROOT / "config" / "settings.json").read_text())
        listings = pd.DataFrame([{
            "title": "Victor Wembanyama custom art card reprint",
            "price": 20,
            "shipping": 4,
            "currency": "USD",
            "item_url": "",
            "image_url": "",
            "seller_username": "test",
            "seller_feedback": 1,
            "seller_feedback_pct": 100,
            "buying_options": "FIXED_PRICE",
            "condition": "Used",
            "item_end_date": "",
        }])
        values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")

        result = analyze_listings(listings, values, settings)
        self.assertEqual(result.iloc[0]["recommended_action"], "PASS")


if __name__ == "__main__":
    unittest.main()
