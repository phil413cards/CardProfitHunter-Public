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
PILOT_KEYWORD = (
    "2018 Topps Chrome Shohei Ohtani #150 Rookie White Jersey Los Angeles Angels"
)


def listing(
    title: str,
    *,
    price: float = 400.0,
    condition: str = "Ungraded",
) -> pd.Series:
    return pd.Series(
        {
            "item_id": "pilot-listing",
            "title": title,
            "price": price,
            "shipping": 0.0,
            "currency": "USD",
            "item_url": "",
            "image_url": "",
            "seller_username": "pilot",
            "seller_feedback": 1000,
            "seller_feedback_pct": 100.0,
            "buying_options": "FIXED_PRICE",
            "condition": condition,
            "item_end_date": "",
        }
    )


class VerifiedValuationPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.values = pd.read_csv(ROOT / "sample_data" / "card_values.csv")
        cls.pilot_values = cls.values.loc[
            cls.values["keyword"].eq(PILOT_KEYWORD)
        ].copy()
        cls.settings = json.loads(
            (ROOT / "config" / "settings.json").read_text(encoding="utf-8")
        )

    def test_bundled_valuation_file_remains_schema_valid(self):
        validated = validate_valuation_frame(self.values)
        self.assertIn(PILOT_KEYWORD, set(validated["keyword"]))

    def test_pilot_valuation_has_structured_provenance(self):
        pilot = self.pilot_values.iloc[0]

        self.assertEqual(pilot["verification_status"], "verified")
        self.assertEqual(pilot["verified_at"], "2026-08-09")
        self.assertEqual(pilot["expires_at"], "2026-09-08")
        self.assertTrue(str(pilot["source_url"]).startswith("https://"))
        self.assertGreater(int(pilot["comp_count"]), 0)

    def test_pilot_expiration_boundary_is_deterministic(self):
        pilot = self.pilot_values.iloc[0]

        self.assertEqual(
            valuation_provenance_flags(pilot, as_of=date(2026, 9, 8)),
            (),
        )
        self.assertEqual(
            valuation_provenance_flags(pilot, as_of=date(2026, 9, 9)),
            ("expired_valuation",),
        )

    def test_exact_raw_pilot_can_produce_a_financial_recommendation(self):
        current_values = self.values.copy()
        pilot_mask = current_values["keyword"].eq(PILOT_KEYWORD)
        current_values.loc[pilot_mask, "verified_at"] = (
            date.today() - timedelta(days=1)
        ).isoformat()
        current_values.loc[pilot_mask, "expires_at"] = (
            date.today() + timedelta(days=30)
        ).isoformat()
        result = analyze_listing(
            listing(f"{PILOT_KEYWORD} Raw Sharp", price=300.0),
            current_values,
            self.settings,
        )

        self.assertEqual(result.recommended_action, "BUY_RAW_FLIP")
        self.assertEqual(result.best_path, "RAW_FLIP")
        self.assertEqual(result.matched_card, PILOT_KEYWORD)
        self.assertEqual(result.raw_market_value, 650.0)
        self.assertIsNotNone(result.raw_flip_profit)
        self.assertIsNotNone(result.raw_flip_roi_pct)

    def test_previous_pilot_price_is_now_non_actionable(self):
        current_values = self.values.copy()
        pilot_mask = current_values["keyword"].eq(PILOT_KEYWORD)
        current_values.loc[pilot_mask, "verified_at"] = (
            date.today() - timedelta(days=1)
        ).isoformat()
        current_values.loc[pilot_mask, "expires_at"] = (
            date.today() + timedelta(days=30)
        ).isoformat()
        result = analyze_listing(
            listing(f"{PILOT_KEYWORD} Raw Sharp"),
            current_values,
            self.settings,
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.best_path, "NONE")
        self.assertIsNone(result.raw_flip_profit)
        self.assertIsNone(result.raw_flip_roi_pct)
        self.assertIsNone(result.suggested_offer)
        self.assertIn("offer_not_supported", result.flags)

    def test_slab_version_remains_non_actionable(self):
        result = analyze_listing(
            listing(f"{PILOT_KEYWORD} PSA10", condition="Graded"),
            self.values,
            self.settings,
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.matched_card, "")
        self.assertIsNone(result.raw_market_value)
        self.assertIsNone(result.best_expected_profit)
        self.assertIn("graded_or_slabbed", result.flags)

    def test_conflicting_parallel_remains_non_actionable(self):
        result = analyze_listing(
            listing(f"{PILOT_KEYWORD} Sepia"),
            self.pilot_values,
            self.settings,
        )

        self.assertEqual(result.recommended_action, "PASS")
        self.assertEqual(result.matched_card, "")
        self.assertIsNone(result.raw_market_value)
        self.assertIsNone(result.best_expected_profit)
        self.assertIn("card_identity_conflict_parallel", result.flags)


if __name__ == "__main__":
    unittest.main()
