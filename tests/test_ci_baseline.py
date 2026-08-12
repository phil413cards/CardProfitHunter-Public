from __future__ import annotations

from pathlib import Path
import unittest

from scripts.check_tracked_artifacts import (
    find_forbidden_tracked_paths,
    is_forbidden_tracked_path,
    read_tracked_paths,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"


class TrackedArtifactGuardTests(unittest.TestCase):
    def test_private_runtime_paths_are_rejected(self):
        paths = (
            ".env",
            ".env.production",
            "data/card_profit_hunter.db",
            "data/history.sqlite",
            "data/history.sqlite3",
            ".cache/ebay_token.json",
            "output/results.csv",
            "logs/application.log",
            ".venv/bin/python",
            "venv/bin/python",
            "env/bin/python",
            "src/__pycache__/module.pyc",
            ".pytest_cache/state",
            ".mypy_cache/state",
            ".ruff_cache/state",
            ".coverage",
            "htmlcov/index.html",
            "application.log",
            "token_cache.json",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(is_forbidden_tracked_path(path))

    def test_trackable_source_and_example_paths_are_allowed(self):
        paths = (
            ".env.example",
            "README.md",
            "database.py",
            "sample_data/card_values.csv",
            "tests/test_database.py",
            "docs/VALUATION_RENEWAL.md",
            "config/settings.json",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(is_forbidden_tracked_path(path))

    def test_forbidden_paths_are_sorted_deterministically(self):
        self.assertEqual(
            find_forbidden_tracked_paths(
                ["output/z.csv", "README.md", ".env", "logs/a.log"]
            ),
            (".env", "logs/a.log", "output/z.csv"),
        )

    def test_current_repository_has_no_tracked_private_artifacts(self):
        self.assertEqual(find_forbidden_tracked_paths(read_tracked_paths()), ())


class PythonWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_supported_python_versions_and_canonical_tests_are_configured(self):
        self.assertIn('- "3.11"', self.source)
        self.assertIn('- "3.12"', self.source)
        self.assertIn(
            "python -B -m unittest discover -s tests -v",
            self.source,
        )
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', self.source)

    def test_actions_are_commit_pinned_and_permissions_are_read_only(self):
        self.assertIn(
            "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
            self.source,
        )
        self.assertIn(
            "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
            self.source,
        )
        self.assertNotIn("actions/checkout@v", self.source)
        self.assertNotIn("actions/setup-python@v", self.source)
        self.assertIn("permissions:\n  contents: read", self.source)

    def test_workflow_runs_privacy_guard_without_secrets(self):
        self.assertIn("python scripts/check_tracked_artifacts.py", self.source)
        self.assertNotIn("secrets.", self.source)
        self.assertNotIn("EBAY_CLIENT", self.source)
        self.assertNotIn("EBAY_ENVIRONMENT", self.source)

    def test_workflow_rejects_blocking_valuation_freshness_issues(self):
        self.assertIn(
            "python scripts/audit_valuations.py --fail-on-blocking",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
