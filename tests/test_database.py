import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


REAL_DB_PATH = database.DB_PATH


def opportunity(
    item_id,
    title,
    action,
    profit,
    roi,
    score,
    suggested_offer=None,
):
    today = datetime.now(timezone.utc).date()
    return {
        "item_id": item_id,
        "title": title,
        "item_url": f"https://example.com/{item_id}",
        "total_price": 100.0,
        "recommended_action": action,
        "total_score": score,
        "best_path": "RAW_FLIP",
        "best_expected_profit": profit,
        "best_expected_roi_pct": roi,
        "raw_flip_profit": profit,
        "raw_flip_roi_pct": roi,
        "max_buy_price_raw_flip": 80.0,
        "suggested_offer": suggested_offer,
        "raw_market_value": 200.0,
        "seller_username": "trusted-seller",
        "seller_feedback": 100,
        "seller_feedback_pct": 99.0,
        "verification_status": "verified",
        "verified_at": (today - timedelta(days=1)).isoformat(),
        "expires_at": (today + timedelta(days=30)).isoformat(),
        "source_url": "https://example.com/verified-comps",
        "comp_count": 10,
        "valuation_notes": "Verified comps",
    }


class DatabaseDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "card-profit-hunter-test.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_db()

    def save_batch(self, rows, batch_id="batch-1"):
        database.save_opportunity_batch(
            batch_id,
            None,
            "Test Search",
            "test cards",
            pd.DataFrame(rows),
        )

    def insert_legacy_row(self, title, action, profit, roi, score, batch_id="legacy"):
        today = datetime.now(timezone.utc).date()
        payload = json.dumps({
            "title": title,
            "recommended_action": action,
            "seller_username": "trusted-seller",
            "seller_feedback": 100,
            "seller_feedback_pct": 99.0,
            "verification_status": "verified",
            "verified_at": (today - timedelta(days=1)).isoformat(),
            "expires_at": (today + timedelta(days=30)).isoformat(),
            "source_url": "https://example.com/verified-comps",
            "comp_count": 10,
            "valuation_notes": "Verified comps",
        })
        with database.connect() as conn:
            conn.execute(
                """INSERT INTO opportunity_snapshots(
                       batch_id, saved_search_name, query, title, recommended_action,
                       total_score, expected_profit, expected_roi_pct, payload_json,
                       created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    "Legacy Search",
                    "legacy cards",
                    title,
                    action,
                    score,
                    profit,
                    roi,
                    payload,
                    database.utc_now(),
                ),
            )

    def test_uses_temporary_database(self):
        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(self.db_path.exists())

    def test_all_pass_batch_is_zero_and_sanitized(self):
        self.save_batch([
            opportunity("pass", "Demo Card", "PASS", 500.0, 250.0, 999, 75.0),
        ])

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 1)
        self.assertEqual(metrics["buy_candidates"], 0)
        self.assertEqual(metrics["potential_profit"], 0.0)
        self.assertEqual(metrics["average_roi_pct"], 0.0)
        self.assertEqual(metrics["highest_score"], 0.0)
        self.assertIsNone(metrics["best_opportunity"])
        self.assertTrue(database.latest_batch_opportunities().empty)

        with database.connect() as conn:
            stored = conn.execute(
                """SELECT expected_profit, expected_roi_pct, suggested_offer, payload_json
                   FROM opportunity_snapshots"""
            ).fetchone()
        self.assertIsNone(stored["expected_profit"])
        self.assertIsNone(stored["expected_roi_pct"])
        self.assertIsNone(stored["suggested_offer"])
        payload = json.loads(stored["payload_json"])
        self.assertEqual(payload["best_path"], "NONE")
        for field in database.NON_ACTIONABLE_FINANCIAL_FIELDS:
            self.assertIsNone(payload[field], field)

    def test_positive_legacy_pass_and_watch_values_are_ignored(self):
        self.insert_legacy_row("Legacy PASS", "PASS", 900.0, 300.0, 999)
        self.insert_legacy_row("Legacy WATCH", "WATCH", 800.0, 200.0, 998)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 2)
        self.assertEqual(metrics["potential_profit"], 0.0)
        self.assertEqual(metrics["average_roi_pct"], 0.0)
        self.assertEqual(metrics["highest_score"], 0.0)
        self.assertIsNone(metrics["best_opportunity"])

    def test_mixed_batch_counts_only_actionable_rows(self):
        self.insert_legacy_row("Misleading PASS", "PASS", 900.0, 300.0, 999)
        self.insert_legacy_row("Misleading WATCH", "WATCH", 800.0, 200.0, 998)
        self.insert_legacy_row("Actionable Buy", "BUY_RAW_FLIP", 50.0, 40.0, 90)
        self.insert_legacy_row("Actionable Offer", "OFFER", 20.0, 20.0, 80)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 4)
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["potential_profit"], 70.0)
        self.assertEqual(metrics["average_roi_pct"], 30.0)
        self.assertEqual(metrics["highest_score"], 90.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Actionable Buy")

        latest = database.latest_batch_opportunities()
        self.assertEqual(list(latest["title"]), ["Actionable Buy", "Actionable Offer"])

        summary = database.latest_batch_summary().iloc[0]
        self.assertEqual(summary["listings"], 4)
        self.assertEqual(summary["buy_candidates"], 1)
        self.assertEqual(summary["best_profit"], 50.0)
        self.assertEqual(summary["best_roi_pct"], 40.0)

    def test_actionable_only_rows_contribute_correctly(self):
        self.save_batch([
            opportunity("buy", "Verified Buy", "BUY_GRADE_PSA", 60.0, 50.0, 95),
            opportunity("offer", "Verified Offer", "OFFER", 15.0, 10.0, 75, 70.0),
        ])

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["potential_profit"], 75.0)
        self.assertEqual(metrics["average_roi_pct"], 30.0)
        self.assertEqual(metrics["highest_score"], 95.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Verified Buy")


if __name__ == "__main__":
    unittest.main()
