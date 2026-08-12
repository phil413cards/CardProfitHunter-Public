from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SETTINGS_PATH = ROOT / "config" / "settings.json"

RISK_SETTING_KEYS = (
    "purchase_tax_pct",
    "promoted_listing_fee_pct",
    "return_defect_allowance_pct",
    "grading_loss_risk_pct",
)


class ProfitModelWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_source = APP_PATH.read_text(encoding="utf-8")
        cls.settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    def test_app_exposes_every_required_risk_setting_without_import(self):
        self.assertNotIn("import app", self.app_source)
        for key in RISK_SETTING_KEYS:
            with self.subTest(key=key):
                self.assertIn(f'("{key}",', self.app_source)

    def test_controlled_demo_defaults_are_explicit_and_nonzero(self):
        expected = {
            "purchase_tax_pct": 0.10,
            "promoted_listing_fee_pct": 0.05,
            "return_defect_allowance_pct": 0.05,
            "grading_loss_risk_pct": 0.01,
        }
        self.assertEqual(
            {key: self.settings[key] for key in RISK_SETTING_KEYS},
            expected,
        )

    def test_ui_explains_decimal_rate_units(self):
        self.assertIn("0.10 means 10%", self.app_source)
        self.assertIn("actual tax and selling history", self.app_source)


if __name__ == "__main__":
    unittest.main()
