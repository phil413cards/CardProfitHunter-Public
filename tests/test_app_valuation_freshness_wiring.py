from __future__ import annotations

import ast
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppValuationFreshnessWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_app_displays_computed_freshness_without_importing_app(self):
        self.assertIn("build_valuation_renewal_report", self.source)
        self.assertIn("summarize_valuation_renewal", self.source)
        self.assertIn('editor_values["freshness_status"]', self.source)
        self.assertIn('disabled=["freshness_status"]', self.source)

    def test_app_warns_when_verified_valuations_are_due_soon(self):
        self.assertIn('renewal_summary["due_soon"]', self.source)
        self.assertIn("expire within 30 days", self.source)
        self.assertIn("current exact-card sold comparables", self.source)

    def test_computed_status_is_removed_before_validation_and_persistence(self):
        self.assertIn(
            'drop(columns=["freshness_status"], errors="ignore")',
            self.source,
        )

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())


if __name__ == "__main__":
    unittest.main()
