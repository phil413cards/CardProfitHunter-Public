import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


class V51DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "dashboard-test.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_db()

    def test_latest_batch_metrics_empty(self):
        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 0)
        self.assertEqual(metrics["potential_profit"], 0.0)
        self.assertIsNone(metrics["best_opportunity"])

    def test_latest_batch_metrics_and_current_batch_exclude_watch(self):
        today = datetime.now(timezone.utc).date()
        provenance = {
            "verification_status": "verified",
            "verified_at": (today - timedelta(days=1)).isoformat(),
            "expires_at": (today + timedelta(days=30)).isoformat(),
            "source_url": "https://example.com/verified-comps",
            "comp_count": 10,
            "valuation_notes": "Verified comps",
        }
        frame = pd.DataFrame([
            {
                "item_id": "1",
                "title": "Card A",
                "item_url": "https://example.com/a",
                "total_price": 100,
                "recommended_action": "BUY_RAW_FLIP",
                "total_score": 90,
                "best_expected_profit": 50,
                "best_expected_roi_pct": 50,
                "suggested_offer": 80,
                "seller_username": "trusted-seller",
                "seller_feedback": 100,
                "seller_feedback_pct": 99.0,
                **provenance,
            },
            {
                "item_id": "2",
                "title": "Card B",
                "item_url": "https://example.com/b",
                "total_price": 200,
                "recommended_action": "WATCH",
                "total_score": 100,
                "best_expected_profit": 500,
                "best_expected_roi_pct": 500,
                "suggested_offer": 150,
            },
        ])
        database.save_opportunity_batch("batch-1", None, "Test", "cards", frame)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 2)
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["potential_profit"], 50.0)
        self.assertEqual(metrics["average_roi_pct"], 50.0)
        self.assertEqual(metrics["highest_score"], 90.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Card A")

        latest = database.latest_batch_opportunities()
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest.iloc[0]["title"], "Card A")


if __name__ == "__main__":
    unittest.main()
