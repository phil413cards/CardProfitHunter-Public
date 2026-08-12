from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import BOX_BREAK, RAW_PARALLEL, classify_listing
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]
BASE_IDENTITY = "2024 Topps Chrome Shohei Ohtani Gold Refractor #17 3/10"

BREAK_LISTING_TERMS = (
    "Box Break",
    "Case Break",
    "Group Break",
    "Live Break",
    "Team Break",
    "Player Break",
    "Division Break",
    "Conference Break",
    "Personal Break",
    "Break Spot",
    "Break Slots",
    "Break Entry",
    "Break Filler",
    "Break Credit",
    "Player Spot",
    "Team Slot",
    "Spot In The Case Break",
    "Pick Your Team",
    "Pick Your Player",
    "PYT",
    "Rip And Ship",
    "Rip & Ship",
    "Rip N Ship",
    "Live Rip",
    "Group Rip",
    "Box Opening",
    "Case Opening",
    "Pack Opening",
)

SAFE_CARD_TERMS = (
    "Breakout Insert",
    "Breakaway Prizm",
    "Record Breaking Insert",
    "Unbreakable Insert",
)


class BreakListingSafetyTests(unittest.TestCase):
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

    def test_break_services_are_hard_nonactionable_classifications(self):
        for term in BREAK_LISTING_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, BOX_BREAK)
                self.assertEqual(classification.exclusion_reason, "break_listing")
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_break_services_are_removed_before_scout_analysis(self):
        for term in BREAK_LISTING_TERMS:
            title = f"{BASE_IDENTITY} {term}"
            with self.subTest(term=term):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "break_listing",
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

    def test_scout_boundary_rejects_spoofed_break_metadata(self):
        row = pd.Series({
            "title": f"{BASE_IDENTITY} Pick Your Player",
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

    def test_direct_analysis_vetoes_exact_break_valuation_keywords(self):
        for term in BREAK_LISTING_TERMS:
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
                self.assertIn("break_listing", result.flags.split(";"))

    def test_legitimate_card_names_with_break_stems_remain_eligible(self):
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
