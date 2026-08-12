from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import PICK_YOUR_CARD, RAW_PARALLEL, classify_listing
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]
BASE_IDENTITY = "2024 Topps Chrome Shohei Ohtani Gold Refractor #17 3/10"

CHOICE_LISTING_TERMS = (
    "U Pick",
    "You Pick",
    "You Choose",
    "You Select",
    "Pick Your Card",
    "Pick A Card",
    "Pick One",
    "Choose Your Card",
    "Choose A Card",
    "Choose One",
    "Select Your Card",
    "Select A Card",
    "Select One",
    "Card Of Your Choice",
    "Choice Of Cards",
    "Pick From List",
    "Choose From The Menu",
    "Select From Dropdown",
    "Select From Drop Down",
    "Complete Your Set",
    "Price Per Card",
    "Cards Sold Individually",
    "One Card Per Purchase",
    "One Card Per Order",
    "Each Card Sold Separately",
    "Multiple Cards Available",
)

SAFE_CARD_TERMS = (
    "Pick 2 Card",
    "First Overall Pick Card #1",
    "Draft Picks Insert #1",
    "Photo Variation #1",
    "Choice Black Gold #1",
    "Panini Select #1",
)


class ChoiceListingSafetyTests(unittest.TestCase):
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
        self.assertFalse(result.raw_candidate)
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

    def test_choice_inventory_is_hard_nonactionable(self):
        for term in CHOICE_LISTING_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, PICK_YOUR_CARD)
                self.assertEqual(
                    classification.exclusion_reason,
                    "pick_your_card",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_choice_inventory_is_removed_before_scout_analysis(self):
        for term in CHOICE_LISTING_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "pick your card",
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

    def test_scout_boundary_rejects_spoofed_choice_metadata(self):
        row = pd.Series({
            "title": f"{BASE_IDENTITY} Select From Dropdown",
            "condition": "Ungraded",
            "recommended_action": "PASS",
            "valuation_available": False,
            "listing_actionable": True,
            "grading_candidate": True,
            "listing_listing_class": RAW_PARALLEL,
            "grading_signal_score": 100,
            "parsed_print_run": 10,
            "parsed_rookie": True,
            "parsed_autograph": False,
            "parsed_parallel": "Gold Refractor",
            "parsed_card_number": "17",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_vetoes_exact_choice_valuation_keywords(self):
        for term in CHOICE_LISTING_TERMS:
            title = f"{BASE_IDENTITY} {term}"
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

            with self.subTest(term=term):
                result = analyze_listing(listing, values, self.settings)

                self.assert_no_financial_fields(result)
                self.assertIn("pick_your_card", result.flags.split(";"))

    def test_card_identity_terms_with_pick_select_and_choice_remain_eligible(self):
        for term in SAFE_CARD_TERMS:
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
