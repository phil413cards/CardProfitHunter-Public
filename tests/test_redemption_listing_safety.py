from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import REDEMPTION_LISTING, classify_listing
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]

REDEMPTION_TITLES = (
    "2024 Panini Prizm Victor Wembanyama Rookie Auto Redemption Card /25",
    "2024 Topps Chrome Shohei Ohtani Autograph Redemption Code Card",
    "Panini Rewards Points 600 Rookie Card",
    "Panini Wild Card Points 1500 Redemption",
    "Topps Home Run Challenge Code Card Shohei Ohtani",
    "Panini 900 Points Card",
    "Topps Unused Code Shohei Ohtani Rookie Card",
    "Panini QR Code Victor Wembanyama Rookie Card",
)

DIRECT_ANALYSIS_BLOCKED_TERMS = (
    "Redemption Card",
    "Reward Points",
    "Panini Points",
    "Wild Card Points",
    "Points Card",
    "Code Card",
    "Digital Code",
    "Home Run Challenge",
    "Unused Code",
    "Scratch Code",
    "Scratched Code",
    "QR Code",
)


class RedemptionListingSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(
            (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
        )
        cls.card_values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")

    def test_redemption_and_code_products_are_nonactionable(self):
        for title in REDEMPTION_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(
                    classification.listing_class,
                    REDEMPTION_LISTING,
                )
                self.assertEqual(
                    classification.exclusion_reason,
                    "redemption_or_code_listing",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)
                self.assertFalse(classification.single_card)

    def test_redemption_and_code_products_are_removed_before_analysis(self):
        for title in REDEMPTION_TITLES:
            with self.subTest(title=title):
                self.assertEqual(
                    excluded_listing_reason(title, "Shohei Ohtani"),
                    "redemption_or_code_listing",
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

    def test_scout_boundary_rejects_spoofed_redemption_metadata(self):
        for title in REDEMPTION_TITLES:
            with self.subTest(title=title):
                row = pd.Series({
                    "title": title,
                    "condition": "Ungraded",
                    "recommended_action": "PASS",
                    "valuation_available": False,
                    "listing_actionable": True,
                    "grading_candidate": True,
                    "listing_listing_class": "RAW_AUTOGRAPH",
                    "grading_signal_score": 100,
                    "parsed_print_run": 25,
                    "parsed_rookie": True,
                    "parsed_autograph": True,
                    "parsed_parallel": "Gold",
                    "parsed_card_number": "1",
                    "seller_feedback_pct": 100,
                })

                self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_blocks_redemption_before_valuation_attachment(self):
        keyword = self.card_values.loc[
            self.card_values["verification_status"].eq("verified"),
            "keyword",
        ].iloc[0]
        for blocked_term in DIRECT_ANALYSIS_BLOCKED_TERMS:
            with self.subTest(blocked_term=blocked_term):
                listing = pd.Series({
                    "title": f"{keyword} {blocked_term}",
                    "price": 10.0,
                    "shipping": 0.0,
                    "currency": "USD",
                    "buying_options": "FIXED_PRICE,BEST_OFFER",
                    "condition": "Ungraded",
                })

                result = analyze_listing(
                    listing,
                    self.card_values,
                    self.settings,
                )

                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(result.matched_card, "")
                self.assertEqual(result.best_path, "NONE")
                self.assertIsNone(result.suggested_offer)
                self.assertIsNone(result.best_expected_profit)
                self.assertIsNone(result.best_expected_roi_pct)
                self.assertIsNone(result.raw_market_value)
                self.assertIn("bad_listing_language", result.flags)


if __name__ == "__main__":
    unittest.main()
