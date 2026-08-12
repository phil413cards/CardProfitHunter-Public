import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


REAL_DB_PATH = database.DB_PATH


def opportunity(**overrides):
    today = datetime.now(timezone.utc).date()
    row = {
        "item_id": "valid",
        "title": "Verified Card",
        "item_url": "https://example.com/valid",
        "total_price": 100.0,
        "recommended_action": "BUY_RAW_FLIP",
        "total_score": 90,
        "best_path": "RAW_FLIP",
        "best_expected_profit": 50.0,
        "best_expected_roi_pct": 40.0,
        "raw_flip_profit": 50.0,
        "raw_flip_roi_pct": 40.0,
        "max_buy_price_raw_flip": 125.0,
        "suggested_offer": 90.0,
        "matched_card": "Verified Card",
        "match_strength": 1.0,
        "raw_market_value": 200.0,
        "valuation_available": True,
        "financially_verified": True,
        "flags": "raw_flip_profitable",
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
    row.update(overrides)
    return row


class DatabaseSellerEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "seller-safety.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(self.db_path, REAL_DB_PATH)
        database.init_db()

    def save_batch(self, rows, batch_id="batch"):
        database.save_opportunity_batch(
            batch_id,
            None,
            "Seller Safety",
            "verified card",
            pd.DataFrame(rows),
        )

    def insert_snapshot(
        self,
        title,
        action,
        profit,
        roi,
        score,
        payload,
        batch_id="legacy",
    ):
        payload_json = payload if isinstance(payload, str) else json.dumps(payload)
        with database.connect() as conn:
            conn.execute(
                """INSERT INTO opportunity_snapshots(
                       batch_id, saved_search_name, query, title,
                       recommended_action, total_score, expected_profit,
                       expected_roi_pct, suggested_offer, payload_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    "Legacy Search",
                    "legacy cards",
                    title,
                    action,
                    score,
                    profit,
                    roi,
                    75.0,
                    payload_json,
                    database.utc_now(),
                ),
            )

    def test_new_snapshot_writes_fail_closed_for_ineligible_sellers(self):
        cases = (
            (
                "missing seller",
                {"seller_username": None},
                "missing_seller_username",
            ),
            (
                "low count",
                {"seller_feedback": 99},
                "insufficient_seller_feedback",
            ),
            (
                "low percentage",
                {"seller_feedback_pct": 98.9},
                "insufficient_seller_feedback_pct",
            ),
            (
                "malformed count",
                {"seller_feedback": "many"},
                "invalid_seller_feedback",
            ),
        )

        for index, (name, overrides, expected_flag) in enumerate(cases):
            with self.subTest(name=name):
                batch_id = f"unsafe-{index}"
                self.save_batch([opportunity(**overrides)], batch_id)
                with database.connect() as conn:
                    stored = conn.execute(
                        """SELECT recommended_action, expected_profit,
                                  expected_roi_pct, suggested_offer, payload_json
                           FROM opportunity_snapshots WHERE batch_id = ?""",
                        (batch_id,),
                    ).fetchone()

                self.assertEqual(stored["recommended_action"], "PASS")
                self.assertIsNone(stored["expected_profit"])
                self.assertIsNone(stored["expected_roi_pct"])
                self.assertIsNone(stored["suggested_offer"])
                payload = json.loads(stored["payload_json"])
                self.assertEqual(payload["recommended_action"], "PASS")
                self.assertEqual(payload["matched_card"], "")
                self.assertEqual(payload["best_path"], "NONE")
                self.assertFalse(payload["valuation_available"])
                self.assertFalse(payload["financially_verified"])
                self.assertIn(expected_flag, payload["flags"].split(";"))
                for field in database.NON_ACTIONABLE_FINANCIAL_FIELDS:
                    self.assertIsNone(payload[field], field)

    def test_valid_numeric_string_seller_data_remains_actionable(self):
        self.save_batch([
            opportunity(
                seller_feedback="100",
                seller_feedback_pct="99.0",
            )
        ])

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["potential_profit"], 50.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Verified Card")

    def test_legacy_dashboard_reads_recheck_stored_seller_payloads(self):
        valid_payload = opportunity(title="Eligible Legacy")
        missing_payload = opportunity(title="Missing Legacy")
        missing_payload.pop("seller_feedback")
        low_payload = opportunity(
            title="Low Legacy",
            recommended_action="OFFER",
            seller_feedback_pct=98.0,
        )
        mismatched_payload = opportunity(
            title="Mismatched Legacy",
            recommended_action="PASS",
        )

        self.insert_snapshot("Eligible Legacy", "BUY_RAW_FLIP", 50, 40, 90, valid_payload)
        self.insert_snapshot("Missing Legacy", "BUY_RAW_FLIP", 900, 300, 999, missing_payload)
        self.insert_snapshot("Low Legacy", "OFFER", 800, 250, 998, low_payload)
        self.insert_snapshot("Malformed Legacy", "BUY_GRADE_PSA", 700, 200, 997, "not-json")
        self.insert_snapshot("Mismatched Legacy", "BUY_RAW_FLIP", 600, 150, 996, mismatched_payload)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 5)
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["potential_profit"], 50.0)
        self.assertEqual(metrics["average_roi_pct"], 40.0)
        self.assertEqual(metrics["highest_score"], 90.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Eligible Legacy")

        summary = database.latest_batch_summary().iloc[0]
        self.assertEqual(summary["listings"], 5)
        self.assertEqual(summary["buy_candidates"], 1)
        self.assertEqual(summary["best_profit"], 50.0)
        self.assertEqual(summary["best_roi_pct"], 40.0)

        current = database.latest_batch_opportunities()
        self.assertEqual(list(current["title"]), ["Eligible Legacy"])

        history = database.latest_opportunities()
        unsafe = history[history["title"] != "Eligible Legacy"]
        self.assertEqual(set(unsafe["recommended_action"]), {"PASS"})
        self.assertTrue(unsafe["expected_profit"].isna().all())
        self.assertTrue(unsafe["expected_roi_pct"].isna().all())
        self.assertTrue(unsafe["suggested_offer"].isna().all())

    def test_watchlist_writes_and_legacy_reads_fail_closed(self):
        database.add_watchlist_row(
            opportunity(
                title="Low New Watch",
                seller_feedback=10,
            )
        )
        with database.connect() as conn:
            conn.execute(
                """INSERT INTO watchlist(
                       title, recommended_action, expected_profit,
                       expected_roi_pct, payload_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "Legacy Watch",
                    "BUY_GRADE_PSA",
                    500.0,
                    200.0,
                    None,
                    database.utc_now(),
                ),
            )

        watchlist = database.list_watchlist()
        self.assertEqual(set(watchlist["recommended_action"]), {"PASS"})
        self.assertTrue(watchlist["expected_profit"].isna().all())
        self.assertTrue(watchlist["expected_roi_pct"].isna().all())

        activity = database.recent_activity()
        watch_activity = activity[activity["activity_type"] == "Watchlist"]
        self.assertEqual(set(watch_activity["detail"]), {"PASS"})


if __name__ == "__main__":
    unittest.main()
