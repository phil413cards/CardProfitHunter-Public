from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from card_parser import parse_card_identity
from listing_classifier import GRADED_CARD, RAW_SINGLE_CARD, classify_listing
from profit_engine import analyze_listing
from recommendation_engine import is_unverified_scout_candidate
from scout_engine import run_scout_engine


ROOT = Path(__file__).resolve().parents[1]
BASE_IDENTITY = "2018 Topps Chrome Shohei Ohtani Rookie Card #150"

GRADED_LABELS = (
    ("HGA10", "HGA", 10.0),
    ("HGA-10", "HGA", 10.0),
    ("CSG 10", "CSG", 10.0),
    ("GMA 10", "GMA", 10.0),
    ("ISA 10", "ISA", 10.0),
    ("KSA 10", "KSA", 10.0),
    ("AGS 10", "AGS", 10.0),
    ("MNT9.5", "MNT", 9.5),
    ("MNT 9.5", "MNT", 9.5),
    ("FCG 10", "FCG", 10.0),
    ("BVG 9.5", "BVG", 9.5),
    ("BCCG 10", "BCCG", 10.0),
    ("Beckett 9.5", "BECKETT", 9.5),
    ("Arena Club 10", "ARENA CLUB", 10.0),
    ("Rare Edition 10", "RARE EDITION", 10.0),
    ("Degree Grading 10", "DEGREE GRADING", 10.0),
)

GRADED_DESCRIPTOR_TITLES = (
    f"{BASE_IDENTITY} Encapsulated",
    f"{BASE_IDENTITY} Professionally Graded",
    f"{BASE_IDENTITY} Slabbed",
    f"{BASE_IDENTITY} Mint 10",
)

SAFE_RAW_TITLES = (
    "2003 Topps Chrome Josh Beckett Rookie Card #200",
    "2024 Panini Certified Shohei Ohtani Autograph Card #17",
    "2024 Topps Chrome Shohei Ohtani Certified Autograph Card #17",
    "2024 Topps Chrome Shohei Ohtani HGA Insert Card #17",
    "2024 Topps Chrome Shohei Ohtani 10th Anniversary Card #17",
)


class ExtendedGraderSafetyTests(unittest.TestCase):
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

    def test_extended_grader_labels_are_graded_and_parsed(self):
        for label, expected_grader, expected_grade in GRADED_LABELS:
            title = f"{BASE_IDENTITY} {label}"
            with self.subTest(label=label):
                classification = classify_listing(title, "Ungraded")
                identity = parse_card_identity(title, "Shohei Ohtani")

                self.assertEqual(classification.listing_class, GRADED_CARD)
                self.assertTrue(classification.graded)
                self.assertFalse(classification.actionable)
                self.assertEqual(identity.grader, expected_grader)
                self.assertEqual(identity.grade, expected_grade)

    def test_graded_descriptors_are_nonactionable(self):
        for title in GRADED_DESCRIPTOR_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertEqual(classification.listing_class, GRADED_CARD)
                self.assertTrue(classification.graded)
                self.assertFalse(classification.actionable)

    def test_extended_graders_are_removed_before_scout_ranking(self):
        for label, _, _ in GRADED_LABELS:
            title = f"{BASE_IDENTITY} {label}"
            with self.subTest(label=label):
                results = run_scout_engine(
                    pd.DataFrame([{"title": title, "condition": "Ungraded"}]),
                    pd.DataFrame(),
                    {},
                    "Shohei Ohtani",
                    recommendation_limit=10,
                    minimum_scout_score=25,
                )
                self.assertTrue(results.empty)

    def test_scout_boundary_rejects_spoofed_extended_grader_metadata(self):
        row = pd.Series({
            "title": f"{BASE_IDENTITY} MNT 9.5",
            "condition": "Ungraded",
            "recommended_action": "PASS",
            "valuation_available": False,
            "listing_actionable": True,
            "grading_candidate": True,
            "listing_listing_class": RAW_SINGLE_CARD,
            "grading_signal_score": 100,
            "parsed_print_run": None,
            "parsed_rookie": True,
            "parsed_autograph": False,
            "parsed_parallel": "",
            "parsed_card_number": "150",
            "seller_feedback_pct": 100,
        })

        self.assertFalse(is_unverified_scout_candidate(row, 25))

    def test_direct_analysis_vetoes_exact_extended_grader_valuation_keywords(self):
        for label, _, _ in GRADED_LABELS:
            title = f"{BASE_IDENTITY} {label}"
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

            with self.subTest(label=label):
                result = analyze_listing(listing, values, self.settings)

                self.assert_no_financial_fields(result)
                self.assertIn("graded_or_slabbed", result.flags.split(";"))

    def test_graded_condition_descriptors_fail_closed_without_title_labels(self):
        for condition in ("Graded", "Slabbed", "Professionally Graded", "Certified"):
            listing = pd.Series({
                "title": BASE_IDENTITY,
                "price": 25.0,
                "shipping": 0.0,
                "currency": "USD",
                "buying_options": "FIXED_PRICE,BEST_OFFER",
                "condition": condition,
            })

            with self.subTest(condition=condition):
                result = analyze_listing(
                    listing,
                    self.verified_value,
                    self.settings,
                )
                self.assert_no_financial_fields(result)
                self.assertIn("graded_or_slabbed", result.flags.split(";"))

    def test_raw_card_and_product_words_remain_actionable(self):
        for title in SAFE_RAW_TITLES:
            with self.subTest(title=title):
                classification = classify_listing(title, "Ungraded")

                self.assertTrue(classification.actionable)
                self.assertFalse(classification.graded)


if __name__ == "__main__":
    unittest.main()
