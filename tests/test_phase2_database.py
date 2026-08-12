import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


REAL_DB_PATH = database.DB_PATH


class Phase2DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        database.init_db()

    def test_save_and_read_opportunity_batch(self):
        today = datetime.now(timezone.utc).date()
        frame = pd.DataFrame([{
            "item_id": "1", "title": "Test Card", "item_url": "https://example.com",
            "total_price": 10.0, "recommended_action": "BUY_RAW_FLIP", "total_score": 88,
            "best_expected_profit": 15.0, "best_expected_roi_pct": 150.0, "suggested_offer": 8.0,
            "seller_username": "trusted-seller", "seller_feedback": 100,
            "seller_feedback_pct": 99.0,
            "verification_status": "verified",
            "verified_at": (today - timedelta(days=1)).isoformat(),
            "expires_at": (today + timedelta(days=30)).isoformat(),
            "source_url": "https://example.com/verified-comps",
            "comp_count": 10,
            "valuation_notes": "Verified comps",
        }])
        database.save_opportunity_batch("batch", None, "Test", "test card", frame)
        result = database.latest_opportunities()
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["title"], "Test Card")
        self.assertEqual(database.dashboard_metrics()["opportunities"], 1)


if __name__ == "__main__":
    unittest.main()
