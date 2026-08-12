from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import DAMAGED_CARD, RAW_AUTOGRAPH, classify_listing
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]
BASE_IDENTITY = (
    "2024 Topps Chrome Shohei Ohtani Rookie Auto Gold Refractor #17 3/10"
)

DEFECT_TERMS = (
    "Scratch",
    "Scratched",
    "Print Line",
    "Off Center",
    "OC",
    "Dent",
    "Dimple",
    "Corner Wear",
    "Edge Wear",
    "Soft Corner",
    "Rounded Corners",
    "Corner Ding",
    "Surface Issue",
    "Whitening",
    "Chipping",
    "Scuffed",
    "Peeled",
    "Staining",
    "Creases",
    "Creasing",
    "Faded",
    "Fading",
    "Paper Loss",
)

SAFE_CONDITION_TERMS = (
    "No Scratches",
    "No Visible Scratches",
    "No Print Lines",
    "No Dents",
    "No Dimples",
    "No Whitening",
    "No Damage",
    "No Creases",
    "No Stains",
    "Not Trimmed",
    "Not Altered",
    "Damage Free",
    "Scratch Free",
    "Scratch Resistant Sleeve",
    "Well Centered",
    "Clean Surface",
    "Sharp Corners",
)


class DisclosedConditionDefectSafetyTests(unittest.TestCase):
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

    def test_disclosed_defects_are_hard_nonactionable_classifications(self):
        for term in DEFECT_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, DAMAGED_CARD)
                self.assertEqual(
                    classification.exclusion_reason,
                    "damage_language",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertTrue(classification.damaged)

    def test_condition_only_defects_are_nonactionable(self):
        for condition in ("Ungraded - Print Line", "Ungraded - Corner Wear"):
            with self.subTest(condition=condition):
                classification = classify_listing(BASE_IDENTITY, condition)

                self.assertEqual(classification.listing_class, DAMAGED_CARD)
                self.assertFalse(classification.actionable)
                self.assertTrue(classification.damaged)

    def test_disclosed_defects_are_removed_before_scout_analysis(self):
        for term in DEFECT_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "damage_language",
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

    def test_scout_boundary_rejects_spoofed_defect_metadata(self):
        row = pd.Series({
            "title": f"{BASE_IDENTITY} Print Line",
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

    def test_direct_analysis_vetoes_exact_defect_valuation_keywords(self):
        for term in DEFECT_TERMS:
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
                self.assertIn("damage_language", result.flags.split(";"))

    def test_direct_analysis_vetoes_condition_only_defect_disclosure(self):
        values = self.verified_value.copy()
        title = str(values.iloc[0]["keyword"])
        listing = pd.Series({
            "title": title,
            "price": 25.0,
            "shipping": 0.0,
            "currency": "USD",
            "buying_options": "FIXED_PRICE,BEST_OFFER",
            "condition": "Ungraded - Print Line",
        })

        result = analyze_listing(listing, values, self.settings)

        self.assert_no_financial_fields(result)
        self.assertIn("damage_language", result.flags.split(";"))

    def test_explicit_no_defect_and_safe_condition_words_remain_eligible(self):
        for term in SAFE_CONDITION_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, RAW_AUTOGRAPH)
                self.assertTrue(classification.actionable)
                self.assertFalse(classification.damaged)


if __name__ == "__main__":
    unittest.main()
