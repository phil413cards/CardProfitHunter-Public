import ast
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import database


REAL_DB_PATH = database.DB_PATH
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def current_opportunity(**overrides):
    today = datetime.now(timezone.utc).date()
    row = {
        "item_id": "current-card",
        "title": "Current Verified Card",
        "item_url": "https://example.com/current-card",
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
        "matched_card": "Current Verified Card",
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


class DailyBoardBatchOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "batch-outcomes.db"
        self.backup_dir = self.root / "backups"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(self.db_path, REAL_DB_PATH)
        database.init_db()

    def save_actionable_batch(self, batch_id="old-actionable"):
        database.save_opportunity_batch(
            batch_id,
            None,
            "Verified Search",
            "verified card",
            pd.DataFrame([current_opportunity()]),
        )

    def save_outcome(
        self,
        batch_id,
        status,
        attempted,
        successful,
        empty,
        failed,
        results,
        completed_at=None,
    ):
        database.save_opportunity_batch_outcome(
            batch_id,
            status=status,
            attempted_count=attempted,
            successful_count=successful,
            empty_count=empty,
            failed_count=failed,
            result_count=results,
            completed_at=completed_at or database.utc_now(),
        )

    def assert_zero_current_opportunities(self, expected_status, expected_batch):
        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["batch_id"], expected_batch)
        self.assertEqual(metrics["status"], expected_status)
        self.assertEqual(metrics["listings_analyzed"], 0)
        self.assertEqual(metrics["buy_candidates"], 0)
        self.assertEqual(metrics["potential_profit"], 0.0)
        self.assertEqual(metrics["average_roi_pct"], 0.0)
        self.assertEqual(metrics["highest_score"], 0.0)
        self.assertIsNone(metrics["best_opportunity"])
        self.assertTrue(database.latest_batch_summary().empty)
        self.assertTrue(database.latest_batch_opportunities().empty)

    def test_all_empty_outcome_replaces_prior_dashboard_metrics(self):
        self.save_actionable_batch()
        self.assertEqual(database.latest_batch_metrics()["buy_candidates"], 1)

        self.save_outcome("empty-run", "empty", 2, 2, 2, 0, 0)

        self.assert_zero_current_opportunities("empty", "empty-run")
        history = database.latest_opportunities()
        self.assertEqual(list(history["title"]), ["Current Verified Card"])
        self.assertEqual(history.iloc[0]["recommended_action"], "BUY_RAW_FLIP")

    def test_all_failed_outcome_replaces_prior_dashboard_metrics(self):
        self.save_actionable_batch()

        self.save_outcome("failed-run", "failed", 2, 0, 0, 2, 0)

        self.assert_zero_current_opportunities("failed", "failed-run")
        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["attempted_count"], 2)
        self.assertEqual(metrics["failed_count"], 2)

    def test_partial_outcome_preserves_only_its_successful_rows(self):
        self.save_actionable_batch("previous")
        database.save_opportunity_batch(
            "partial-run",
            None,
            "Partial Search",
            "verified card",
            pd.DataFrame([current_opportunity(title="Partial Current Card")]),
        )
        self.save_outcome("partial-run", "partial", 2, 1, 0, 1, 1)

        metrics = database.latest_batch_metrics()
        self.assertEqual(metrics["status"], "partial")
        self.assertEqual(metrics["successful_count"], 1)
        self.assertEqual(metrics["failed_count"], 1)
        self.assertEqual(metrics["listings_analyzed"], 1)
        self.assertEqual(metrics["buy_candidates"], 1)
        self.assertEqual(metrics["best_opportunity"]["title"], "Partial Current Card")
        self.assertEqual(
            list(database.latest_batch_opportunities()["title"]),
            ["Partial Current Card"],
        )

    def test_same_second_outcomes_use_most_recently_saved_run(self):
        completed_at = "2026-08-11T12:00:00+00:00"
        self.save_outcome(
            "first-empty",
            "empty",
            1,
            1,
            1,
            0,
            0,
            completed_at,
        )
        self.save_outcome(
            "second-failed",
            "failed",
            1,
            0,
            0,
            1,
            0,
            completed_at,
        )

        self.assert_zero_current_opportunities("failed", "second-failed")

    def test_invalid_outcomes_are_rejected_without_persistence(self):
        cases = (
            ("invalid status", {"status": "private-invalid"}),
            ("missing batch id", {"batch_id": None}),
            ("status mismatch", {"status": "success", "failed_count": 1}),
            ("count mismatch", {"attempted_count": 3}),
            ("negative count", {"result_count": -1}),
            ("empty with results", {"status": "empty", "failed_count": 0, "successful_count": 2, "empty_count": 2}),
            ("naive timestamp", {"completed_at": "2026-08-11T12:00:00"}),
            ("future timestamp", {"completed_at": "2099-01-01T00:00:00+00:00"}),
        )
        baseline = {
            "status": "partial",
            "attempted_count": 2,
            "successful_count": 1,
            "empty_count": 0,
            "failed_count": 1,
            "result_count": 1,
            "completed_at": database.utc_now(),
        }

        for index, (name, overrides) in enumerate(cases):
            with self.subTest(name=name):
                values = dict(baseline)
                values.update(overrides)
                batch_id = values.pop("batch_id", f"invalid-{index}")
                with self.assertRaisesRegex(ValueError, "outcome is invalid") as raised:
                    database.save_opportunity_batch_outcome(
                        batch_id,
                        **values,
                    )
                self.assertNotIn("private-invalid", str(raised.exception))

        with database.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_batches"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_version_one_database_migrates_additively_and_preserves_data(self):
        database.save_search(
            "Preserved Search",
            "preserved query",
            25,
            "newlyListed",
            100.0,
            "183454",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE opportunity_batches")
            conn.execute(
                f"PRAGMA user_version = {database.LEGACY_SCHEMA_VERSION}"
            )

        database.init_db()

        with database.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            query = conn.execute(
                "SELECT query FROM saved_searches WHERE name = ?",
                ("Preserved Search",),
            ).fetchone()[0]
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='opportunity_batches'"
            ).fetchone()
        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertEqual(query, "preserved query")
        self.assertIsNotNone(table)

    def test_version_one_backup_is_restored_and_migrated_before_replacement(self):
        database.save_search(
            "Version One Search",
            "version one query",
            25,
            "newlyListed",
            100.0,
            "183454",
        )
        source = database.create_database_backup(self.backup_dir)
        self.assertIsNotNone(source)
        with sqlite3.connect(source) as conn:
            conn.execute("DROP TABLE opportunity_batches")
            conn.execute(
                f"PRAGMA user_version = {database.LEGACY_SCHEMA_VERSION}"
            )

        metadata = database.inspect_database_backup(source, self.backup_dir)
        self.assertEqual(metadata["schema_version"], database.LEGACY_SCHEMA_VERSION)
        with database.connect() as conn:
            conn.execute("DELETE FROM saved_searches")

        result = database.restore_database_backup(
            source,
            self.backup_dir,
            confirmed=True,
        )

        self.assertEqual(result["schema_version"], database.SCHEMA_VERSION)
        with database.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            query = conn.execute(
                "SELECT query FROM saved_searches WHERE name = ?",
                ("Version One Search",),
            ).fetchone()[0]
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='opportunity_batches'"
            ).fetchone()
        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertEqual(query, "version one query")
        self.assertIsNotNone(table)

    def test_recorded_batch_retention_is_explicit_and_preserves_latest(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(
            timespec="seconds"
        )
        recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(
            timespec="seconds"
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        self.save_outcome("old-empty", "empty", 1, 1, 1, 0, 0, old)
        self.save_outcome("recent-empty", "empty", 1, 1, 1, 0, 0, recent)

        preview = database.preview_history_retention(cutoff)
        self.assertEqual(preview["opportunity_batches"], 1)
        with database.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM opportunity_batches").fetchone()[0],
                2,
            )

        deleted = database.apply_history_retention(
            cutoff,
            self.backup_dir,
            confirmed=True,
        )
        self.assertEqual(deleted["opportunity_batches"], 1)
        with database.connect() as conn:
            rows = conn.execute(
                "SELECT batch_id FROM opportunity_batches"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["recent-empty"])

    def test_retention_preserves_latest_snapshot_when_newer_outcome_has_no_rows(self):
        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(
            timespec="seconds"
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        with database.connect() as conn:
            conn.execute(
                """INSERT INTO opportunity_snapshots(
                       batch_id, saved_search_name, query, title, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                ("latest-snapshot", "Legacy Search", "card", "Preserved", old),
            )
        self.save_outcome("latest-empty-outcome", "empty", 1, 1, 1, 0, 0, old)

        preview = database.preview_history_retention(cutoff)

        self.assertEqual(preview["opportunity_snapshots"], 0)
        self.assertEqual(preview["opportunity_batches"], 0)


class DailyBoardBatchOutcomeWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_app_is_not_imported_and_outcome_is_saved_after_classification(self):
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        ]
        build_calls = [call for call in calls if call.func.id == "build_run_outcome"]
        save_calls = [
            call for call in calls if call.func.id == "save_opportunity_batch_outcome"
        ]
        rerun_calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "rerun"
        ]

        self.assertEqual(len(build_calls), 2)
        self.assertEqual(len(save_calls), 1)
        preceding_build_calls = [
            call for call in build_calls if call.lineno < save_calls[0].lineno
        ]
        self.assertEqual(len(preceding_build_calls), 1)
        self.assertTrue(
            any(call.lineno > save_calls[0].lineno for call in rerun_calls)
        )
        self.assertIn('if kpis["status"] == "failed"', self.source)
        self.assertIn('elif kpis["status"] == "empty"', self.source)
        self.assertIn('elif kpis["status"] == "partial"', self.source)


if __name__ == "__main__":
    unittest.main()
