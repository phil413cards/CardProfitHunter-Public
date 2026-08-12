from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from card_parser import normalize_text as normalize_card_text
from card_parser import parse_card_identity
from listing_classifier import RAW_SINGLE_CARD, UNKNOWN, classify_listing
from profit_engine import analyze_listing
from scout_engine import enrich_listings, run_scout_engine
from search_relevance import (
    excluded_listing_reason,
    is_relevant_search_result,
    normalize_text as normalize_search_text,
)


def engine_settings() -> dict[str, object]:
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


def verified_values() -> pd.DataFrame:
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


def complete_listing(**overrides: object) -> pd.Series:
    data: dict[str, object] = {
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
    return pd.Series(data, dtype=object)


class MissingTextBoundarySafetyTests(unittest.TestCase):
    def assert_nonfinancial(self, result, expected_flag: str) -> None:
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

    def test_missing_titles_are_safe_across_parser_and_relevance_boundaries(self):
        cases = (
            ("none", None),
            ("nan", float("nan")),
            ("pandas_na", pd.NA),
        )

        for name, value in cases:
            with self.subTest(name=name):
                self.assertEqual(normalize_card_text(value), "")
                self.assertEqual(normalize_search_text(value), "")

                identity = parse_card_identity(value, "Shohei Ohtani")
                self.assertIsNone(identity.year)
                self.assertEqual(identity.manufacturer, "")
                self.assertEqual(identity.product, "")
                self.assertEqual(identity.card_number, "")

                classification = classify_listing(value, "Ungraded")
                self.assertEqual(classification.listing_class, UNKNOWN)
                self.assertFalse(classification.actionable)
                self.assertEqual(classification.exclusion_reason, "missing_title")

                self.assertEqual(
                    excluded_listing_reason(value, "Shohei Ohtani"),
                    "missing_title",
                )
                self.assertFalse(
                    is_relevant_search_result(value, "Shohei Ohtani")
                )

    def test_missing_query_is_safe_and_never_relevant(self):
        title = "Shohei Ohtani Bowman Chrome RC"
        for name, value in (
            ("none", None),
            ("nan", float("nan")),
            ("pandas_na", pd.NA),
        ):
            with self.subTest(name=name):
                identity = parse_card_identity(title, value)
                self.assertEqual(identity.player, "")
                self.assertFalse(is_relevant_search_result(title, value))

    def test_missing_or_malformed_titles_fail_closed_in_direct_analysis(self):
        cases = (
            ("none", None, "missing_title"),
            ("nan", float("nan"), "missing_title"),
            ("pandas_na", pd.NA, "missing_title"),
            ("list", [], "invalid_title"),
            ("dict", {}, "invalid_title"),
            ("number", 413, "invalid_title"),
        )

        for name, value, expected_flag in cases:
            with self.subTest(name=name):
                result = analyze_listing(
                    complete_listing(title=value),
                    verified_values(),
                    engine_settings(),
                )
                self.assert_nonfinancial(result, expected_flag)
                self.assertFalse(result.raw_candidate)

    def test_missing_or_malformed_conditions_fail_closed_in_direct_analysis(self):
        cases = (
            ("none", None, "missing_condition"),
            ("nan", float("nan"), "missing_condition"),
            ("pandas_na", pd.NA, "missing_condition"),
            ("list", [], "invalid_condition"),
            ("dict", {}, "invalid_condition"),
            ("number", 413, "invalid_condition"),
        )

        for name, value, expected_flag in cases:
            with self.subTest(name=name):
                result = analyze_listing(
                    complete_listing(condition=value),
                    verified_values(),
                    engine_settings(),
                )
                self.assert_nonfinancial(result, expected_flag)

    def test_missing_or_malformed_title_and_condition_cannot_become_scouts(self):
        cases = (
            ("missing_title", None, "Ungraded", "missing_title"),
            ("nan_title", float("nan"), "Ungraded", "missing_title"),
            ("pandas_na_title", pd.NA, "Ungraded", "missing_title"),
            ("malformed_title", [], "Ungraded", "invalid_title"),
            (
                "missing_condition",
                "Shohei Ohtani Bowman Chrome RC Raw",
                None,
                "missing_condition",
            ),
            (
                "nan_condition",
                "Shohei Ohtani Bowman Chrome RC Raw",
                float("nan"),
                "missing_condition",
            ),
            (
                "pandas_na_condition",
                "Shohei Ohtani Bowman Chrome RC Raw",
                pd.NA,
                "missing_condition",
            ),
            (
                "malformed_condition",
                "Shohei Ohtani Bowman Chrome RC Raw",
                {},
                "invalid_condition",
            ),
        )

        for name, title, condition, expected_reason in cases:
            with self.subTest(name=name):
                listings = pd.DataFrame(
                    [complete_listing(title=title, condition=condition).to_dict()]
                )
                enriched = enrich_listings(listings, "Shohei Ohtani")
                self.assertFalse(bool(enriched.iloc[0]["listing_actionable"]))
                self.assertEqual(
                    enriched.iloc[0]["listing_exclusion_reason"],
                    expected_reason,
                )

                ranked = run_scout_engine(
                    listings,
                    verified_values(),
                    engine_settings(),
                    "Shohei Ohtani",
                    recommendation_limit=100,
                )
                self.assertTrue(ranked.empty)

    def test_valid_text_behavior_is_unchanged(self):
        title = "Shohei Ohtani Bowman Chrome RC Raw"
        classification = classify_listing(title, "Ungraded")
        self.assertEqual(classification.listing_class, RAW_SINGLE_CARD)
        self.assertTrue(classification.actionable)

        result = analyze_listing(
            complete_listing(),
            verified_values(),
            engine_settings(),
        )
        self.assertIn(
            result.recommended_action,
            {"BUY_RAW_FLIP", "BUY_GRADE_PSA", "OFFER"},
        )
        self.assertEqual(
            result.matched_card,
            "Shohei Ohtani Bowman Chrome RC",
        )


if __name__ == "__main__":
    unittest.main()
