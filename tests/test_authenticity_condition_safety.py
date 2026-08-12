from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from listing_classifier import (
    DAMAGED_CARD,
    RAW_PARALLEL,
    REPRINT_CUSTOM,
    classify_listing,
)
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine
from search_relevance import excluded_listing_reason, is_relevant_search_result


ROOT = Path(__file__).resolve().parents[1]

ADDITIONAL_UNAUTHENTIC_TERMS = (
    "Unofficial",
    "Not Licensed",
    "Non-Licensed",
    "Fan Made",
    "Fanmade",
    "Handmade",
    "Hand Made",
    "ORICA",
    "Parody",
    "AI Generated",
    "AI-Generated",
    "Artificial Intelligence Generated",
    "Concept",
    "Aftermarket",
)

ADDITIONAL_DIRECT_BLOCKED_TERMS = (
    "Unofficial",
    "Not Licensed",
    "Non-Licensed",
    "Fan Made",
    "Fanmade",
    "Handmade",
    "Hand Made",
    "ORICA",
    "Parody Card",
    "AI Generated Card",
    "AI-Generated Card",
    "Artificial Intelligence Generated Card",
    "Concept Card",
    "Aftermarket Card",
)

UNAUTHENTIC_TITLES = (
    "2024 Topps Chrome Shohei Ohtani Custom Refractor Card",
    "Topps Chrome Shohei Ohtani Replica Rookie Card",
    "Unlicensed Panini Prizm Shohei Ohtani Fan Art Refractor",
    "Shohei Ohtani ACEO Topps Chrome Rookie Card",
    "Topps Chrome Shohei Ohtani Homemade Novelty Card",
    "Topps Chrome Shohei Ohtani Repro Rookie Card",
    "Topps Chrome Shohei Ohtani RP Rookie Card",
    "Topps Chrome Shohei Ohtani Counterfeit Rookie Card",
    "Topps Chrome Shohei Ohtani Unauthorized Bootleg Card",
) + tuple(
    f"2024 Topps Chrome Shohei Ohtani {term} Card"
    for term in ADDITIONAL_UNAUTHENTIC_TERMS
)

ALTERED_TITLES = (
    "Topps Chrome Shohei Ohtani Trimmed Refractor Rookie Card",
    "Topps Chrome Shohei Ohtani Evidence of Trimming Rookie Card",
    "Topps Chrome Shohei Ohtani Altered Rookie Card",
    "Topps Chrome Shohei Ohtani Restored Rookie Card",
    "Topps Chrome Shohei Ohtani Color Added Rookie Card",
    "Topps Chrome Shohei Ohtani Minimum Size Requirement Rookie Card",
)

DIRECT_BLOCKED_TERMS = (
    "Custom",
    "Replica",
    "Reproduction",
    "Repro",
    "Unlicensed",
    "Unauthorized",
    "Fan Art",
    "ACEO",
    "Novelty",
    "Homemade",
    "Counterfeit",
    "Fake",
    "Bootleg",
    "Trimmed",
    "Trimming",
    "Altered",
    "Restored",
    "Color Added",
    "Evidence of Trimming",
    "Minimum Size Requirement",
) + ADDITIONAL_DIRECT_BLOCKED_TERMS


class AuthenticityConditionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(
            (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
        )
        cls.card_values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")

    def test_custom_and_counterfeit_titles_are_nonactionable(self):
        for title in UNAUTHENTIC_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, REPRINT_CUSTOM)
                self.assertEqual(
                    classification.exclusion_reason,
                    "reprint_or_custom",
                )
                self.assertFalse(classification.actionable)
                self.assertFalse(classification.raw)

    def test_altered_titles_are_nonactionable(self):
        for title in ALTERED_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, DAMAGED_CARD)
                self.assertEqual(classification.exclusion_reason, "damage_language")
                self.assertFalse(classification.actionable)
                self.assertTrue(classification.damaged)

    def test_unsafe_titles_are_removed_before_scout_analysis(self):
        for title in UNAUTHENTIC_TITLES + ALTERED_TITLES:
            with self.subTest(title=title):
                reason = excluded_listing_reason(title, "Shohei Ohtani")
                self.assertIn(reason, {"reprint_or_custom", "damage_language"})
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

    def test_scout_boundary_rejects_spoofed_unsafe_metadata(self):
        for title in UNAUTHENTIC_TITLES + ALTERED_TITLES:
            with self.subTest(title=title):
                row = pd.Series({
                    "title": title,
                    "condition": "Ungraded",
                    "recommended_action": "PASS",
                    "valuation_available": False,
                    "listing_actionable": True,
                    "grading_candidate": True,
                    "listing_listing_class": "RAW_PARALLEL",
                    "grading_signal_score": 100,
                    "parsed_print_run": 25,
                    "parsed_rookie": True,
                    "parsed_autograph": False,
                    "parsed_parallel": "Refractor",
                    "parsed_card_number": "1",
                    "seller_feedback_pct": 100,
                })

                self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_blocks_unsafe_terms_before_valuation(self):
        keyword = self.card_values.loc[
            self.card_values["verification_status"].eq("verified"),
            "keyword",
        ].iloc[0]

        for blocked_term in DIRECT_BLOCKED_TERMS:
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

    def test_exact_unofficial_valuation_keywords_remain_nonfinancial(self):
        verified = self.card_values.loc[
            self.card_values["verification_status"].eq("verified")
        ].iloc[[0]].copy()

        for term in ADDITIONAL_UNAUTHENTIC_TERMS:
            title = f"2024 Topps Chrome Shohei Ohtani {term} Card #17"
            values = verified.copy()
            values.loc[values.index[0], "keyword"] = title
            listing = pd.Series({
                "title": title,
                "price": 10.0,
                "shipping": 0.0,
                "currency": "USD",
                "buying_options": "FIXED_PRICE,BEST_OFFER",
                "condition": "Ungraded",
            })

            with self.subTest(term=term):
                result = analyze_listing(listing, values, self.settings)

                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(result.matched_card, "")
                self.assertEqual(result.best_path, "NONE")
                self.assertFalse(result.raw_candidate)
                self.assertIsNone(result.suggested_offer)
                self.assertIsNone(result.best_expected_profit)
                self.assertIsNone(result.best_expected_roi_pct)
                self.assertIsNone(result.raw_market_value)
                self.assertIn("reprint_or_custom", result.flags.split(";"))

    def test_legitimate_variation_and_relic_titles_remain_actionable(self):
        titles = (
            "2024 Topps Chrome Shohei Ohtani Image Variation Refractor Card",
            "2024 Topps Chrome Shohei Ohtani Bat Relic Refractor Card",
            "2024 Topps Chrome Shohei Ohtani Mini Refractor Card",
            "2024 Topps Chrome Shohei Ohtani Officially Licensed Refractor Card #1",
            "2024 Topps Chrome Shohei Ohtani Fanatics Exclusive Refractor Card #1",
            "2024 Topps Chrome Shohei Ohtani Hand Numbered Card #1",
            "2024 Topps Chrome Shohei Ohtani Artist Proof Refractor Card #1",
            "2024 Topps Chrome Shohei Ohtani Fantasy Favorites Refractor Insert #1",
        )

        for title in titles:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, RAW_PARALLEL)
                self.assertTrue(classification.actionable)
                self.assertTrue(classification.single_card)


if __name__ == "__main__":
    unittest.main()
