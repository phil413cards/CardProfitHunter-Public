from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from input_validation import validate_valuation_frame
from profit_engine import analyze_listing
from valuation_safety import valuation_provenance_flags


ROOT = Path(__file__).resolve().parents[1]
EXPANDED_VALUATIONS = (
    {
        "keyword": (
            "2023-24 Panini Prizm Victor Wembanyama #136 Silver Prizm "
            "Rookie Spurs"
        ),
        "raw_market_value": 900.0,
        "psa9_value": 1000.0,
        "psa10_value": 2900.0,
        "source_url": (
            "https://www.sportscardspro.com/game/"
            "basketball-cards-2023-panini-prizm/"
            "victor-wembanyama-silver-136"
        ),
    },
    {
        "keyword": (
            "2018 Topps Chrome Shohei Ohtani #150 Refractor Rookie "
            "Pitching Angels"
        ),
        "raw_market_value": 3000.0,
        "psa9_value": 3200.0,
        "psa10_value": 6400.0,
        "source_url": (
            "https://www.sportscardspro.com/game/"
            "baseball-cards-2018-topps-chrome/"
            "shohei-ohtani-refractor-150"
        ),
    },
    {
        "keyword": "2003-04 Topps Chrome LeBron James #111 Rookie Cavaliers",
        "raw_market_value": 2500.0,
        "psa9_value": 5200.0,
        "psa10_value": 15500.0,
        "source_url": (
            "https://www.sportscardspro.com/game/"
            "basketball-cards-2003-topps-chrome/lebron-james-111"
        ),
    },
)


def listing(title: str, price: float, *, condition: str = "Ungraded") -> pd.Series:
    return pd.Series(
        {
            "item_id": "expanded-valuation-listing",
            "title": title,
            "price": price,
            "shipping": 0.0,
            "currency": "USD",
            "item_url": "",
            "image_url": "",
            "seller_username": "valuation-test",
            "seller_feedback": 1000,
            "seller_feedback_pct": 100.0,
            "buying_options": "FIXED_PRICE",
            "condition": condition,
            "item_end_date": "",
        }
    )


class VerifiedValuationExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")
        cls.settings = json.loads(
            (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
        )

    def valuation_rows(self, keyword: str) -> pd.DataFrame:
        return self.values.loc[self.values["keyword"].eq(keyword)].copy()

    def current_rows(self, keyword: str) -> pd.DataFrame:
        rows = self.valuation_rows(keyword)
        rows.loc[:, "verified_at"] = (date.today() - timedelta(days=1)).isoformat()
        rows.loc[:, "expires_at"] = (date.today() + timedelta(days=30)).isoformat()
        return rows

    def assert_nonfinancial_rejection(self, result, expected_flag: str) -> None:
        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.best_path, "NONE")
        self.assertEqual(result.matched_card, "")
        self.assertIsNone(result.suggested_offer)
        self.assertIsNone(result.raw_market_value)
        self.assertIsNone(result.psa9_value)
        self.assertIsNone(result.psa10_value)
        self.assertIsNone(result.raw_flip_profit)
        self.assertIsNone(result.raw_flip_roi_pct)
        self.assertIsNone(result.psa_expected_profit)
        self.assertIsNone(result.psa_expected_roi_pct)
        self.assertIsNone(result.best_expected_profit)
        self.assertIsNone(result.best_expected_roi_pct)
        self.assertIn(expected_flag, result.flags)

    def test_expanded_rows_are_unique_and_bundled_file_is_schema_valid(self):
        validated = validate_valuation_frame(self.values)

        for expected in EXPANDED_VALUATIONS:
            rows = validated.loc[validated["keyword"].eq(expected["keyword"])]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(len(rows), 1)

    def test_expanded_rows_have_exact_values_and_structured_provenance(self):
        for expected in EXPANDED_VALUATIONS:
            row = self.valuation_rows(expected["keyword"]).iloc[0]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(row["verification_status"], "verified")
                self.assertEqual(row["verified_at"], "2026-08-12")
                self.assertEqual(row["expires_at"], "2026-09-11")
                self.assertEqual(row["source_url"], expected["source_url"])
                self.assertEqual(int(row["comp_count"]), 30)
                self.assertEqual(float(row["raw_market_value"]), expected["raw_market_value"])
                self.assertEqual(float(row["psa9_value"]), expected["psa9_value"])
                self.assertEqual(float(row["psa10_value"]), expected["psa10_value"])
                self.assertEqual(float(row["gem_rate_estimate"]), 0.0)
                self.assertEqual(float(row["psa9_rate_estimate"]), 0.0)

    def test_expanded_expiration_boundaries_are_deterministic(self):
        for expected in EXPANDED_VALUATIONS:
            row = self.valuation_rows(expected["keyword"]).iloc[0]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(
                    valuation_provenance_flags(row, as_of=date(2026, 9, 11)),
                    (),
                )
                self.assertEqual(
                    valuation_provenance_flags(row, as_of=date(2026, 9, 12)),
                    ("expired_valuation",),
                )

    def test_exact_raw_cards_can_produce_financial_recommendations(self):
        for expected in EXPANDED_VALUATIONS:
            result = analyze_listing(
                listing(
                    f'{expected["keyword"]} Raw Sharp',
                    expected["raw_market_value"] / 2,
                ),
                self.current_rows(expected["keyword"]),
                self.settings,
            )
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(result.recommended_action, "BUY_RAW_FLIP")
                self.assertEqual(result.best_path, "RAW_FLIP")
                self.assertEqual(result.matched_card, expected["keyword"])
                self.assertEqual(
                    result.raw_market_value,
                    expected["raw_market_value"],
                )
                self.assertIsNotNone(result.raw_flip_profit)
                self.assertIsNotNone(result.raw_flip_roi_pct)

    def test_audited_benign_title_variations_still_match(self):
        cases = (
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 Silver Prizm RC",
                EXPANDED_VALUATIONS[0],
            ),
            (
                "VICTOR WEMBANYAMA 2023-24 PANINI PRIZM SILVER ROOKIE "
                "(CENTERED) #136 SPURS Q1887",
                EXPANDED_VALUATIONS[0],
            ),
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 RC Rookie "
                "True Silver",
                EXPANDED_VALUATIONS[0],
            ),
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 Silver Prizm "
                "RC San Antonio Spurs",
                EXPANDED_VALUATIONS[0],
            ),
            (
                "2018 Topps Chrome Shohei Ohtani RC Refractor Rookie "
                "#150 Angels",
                EXPANDED_VALUATIONS[1],
            ),
            (
                "2018 Topps Chrome Shohei Ohtani RC Refractor Rookie "
                "#150 Los Angeles Angels",
                EXPANDED_VALUATIONS[1],
            ),
            (
                "2003-04 Topps Chrome - LeBron James #111 (RC)",
                EXPANDED_VALUATIONS[2],
            ),
            (
                "2003-04 Topps Chrome - Cleveland Cavaliers LeBron James "
                "#111 (RC)",
                EXPANDED_VALUATIONS[2],
            ),
        )

        for title, expected in cases:
            result = analyze_listing(
                listing(title, expected["raw_market_value"] / 2),
                self.current_rows(expected["keyword"]),
                self.settings,
            )
            with self.subTest(title=title):
                self.assertEqual(result.recommended_action, "BUY_RAW_FLIP")
                self.assertEqual(result.best_path, "RAW_FLIP")
                self.assertEqual(result.matched_card, expected["keyword"])
                self.assertEqual(
                    result.raw_market_value,
                    expected["raw_market_value"],
                )

    def test_identity_conflicts_and_slabs_remain_nonfinancial(self):
        cases = (
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 Red Prizm Rookie Spurs",
                EXPANDED_VALUATIONS[0]["keyword"],
                "Ungraded",
                "card_identity_conflict_parallel",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150 Sepia Refractor Rookie Pitching Angels",
                EXPANDED_VALUATIONS[1]["keyword"],
                "Ungraded",
                "card_identity_conflict_parallel",
            ),
            (
                "2003-04 Topps Chrome LeBron James #112 Rookie Cavaliers",
                EXPANDED_VALUATIONS[2]["keyword"],
                "Ungraded",
                "card_identity_conflict_number",
            ),
            (
                "2024-25 Panini Prizm Victor Wembanyama #136 Silver Prizm Rookie Spurs",
                EXPANDED_VALUATIONS[0]["keyword"],
                "Ungraded",
                "card_identity_conflict_year",
            ),
            (
                f'{EXPANDED_VALUATIONS[2]["keyword"]} PSA10',
                EXPANDED_VALUATIONS[2]["keyword"],
                "Graded",
                "graded_or_slabbed",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150 Refractor Rookie "
                "Batting Angels",
                EXPANDED_VALUATIONS[1]["keyword"],
                "Ungraded",
                "card_identity_conflict_modifier",
            ),
            (
                "2003-04 Topps Chrome Los Angeles Lakers LeBron James #111 "
                "Rookie",
                EXPANDED_VALUATIONS[2]["keyword"],
                "Ungraded",
                "card_identity_conflict_modifier",
            ),
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 Silver Prizm "
                "Rookie Spurs MysteryFoil",
                EXPANDED_VALUATIONS[0]["keyword"],
                "Ungraded",
                "card_identity_conflict_modifier",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150 Refractor Rookie "
                "Photo Variation Angels",
                EXPANDED_VALUATIONS[1]["keyword"],
                "Ungraded",
                "card_identity_conflict_variant",
            ),
            (
                "2003-04 Topps Chrome Bronny James #111 Rookie Cavaliers",
                EXPANDED_VALUATIONS[2]["keyword"],
                "Ungraded",
                "insufficient_card_identity",
            ),
            (
                "2023-24 Panini Prizm Victor Wembanyama #136 Silver Prizm "
                "Rookie Cleveland",
                EXPANDED_VALUATIONS[0]["keyword"],
                "Ungraded",
                "card_identity_conflict_modifier",
            ),
        )

        for title, keyword, condition, expected_flag in cases:
            result = analyze_listing(
                listing(title, 100.0, condition=condition),
                self.current_rows(keyword),
                self.settings,
            )
            with self.subTest(title=title):
                self.assert_nonfinancial_rejection(result, expected_flag)

    def test_full_bundled_values_report_target_specific_conflicts(self):
        cases = (
            (
                "2003-04 Topps Chrome LeBron James #111 Refractor Rookie "
                "Cavaliers",
                "card_identity_conflict_parallel",
            ),
            (
                "2003-04 Topps Chrome LeBron James #112 Rookie Cavaliers",
                "card_identity_conflict_number",
            ),
            (
                "2023 Panini Prizm Victor Wembanyama #136 Silver Prizm "
                "Rookie Spurs",
                "card_identity_conflict_year",
            ),
        )

        for title, expected_flag in cases:
            result = analyze_listing(
                listing(title, 100.0),
                self.values,
                self.settings,
            )
            with self.subTest(title=title):
                self.assert_nonfinancial_rejection(result, expected_flag)

    def test_bundled_demonstration_rows_remain_nonfinancial(self):
        demonstrations = self.values.loc[
            self.values["verification_status"].eq("demonstration")
        ]
        self.assertFalse(demonstrations.empty)

        for _, row in demonstrations.iterrows():
            result = analyze_listing(
                listing(f'{row["keyword"]} Raw Sharp', 10.0),
                pd.DataFrame([row]),
                self.settings,
            )
            with self.subTest(keyword=row["keyword"]):
                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(result.best_path, "NONE")
                self.assertIsNone(result.suggested_offer)
                self.assertIsNone(result.raw_market_value)
                self.assertIsNone(result.best_expected_profit)
                self.assertIsNone(result.best_expected_roi_pct)


if __name__ == "__main__":
    unittest.main()
