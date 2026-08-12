import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


REAL_DB_PATH = database.DB_PATH


def current_provenance(**overrides):
    today = datetime.now(timezone.utc).date()
    values = {
        "verification_status": "verified",
        "verified_at": (today - timedelta(days=1)).isoformat(),
        "expires_at": (today + timedelta(days=30)).isoformat(),
        "source_url": "https://example.com/verified-comps",
        "comp_count": 10,
        "valuation_notes": "Verified comps",
    }
    values.update(overrides)
    return values


def opportunity(**overrides):
    row = {
        "item_id": "valuation-safe",
        "title": "Verified Card",
        "item_url": "https://example.com/valuation-safe",
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
        **current_provenance(),
    }
    row.update(overrides)
    return row


class DatabaseValuationFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "valuation-freshness.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(self.db_path, REAL_DB_PATH)
        database.init_db()

    def save_batch(self, rows, batch_id="batch"):
        database.save_opportunity_batch(
            batch_id,
            None,
            "Valuation Freshness",
            "verified card",
            pd.DataFrame(rows),
        )

    def insert_snapshot(self, title, payload, batch_id="legacy"):
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
                    "BUY_RAW_FLIP",
                    90,
                    50.0,
                    40.0,
                    90.0,
                    json.dumps(payload),
                    database.utc_now(),
                ),
            )

    def test_new_writes_fail_closed_for_unsafe_valuation_provenance(self):
        today = datetime.now(timezone.utc).date()
        cases = (
            ("missing", {"verification_status": None}, "missing_valuation_provenance"),
            (
                "expired",
                {"expires_at": (today - timedelta(days=1)).isoformat()},
                "expired_valuation",
            ),
            ("unverified", {"verification_status": "unverified"}, "unverified_valuation_status"),
            ("bad source", {"source_url": "http://example.com/comps"}, "invalid_valuation_provenance"),
            ("demo notes", {"valuation_notes": "Demonstration only"}, "non_actionable_valuation"),
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
                self.assertEqual(payload["matched_card"], "")
                self.assertEqual(payload["best_path"], "NONE")
                self.assertIn(expected_flag, payload["flags"].split(";"))
                for field in database.NON_ACTIONABLE_FINANCIAL_FIELDS:
                    self.assertIsNone(payload[field], field)

    def test_current_provenance_and_expiry_date_boundary_remain_actionable(self):
        today = datetime.now(timezone.utc).date()
        self.save_batch([
            opportunity(expires_at=today.isoformat()),
            opportunity(title="Future expiry"),
        ])

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["buy_candidates"], 2)
        self.assertEqual(metrics["potential_profit"], 100.0)

    def test_legacy_dashboard_and_history_reads_recheck_freshness(self):
        today = datetime.now(timezone.utc).date()
        current = opportunity(title="Current Legacy")
        expired = opportunity(
            title="Expired Legacy",
            expires_at=(today - timedelta(days=1)).isoformat(),
        )
        missing = opportunity(title="Missing Legacy")
        missing.pop("expires_at")

        self.insert_snapshot("Current Legacy", current)
        self.insert_snapshot("Expired Legacy", expired)
        self.insert_snapshot("Missing Legacy", missing)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["listings_analyzed"], 3)
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["potential_profit"], 50.0)
        self.assertEqual(metrics["best_opportunity"]["title"], "Current Legacy")

        current_rows = database.latest_batch_opportunities()
        self.assertEqual(list(current_rows["title"]), ["Current Legacy"])

        history = database.latest_opportunities()
        unsafe = history[history["title"] != "Current Legacy"]
        self.assertEqual(set(unsafe["recommended_action"]), {"PASS"})
        self.assertTrue(unsafe["expected_profit"].isna().all())
        self.assertTrue(unsafe["expected_roi_pct"].isna().all())
        self.assertTrue(unsafe["suggested_offer"].isna().all())

    def test_watchlist_and_recent_activity_recheck_freshness(self):
        today = datetime.now(timezone.utc).date()
        database.add_watchlist_row(
            opportunity(
                title="Expired New Watch",
                expires_at=(today - timedelta(days=1)).isoformat(),
            )
        )
        with database.connect() as conn:
            conn.execute(
                """INSERT INTO watchlist(
                       title, recommended_action, expected_profit,
                       expected_roi_pct, payload_json, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "Missing Legacy Watch",
                    "BUY_GRADE_PSA",
                    500.0,
                    200.0,
                    json.dumps({
                        key: value
                        for key, value in opportunity().items()
                        if key != "expires_at"
                    }),
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
