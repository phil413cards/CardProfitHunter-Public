from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


class AppReleaseMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_PATH.read_text(encoding="utf-8")

    def test_app_is_inspected_without_importing_it(self) -> None:
        self.assertNotIn("import app", self.source)

    def test_visible_version_comes_from_version_file(self) -> None:
        self.assertIn("APPLICATION_VERSION = read_application_version()", self.source)
        self.assertIn('page_title=f"CardProfitHunter {APPLICATION_VERSION}"', self.source)
        self.assertIn('st.title(f"CardProfitHunter {APPLICATION_VERSION}")', self.source)
        self.assertNotIn("Card Profit Hunter V5.1", self.source)

    def test_setup_does_not_overwrite_existing_environment_file(self) -> None:
        self.assertIn("test -f .env || cp .env.example .env", self.source)
        self.assertNotIn("\ncp .env.example .env\n", self.source)

    def test_roadmap_messages_do_not_claim_past_release_delivery(self) -> None:
        self.assertNotIn("arrives in V5.2", self.source)
        self.assertNotIn("arrives in V5.3", self.source)
        self.assertNotIn("Inventory Manager", self.source)
        self.assertNotIn("PSA Pipeline", self.source)


if __name__ == "__main__":
    unittest.main()
