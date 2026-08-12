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
BATCH_2_VALUATIONS = (
    {
        "keyword": (
            "2024 Panini Prizm Caleb Williams #301 Silver Prizm Rookie "
            "Chicago Bears"
        ),
        "raw_market_value": 170.0,
        "psa9_value": 215.0,
        "psa10_value": 1100.0,
        "source_url": (
            "https://www.sportscardspro.com/game/"
            "football-cards-2024-panini-prizm/caleb-williams-silver-301"
        ),
    },
    {
        "keyword": (
            "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
            "Washington Commanders"
        ),
        "raw_market_value": 115.0,
        "psa9_value": 145.0,
        "psa10_value": 850.0,
        "source_url": (
            "https://www.sportscardspro.com/game/"
            "football-cards-2024-panini-prizm/jayden-daniels-silver-347"
        ),
    },
)


def listing(title: str, price: float, *, condition: str = "Ungraded") -> pd.Series:
    return pd.Series(
        {
            "item_id": "batch-2-valuation-listing",
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


class VerifiedValuationBatch2Tests(unittest.TestCase):
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

    def assert_nonfinancial(self, result, expected_flag: str) -> None:
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

    def test_rows_are_unique_and_bundled_file_is_schema_valid(self):
        validated = validate_valuation_frame(self.values)

        for expected in BATCH_2_VALUATIONS:
            rows = validated.loc[validated["keyword"].eq(expected["keyword"])]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(len(rows), 1)

    def test_rows_have_exact_values_and_structured_provenance(self):
        for expected in BATCH_2_VALUATIONS:
            row = self.valuation_rows(expected["keyword"]).iloc[0]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(row["verification_status"], "verified")
                self.assertEqual(row["verified_at"], "2026-08-09")
                self.assertEqual(row["expires_at"], "2026-09-08")
                self.assertEqual(row["source_url"], expected["source_url"])
                self.assertEqual(int(row["comp_count"]), 30)
                self.assertEqual(
                    float(row["raw_market_value"]),
                    expected["raw_market_value"],
                )
                self.assertEqual(float(row["psa9_value"]), expected["psa9_value"])
                self.assertEqual(
                    float(row["psa10_value"]),
                    expected["psa10_value"],
                )
                self.assertEqual(float(row["gem_rate_estimate"]), 0.0)
                self.assertEqual(float(row["psa9_rate_estimate"]), 0.0)

    def test_expiration_boundaries_are_deterministic(self):
        for expected in BATCH_2_VALUATIONS:
            row = self.valuation_rows(expected["keyword"]).iloc[0]
            with self.subTest(keyword=expected["keyword"]):
                self.assertEqual(
                    valuation_provenance_flags(row, as_of=date(2026, 9, 8)),
                    (),
                )
                self.assertEqual(
                    valuation_provenance_flags(row, as_of=date(2026, 9, 9)),
                    ("expired_valuation",),
                )

    def test_exact_and_safe_near_exact_titles_match(self):
        cases = (
            (
                "2024 Panini Prizm Caleb Williams #301 Silver Prizm Rookie "
                "Chicago Bears Raw",
                BATCH_2_VALUATIONS[0],
            ),
            (
                "2024 Panini Prizm Caleb Williams Silver #301 RC Bears",
                BATCH_2_VALUATIONS[0],
            ),
            (
                "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
                "Washington Commanders Raw",
                BATCH_2_VALUATIONS[1],
            ),
            (
                "2024 Panini Prizm Jayden Daniels #347 True Silver RC "
                "Commanders",
                BATCH_2_VALUATIONS[1],
            ),
        )

        for title, expected in cases:
            result = analyze_listing(
                listing(title, expected["raw_market_value"] * 0.40),
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

    def test_former_half_market_jayden_price_is_now_non_actionable(self):
        expected = BATCH_2_VALUATIONS[1]
        result = analyze_listing(
            listing(
                "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
                "Washington Commanders Raw",
                expected["raw_market_value"] / 2,
            ),
            self.current_rows(expected["keyword"]),
            self.settings,
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.best_path, "NONE")
        self.assertIsNone(result.raw_flip_profit)
        self.assertIsNone(result.raw_flip_roi_pct)
        self.assertIsNone(result.suggested_offer)
        self.assertIn("offer_not_supported", result.flags)

    def test_identity_conflicts_and_slabs_remain_nonfinancial(self):
        cases = (
            (
                "2024 Panini Prizm Caleb Williams #302 Silver Prizm Rookie Bears",
                BATCH_2_VALUATIONS[0],
                "Ungraded",
                "card_identity_conflict_number",
            ),
            (
                "2023 Panini Prizm Caleb Williams #301 Silver Prizm Rookie Bears",
                BATCH_2_VALUATIONS[0],
                "Ungraded",
                "card_identity_conflict_year",
            ),
            (
                "2024 Panini Prizm Caleb Williams #301 Green Prizm Rookie Bears",
                BATCH_2_VALUATIONS[0],
                "Ungraded",
                "card_identity_conflict_parallel",
            ),
            (
                "2024 Panini Select Caleb Williams #301 Silver Prizm Rookie Bears",
                BATCH_2_VALUATIONS[0],
                "Ungraded",
                "card_identity_conflict_set",
            ),
            (
                "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
                "Dallas Cowboys",
                BATCH_2_VALUATIONS[1],
                "Ungraded",
                "card_identity_conflict_modifier",
            ),
            (
                "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
                "Photo Variation Commanders",
                BATCH_2_VALUATIONS[1],
                "Ungraded",
                "card_identity_conflict_variant",
            ),
            (
                "2024 Panini Prizm Jayden Daniels #347 Silver Prizm Rookie "
                "Commanders PSA10",
                BATCH_2_VALUATIONS[1],
                "Graded",
                "graded_or_slabbed",
            ),
            (
                "2024 Panini Prizm Jaxson Daniels #347 Silver Prizm Rookie "
                "Commanders",
                BATCH_2_VALUATIONS[1],
                "Ungraded",
                "insufficient_card_identity",
            ),
        )

        for title, expected, condition, expected_flag in cases:
            result = analyze_listing(
                listing(title, 50.0, condition=condition),
                self.current_rows(expected["keyword"]),
                self.settings,
            )
            with self.subTest(title=title):
                self.assert_nonfinancial(result, expected_flag)

    def test_generic_demonstration_titles_remain_nonfinancial(self):
        cases = (
            "Caleb Williams Prizm Silver RC",
            "Jayden Daniels Prizm Silver RC",
        )

        for keyword in cases:
            rows = self.valuation_rows(keyword)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows.iloc[0]["verification_status"], "demonstration")

            result = analyze_listing(
                listing(f"{keyword} Raw", 10.0),
                self.values,
                self.settings,
            )
            with self.subTest(keyword=keyword):
                self.assertEqual(result.recommended_action, "PASS")
                self.assertEqual(result.best_path, "NONE")
                self.assertIsNone(result.suggested_offer)
                self.assertIsNone(result.raw_market_value)
                self.assertIsNone(result.best_expected_profit)
                self.assertIsNone(result.best_expected_roi_pct)


if __name__ == "__main__":
    unittest.main()
