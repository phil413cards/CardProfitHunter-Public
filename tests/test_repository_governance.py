from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PullRequestSafetyTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            ROOT / ".github" / "pull_request_template.md"
        ).read_text(encoding="utf-8")
        cls.normalized = " ".join(cls.source.split())

    def test_template_requires_canonical_verification(self):
        self.assertIn("python scripts/check_tracked_artifacts.py", self.source)
        self.assertIn(
            "PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v",
            self.source,
        )
        self.assertIn("git diff --check", self.source)
        self.assertIn("Python 3.11 and 3.12", self.source)

    def test_template_covers_private_runtime_and_external_side_effects(self):
        for phrase in (
            "No `.env`, credential, token, database, cache, log",
            "eBay tests use mocks",
            "no live marketplace mutation",
            "Database tests use patched temporary paths",
            "local user database",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_template_preserves_financial_and_valuation_safety_review(self):
        for phrase in (
            "money math",
            "identity matching",
            "current sold-comparable",
            "conflict regression tests",
            "expired rows remain",
            "nonfinancial",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)


if __name__ == "__main__":
    unittest.main()
