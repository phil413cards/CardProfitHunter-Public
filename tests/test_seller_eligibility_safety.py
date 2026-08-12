import unittest
from datetime import date, timedelta

import pandas as pd

from profit_engine import analyze_listing


def settings():
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
        "raw_only": True,
    }


def verified_values():
    return pd.DataFrame(
        [
            {
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
            }
        ]
    )


def listing(**overrides):
    row = {
        "title": "Shohei Ohtani Bowman Chrome RC Raw",
        "price": 100.0,
        "shipping": 5.0,
        "currency": "USD",
        "item_url": "https://www.ebay.com/itm/test",
        "image_url": "",
        "seller_username": "trusted-seller",
        "seller_feedback": 100,
        "seller_feedback_pct": 99.0,
        "buying_options": "FIXED_PRICE",
        "condition": "Ungraded",
        "item_end_date": "",
    }
    row.update(overrides)
    return pd.Series(row)


class SellerEligibilitySafetyTests(unittest.TestCase):
    def assert_non_actionable(self, overrides, expected_flag):
        result = analyze_listing(
            listing(**overrides),
            verified_values(),
            settings(),
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.matched_card, "")
        self.assertEqual(result.best_path, "NONE")
        self.assertIsNone(result.suggested_offer)
        self.assertIn(expected_flag, result.flags.split(";"))
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
            "raw_market_value",
            "psa9_value",
            "psa10_value",
        ):
            self.assertIsNone(getattr(result, field), field)

    def test_missing_and_invalid_seller_identity_is_non_actionable(self):
        cases = (
            ("missing", {"seller_username": None}, "missing_seller_username"),
            ("blank", {"seller_username": "   "}, "missing_seller_username"),
            ("nan", {"seller_username": float("nan")}, "missing_seller_username"),
            ("pd.NA", {"seller_username": pd.NA}, "missing_seller_username"),
            ("non-string", {"seller_username": ["seller"]}, "invalid_seller_username"),
        )

        for name, overrides, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(overrides, expected_flag)

    def test_missing_invalid_and_low_feedback_count_is_non_actionable(self):
        cases = (
            ("missing", None, "missing_seller_feedback"),
            ("nan", float("nan"), "missing_seller_feedback"),
            ("pd.NA", pd.NA, "missing_seller_feedback"),
            ("text", "many", "invalid_seller_feedback"),
            ("container", [], "invalid_seller_feedback"),
            ("boolean", True, "invalid_seller_feedback"),
            ("fractional", 100.5, "invalid_seller_feedback"),
            ("negative", -1, "invalid_seller_feedback"),
            ("below threshold", 99, "insufficient_seller_feedback"),
        )

        for name, value, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(
                    {"seller_feedback": value},
                    expected_flag,
                )

    def test_missing_invalid_and_low_feedback_percentage_is_non_actionable(self):
        cases = (
            ("missing", None, "missing_seller_feedback_pct"),
            ("nan", float("nan"), "missing_seller_feedback_pct"),
            ("pd.NA", pd.NA, "missing_seller_feedback_pct"),
            ("text", "high", "invalid_seller_feedback_pct"),
            ("container", {}, "invalid_seller_feedback_pct"),
            ("boolean", False, "invalid_seller_feedback_pct"),
            ("negative", -0.1, "invalid_seller_feedback_pct"),
            ("above 100", 100.1, "invalid_seller_feedback_pct"),
            ("below threshold", 98.99, "insufficient_seller_feedback_pct"),
        )

        for name, value, expected_flag in cases:
            with self.subTest(name=name):
                self.assert_non_actionable(
                    {"seller_feedback_pct": value},
                    expected_flag,
                )

    def test_boundary_and_numeric_string_values_remain_actionable(self):
        cases = (
            ("exact boundary", {"seller_feedback": 100, "seller_feedback_pct": 99.0}),
            (
                "numeric strings",
                {"seller_feedback": "100", "seller_feedback_pct": "99.0"},
            ),
            (
                "above boundary",
                {"seller_feedback": 1000, "seller_feedback_pct": 100.0},
            ),
        )

        for name, overrides in cases:
            with self.subTest(name=name):
                result = analyze_listing(
                    listing(**overrides),
                    verified_values(),
                    settings(),
                )
                self.assertIn(
                    result.recommended_action,
                    {"BUY_RAW_FLIP", "BUY_GRADE_PSA"},
                )
                self.assertNotEqual(result.matched_card, "")
                self.assertIsNotNone(result.best_expected_profit)

    def test_low_feedback_blocks_offer_and_clears_offer_fields(self):
        self.assert_non_actionable(
            {
                "price": 600.0,
                "buying_options": "BEST_OFFER",
                "seller_feedback": 99,
            },
            "insufficient_seller_feedback",
        )


if __name__ == "__main__":
    unittest.main()
