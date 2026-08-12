import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ebay_client import normalize_ebay_items
from profit_engine import (
    analyze_listing,
    analyze_listings,
    calc_max_buy_prices,
    calc_psa_flip,
    calc_raw_flip,
    contains_term,
    detect_print_run,
)


ROOT = Path(__file__).resolve().parents[1]


def engine_settings(**overrides):
    result = {
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
        "verification_status": "verified",
        "verified_at": (date.today() - timedelta(days=1)).isoformat(),
        "expires_at": (date.today() + timedelta(days=30)).isoformat(),
        "source_url": "https://example.com/verified-comps",
        "comp_count": 10,
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
        values = verified_values()
        result = analyze_listing(
            complete_listing(),
            values,
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
        source = values.iloc[0]
        self.assertEqual(result.verification_status, "verified")
        self.assertEqual(result.verified_at, source["verified_at"])
        self.assertEqual(result.expires_at, source["expires_at"])
        self.assertEqual(result.source_url, source["source_url"])
        self.assertEqual(result.comp_count, 10)
        self.assertEqual(result.valuation_notes, source["notes"])

    def test_expired_or_unverifiable_valuations_are_nonfinancial(self):
        cases = (
            (
                "expired",
                {"expires_at": (date.today() - timedelta(days=1)).isoformat()},
                "expired_valuation",
            ),
            (
                "missing status",
                {"verification_status": None},
                "missing_valuation_provenance",
            ),
            (
                "missing source",
                {"source_url": ""},
                "missing_valuation_provenance",
            ),
            (
                "credential-bearing source",
                {"source_url": "https://user:private@example.com/comps"},
                "invalid_valuation_provenance",
            ),
            (
                "malformed expiry",
                {"expires_at": "not-a-date"},
                "invalid_valuation_provenance",
            ),
            (
                "unverified status",
                {"verification_status": "unverified"},
                "unverified_valuation_status",
            ),
        )

        for name, overrides, expected_flag in cases:
            with self.subTest(name=name):
                values = verified_values()
                for field, value in overrides.items():
                    values[field] = values[field].astype(object)
                    values.loc[0, field] = value

                result = analyze_listing(
                    complete_listing(),
                    values,
                    engine_settings(),
                )

                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(
                    result.matched_card,
                    "Shohei Ohtani Bowman Chrome RC",
                )
                self.assertIn("non_actionable_valuation", result.flags.split(";"))
                self.assertIn(expected_flag, result.flags.split(";"))
                self.assert_no_financial_fields(result)
                self.assertEqual(result.verification_status, "")
                self.assertEqual(result.verified_at, "")
                self.assertEqual(result.expires_at, "")
                self.assertEqual(result.source_url, "")
                self.assertIsNone(result.comp_count)
                self.assertEqual(result.valuation_notes, "")

    def test_legacy_valuation_without_provenance_columns_is_nonfinancial(self):
        values = verified_values().drop(
            columns=[
                "verification_status",
                "verified_at",
                "expires_at",
                "source_url",
                "comp_count",
            ]
        )

        result = analyze_listing(
            complete_listing(),
            values,
            engine_settings(),
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertIn("missing_valuation_provenance", result.flags.split(";"))
        self.assert_no_financial_fields(result)

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

    def test_roi_uses_total_modeled_cost_including_risk_allowances(self):
        settings = engine_settings(
            ebay_fee_pct=0.10,
            purchase_tax_pct=0.08,
            promoted_listing_fee_pct=0.03,
            return_defect_allowance_pct=0.04,
            grading_loss_risk_pct=0.02,
            raw_flip_shipping_allowance=6.0,
            psa_grading_fee=25.0,
            psa_shipping_insurance_allowance=12.0,
            psa_selling_shipping_allowance=8.0,
        )

        raw_profit, raw_roi = calc_raw_flip(110.0, 200.0, settings)
        raw_purchase_tax = 110.0 * 0.08
        raw_marketplace_fee = 200.0 * 0.10
        raw_promoted_fee = 200.0 * 0.03
        raw_return_allowance = 200.0 * 0.04
        raw_total_cost = (
            110.0
            + raw_purchase_tax
            + raw_marketplace_fee
            + raw_promoted_fee
            + raw_return_allowance
            + 6.0
        )
        expected_raw_profit = round(200.0 - raw_total_cost, 2)
        self.assertEqual(raw_profit, expected_raw_profit)
        self.assertAlmostEqual(
            raw_roi,
            round((expected_raw_profit / raw_total_cost) * 100, 1),
        )

        expected_sale, psa_profit, psa_roi = calc_psa_flip(
            110.0,
            raw_market_value=100.0,
            psa9_value=200.0,
            psa10_value=400.0,
            gem_rate=0.5,
            psa9_rate=0.5,
            settings=settings,
        )
        psa_purchase_with_tax = 110.0 * 1.08
        psa_grading_costs_at_risk = 25.0 + 12.0
        psa_grading_loss_allowance = (
            psa_purchase_with_tax + psa_grading_costs_at_risk
        ) * 0.02
        psa_marketplace_fee = 300.0 * 0.10
        psa_promoted_fee = 300.0 * 0.03
        psa_return_allowance = 300.0 * 0.04
        psa_total_cost = (
            psa_purchase_with_tax
            + psa_grading_costs_at_risk
            + psa_grading_loss_allowance
            + 8.0
            + psa_marketplace_fee
            + psa_promoted_fee
            + psa_return_allowance
        )
        self.assertEqual(expected_sale, 300.0)
        expected_psa_profit = round(300.0 - psa_total_cost, 2)
        self.assertEqual(psa_profit, expected_psa_profit)
        self.assertAlmostEqual(
            psa_roi,
            round((expected_psa_profit / psa_total_cost) * 100, 1),
        )

    def test_new_costs_reduce_max_buy_prices(self):
        zero_risk_settings = engine_settings(
            purchase_tax_pct=0.0,
            promoted_listing_fee_pct=0.0,
            return_defect_allowance_pct=0.0,
            grading_loss_risk_pct=0.0,
        )
        modeled_risk_settings = engine_settings(
            purchase_tax_pct=0.10,
            promoted_listing_fee_pct=0.05,
            return_defect_allowance_pct=0.05,
            grading_loss_risk_pct=0.01,
        )

        zero_raw, zero_psa = calc_max_buy_prices(
            verified_values().iloc[0],
            zero_risk_settings,
        )
        modeled_raw, modeled_psa = calc_max_buy_prices(
            verified_values().iloc[0],
            modeled_risk_settings,
        )

        self.assertLess(modeled_raw, zero_raw)
        self.assertLess(modeled_psa, zero_psa)

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
            (
                "missing purchase tax",
                engine_settings(purchase_tax_pct=None),
                "missing_modeled_cost_purchase_tax_pct",
            ),
            (
                "invalid promoted listing fee",
                engine_settings(promoted_listing_fee_pct=-0.01),
                "invalid_modeled_cost_promoted_listing_fee_pct",
            ),
            (
                "invalid return allowance",
                engine_settings(return_defect_allowance_pct=1.01),
                "invalid_modeled_cost_return_defect_allowance_pct",
            ),
            (
                "invalid grading loss risk",
                engine_settings(grading_loss_risk_pct=1.01),
                "invalid_modeled_cost_grading_loss_risk_pct",
            ),
            (
                "combined selling rates above sale value",
                engine_settings(
                    ebay_fee_pct=0.50,
                    promoted_listing_fee_pct=0.30,
                    return_defect_allowance_pct=0.30,
                ),
                "invalid_modeled_cost_combined_selling_rate",
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
