from __future__ import annotations

import unittest
from datetime import date, timedelta

import pandas as pd

from listing_classifier import (
    NON_ACTUAL_OR_PRESALE,
    RAW_PARALLEL,
    classify_listing,
)
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


BASE_IDENTITY = "2018 Topps Chrome Shohei Ohtani #150 Refractor"

UNSAFE_TERMS = (
    "Presale",
    "Pre-Sale",
    "Pre Order",
    "Preorder",
    "Not In Hand",
    "Ships When Received",
    "Ships Upon Release",
    "Not Yet Released",
    "Stock Photo",
    "Stock Image",
    "Representative Image",
    "Example Picture",
    "Image Not Of Actual Card",
    "Image Is Not Of Actual Card",
    "Photo Is Representative",
    "Actual Card Not Pictured",
    "Photo May Vary",
)

SAFE_TERMS = (
    "In Hand",
    "Ready To Ship",
    "Actual Card Pictured",
    "Image Variation",
    "Photo Variation",
    "Pack Fresh",
)


def settings() -> dict:
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


def verified_value(keyword: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "keyword": keyword,
        "raw_market_value": 350.0,
        "psa9_value": 550.0,
        "psa10_value": 1100.0,
        "gem_rate_estimate": 0.55,
        "psa9_rate_estimate": 0.35,
        "verification_status": "verified",
        "verified_at": (date.today() - timedelta(days=1)).isoformat(),
        "expires_at": (date.today() + timedelta(days=30)).isoformat(),
        "source_url": "https://example.com/verified-comps",
        "comp_count": 10,
        "notes": "Verified comps",
    }])


def listing(title: str) -> pd.Series:
    return pd.Series({
        "title": title,
        "price": 25.0,
        "shipping": 0.0,
        "currency": "USD",
        "buying_options": "FIXED_PRICE,BEST_OFFER",
        "condition": "Ungraded",
    })


class PresaleNonactualListingSafetyTests(unittest.TestCase):
    def assert_no_financial_fields(self, result) -> None:
        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.matched_card, "")
        self.assertEqual(result.best_path, "NONE")
        for field in (
            "suggested_offer",
            "best_expected_profit",
            "best_expected_roi_pct",
            "raw_flip_profit",
            "raw_flip_roi_pct",
            "psa_expected_profit",
            "psa_expected_roi_pct",
            "max_buy_price_raw_flip",
            "max_buy_price_psa_flip",
            "raw_market_value",
            "psa9_value",
            "psa10_value",
        ):
            self.assertIsNone(getattr(result, field), field)

    def test_unsafe_fulfillment_and_nonactual_images_are_nonactionable(self):
        for term in UNSAFE_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(
                    classification.listing_class,
                    NON_ACTUAL_OR_PRESALE,
                )
                self.assertEqual(
                    classification.exclusion_reason,
                    "presale_or_non_actual_item",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)

    def test_unsafe_titles_are_removed_before_scout_analysis(self):
        for term in UNSAFE_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "presale_or_non_actual_item",
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

    def test_scout_boundary_rejects_spoofed_actionable_metadata(self):
        row = pd.Series({
            "title": f"{BASE_IDENTITY} Stock Photo",
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
            "parsed_card_number": "150",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_vetoes_even_an_exact_unsafe_valuation_keyword(self):
        for term in UNSAFE_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                result = analyze_listing(
                    listing(title),
                    verified_value(title),
                    settings(),
                )

                self.assert_no_financial_fields(result)
                self.assertIn(
                    "presale_or_non_actual_item",
                    result.flags.split(";"),
                )

    def test_safe_fulfillment_and_variation_wording_remains_eligible(self):
        for term in SAFE_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, RAW_PARALLEL)
                self.assertTrue(classification.actionable)
                self.assertIsNone(
                    excluded_listing_reason(title, "Shohei Ohtani")
                )


if __name__ == "__main__":
    unittest.main()
