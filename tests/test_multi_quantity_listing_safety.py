from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import (
    MULTI_CARD_LISTING,
    RAW_AUTOGRAPH,
    classify_listing,
)
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]
BASE_IDENTITY = (
    "2024 Topps Chrome Shohei Ohtani Rookie Auto Gold Refractor #17 3/10"
)

MULTI_QUANTITY_TITLES = (
    f"2x {BASE_IDENTITY}",
    "2x 2024 Topps Chrome Shohei Ohtani MVP Card #17",
    f"3 X {BASE_IDENTITY}",
    f"X2 {BASE_IDENTITY}",
    f"{BASE_IDENTITY} Qty 2",
    f"{BASE_IDENTITY} Quantity: 3",
    f"Lot (2) {BASE_IDENTITY}",
    f"Lot of 3 {BASE_IDENTITY}",
    f"Lot x2 {BASE_IDENTITY}",
    f"Pair of {BASE_IDENTITY}",
    f"{BASE_IDENTITY} 2 Copies",
    f"{BASE_IDENTITY} 2 Cards",
    f"{BASE_IDENTITY} 2-Card Lot",
    f"{BASE_IDENTITY} Set of 2 Cards",
    f"{BASE_IDENTITY} Both Cards",
    f"(2) {BASE_IDENTITY}",
    f"Two {BASE_IDENTITY}",
    "Two 2024 Topps Chrome Shohei Ohtani MVP Cards #17",
    f"Three {BASE_IDENTITY}",
    f"Twelve {BASE_IDENTITY}",
    f"Dozen {BASE_IDENTITY}",
    f"Two Shohei Ohtani {BASE_IDENTITY} Cards",
    f"{BASE_IDENTITY} Multiple Cards",
    f"{BASE_IDENTITY} Assorted Cards",
    f"{BASE_IDENTITY} Mixed Card Lot",
    f"{BASE_IDENTITY} Bulk Trading Cards",
    f"{BASE_IDENTITY} Lot of Cards",
    f"{BASE_IDENTITY} Includes 2 Cards",
    f"{BASE_IDENTITY} You Will Receive 2 Cards",
    f"{BASE_IDENTITY} 2-Card Combo",
    f"{BASE_IDENTITY} Choose Any 2 Cards",
)

SAFE_SINGLE_CARD_TITLES = (
    "2024 Topps Chrome Shohei Ohtani Rookie Auto #2 X-Fractor Card",
    "2X MVP Shohei Ohtani 2024 Topps Chrome Rookie Card #17",
    "2X World Series Champion Shohei Ohtani Topps Chrome Card #17",
    "2024 Topps Chrome Shohei Ohtani #17 2nd Year Card",
    "2024 Topps Chrome Shohei Ohtani #17 One of One 1/1",
    "2024 Topps Chrome Shohei Ohtani Dual Auto #17",
    "2024 Topps Chrome Shohei Ohtani Pair of Aces Insert Card #17",
    "2024 Topps Chrome Shohei Ohtani #17 Both Sides Pictured",
    "2024 Topps Chrome Shohei Ohtani #17 Single Copy",
    "2024 Panini Select Shohei Ohtani Pick 2 Card",
    "2024 Panini Select Shohei Ohtani #2 Card",
)


class MultiQuantityListingSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(
            (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
        )
        all_values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")
        cls.verified_value = all_values.loc[
            all_values["verification_status"].eq("verified")
        ].iloc[[0]].copy()

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

    def test_multi_quantity_titles_are_hard_nonactionable_classifications(self):
        for title in MULTI_QUANTITY_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(
                    classification.listing_class,
                    MULTI_CARD_LISTING,
                )
                self.assertEqual(
                    classification.exclusion_reason,
                    "multi_card_quantity",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_multi_quantity_titles_are_removed_before_scout_analysis(self):
        for title in MULTI_QUANTITY_TITLES:
            with self.subTest(title=title):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "multi_card_quantity",
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

    def test_scout_boundary_rejects_spoofed_multi_quantity_metadata(self):
        row = pd.Series({
            "title": f"2x {BASE_IDENTITY}",
            "condition": "Ungraded",
            "recommended_action": "PASS",
            "valuation_available": False,
            "listing_actionable": True,
            "grading_candidate": True,
            "listing_listing_class": RAW_AUTOGRAPH,
            "grading_signal_score": 100,
            "parsed_print_run": 10,
            "parsed_rookie": True,
            "parsed_autograph": True,
            "parsed_parallel": "Gold Refractor",
            "parsed_card_number": "17",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_vetoes_exact_multi_quantity_valuation_keywords(self):
        for title in MULTI_QUANTITY_TITLES:
            values = self.verified_value.copy()
            values.loc[values.index[0], "keyword"] = title
            listing = pd.Series({
                "title": title,
                "price": 25.0,
                "shipping": 0.0,
                "currency": "USD",
                "buying_options": "FIXED_PRICE,BEST_OFFER",
                "condition": "Ungraded",
            })

            with self.subTest(title=title):
                result = analyze_listing(listing, values, self.settings)

                self.assert_no_financial_fields(result)
                self.assertIn("multi_card_listing", result.flags.split(";"))

    def test_single_card_number_and_achievement_phrases_remain_eligible(self):
        for title in SAFE_SINGLE_CARD_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertTrue(classification.actionable)
                self.assertIsNone(
                    excluded_listing_reason(title, "Shohei Ohtani")
                )


if __name__ == "__main__":
    unittest.main()
