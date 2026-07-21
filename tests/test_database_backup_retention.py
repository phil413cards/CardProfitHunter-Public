import ast
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database


REAL_DB_PATH = database.DB_PATH
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _button_block(tree, label):
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
            continue
        call = node.test
        if (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "button"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == label
        ):
            return node
    raise AssertionError(f"Button block not found: {label}")


def _calls_in(node):
    return [child for child in ast.walk(node) if isinstance(child, ast.Call)]


class DatabaseBackupRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "database" / "card-profit-hunter-test.db"
        self.backup_dir = self.root / "backups"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        database.init_db()

    def _insert_history(self):
        old_time = (
            datetime.now(timezone.utc) - timedelta(days=400)
        ).isoformat(timespec="seconds")
        recent_time = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat(timespec="seconds")
        database.save_search(
            "Retention Search",
            "test card",
            25,
            "newlyListed",
            100.0,
            "183454",
        )
        database.add_watchlist_row({
            "item_id": "watch-1",
            "title": "Curated Watchlist Card",
            "total_price": 25.0,
        })
        with database.connect() as conn:
            search_id = conn.execute(
                "SELECT id FROM saved_searches WHERE name = ?",
                ("Retention Search",),
            ).fetchone()[0]
            conn.executemany(
                """INSERT INTO search_runs(
                       saved_search_id, query, result_count, created_at
                   ) VALUES (?, ?, ?, ?)""",
                (
                    (search_id, "old search", 1, old_time),
                    (search_id, "recent search", 1, recent_time),
                ),
            )
            rows = (
                ("old-batch", "Old One", old_time),
                ("old-batch", "Old Two", old_time),
                ("recent-batch", "Recent", recent_time),
                ("latest-old-batch", "Latest But Old", old_time),
            )
            conn.executemany(
                """INSERT INTO opportunity_snapshots(
                       batch_id, saved_search_id, saved_search_name, query,
                       title, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (batch_id, search_id, "Retention Search", "test card", title, created_at)
                    for batch_id, title, created_at in rows
                ],
            )

    def _table_count(self, table):
        with database.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_uses_only_temporary_database_and_backup_paths(self):
        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(str(self.db_path).startswith(str(self.root)))
        self.assertTrue(str(self.backup_dir).startswith(str(self.root)))

    def test_missing_source_returns_none_without_creating_database(self):
        missing_path = self.root / "missing" / "missing.db"
        with patch.object(database, "DB_PATH", missing_path):
            result = database.create_database_backup(self.backup_dir)

        self.assertIsNone(result)
        self.assertFalse(missing_path.exists())

    def test_backup_is_timestamped_complete_and_preserves_schema_version(self):
        self._insert_history()

        backup_path = database.create_database_backup(self.backup_dir)

        self.assertIsNotNone(backup_path)
        self.assertRegex(
            backup_path.name,
            r"^card-profit-hunter-test-backup-\d{8}T\d{12}Z\.db$",
        )
        with sqlite3.connect(backup_path) as conn:
            saved = conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0]
            opportunities = conn.execute(
                "SELECT COUNT(*) FROM opportunity_snapshots"
            ).fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(saved, 1)
        self.assertEqual(opportunities, 4)
        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertEqual(integrity, "ok")

    def test_backup_collision_creates_new_file_without_overwrite(self):
        with patch.object(database, "_backup_timestamp", return_value="20260716T120000000000Z"):
            first = database.create_database_backup(self.backup_dir)
            first_bytes = first.read_bytes()
            second = database.create_database_backup(self.backup_dir)

        self.assertNotEqual(first, second)
        self.assertEqual(first_bytes, first.read_bytes())
        self.assertTrue(second.name.endswith("-1.db"))

    def test_incomplete_backup_is_removed_on_failure(self):
        with patch.object(database, "_backup_integrity_is_valid", return_value=False):
            with self.assertRaisesRegex(
                database.DatabaseMaintenanceError,
                "could not be created",
            ):
                database.create_database_backup(self.backup_dir)

        self.assertEqual(list(self.backup_dir.glob("*.db")), [])

    def test_preview_counts_without_modifying_data(self):
        self._insert_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        before_runs = self._table_count("search_runs")
        before_opportunities = self._table_count("opportunity_snapshots")
        preview = database.preview_history_retention(cutoff)

        self.assertEqual(preview["search_runs"], 1)
        self.assertEqual(preview["opportunity_snapshots"], 2)
        self.assertEqual(self._table_count("search_runs"), before_runs)
        self.assertEqual(
            self._table_count("opportunity_snapshots"),
            before_opportunities,
        )

    def test_cleanup_without_confirmation_is_rejected(self):
        self._insert_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "explicit confirmation",
        ):
            database.apply_history_retention(cutoff, self.backup_dir)

        self.assertEqual(self._table_count("search_runs"), 2)
        self.assertEqual(self._table_count("opportunity_snapshots"), 4)
        self.assertFalse(self.backup_dir.exists())

    def test_backup_failure_blocks_cleanup(self):
        self._insert_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        with patch.object(
            database,
            "create_database_backup",
            side_effect=database.DatabaseMaintenanceError("Backup failed."),
        ):
            with self.assertRaises(database.DatabaseMaintenanceError):
                database.apply_history_retention(
                    cutoff,
                    self.backup_dir,
                    confirmed=True,
                )

        self.assertEqual(self._table_count("search_runs"), 2)
        self.assertEqual(self._table_count("opportunity_snapshots"), 4)

    def test_cleanup_failure_is_sanitized_and_rolls_back_all_deletions(self):
        self._insert_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        with database.connect() as conn:
            conn.execute(
                """CREATE TRIGGER block_search_run_cleanup
                   BEFORE DELETE ON search_runs
                   BEGIN
                       SELECT RAISE(ABORT, 'private database detail');
                   END"""
            )

        with self.assertRaises(database.DatabaseMaintenanceError) as raised:
            database.apply_history_retention(
                cutoff,
                self.backup_dir,
                confirmed=True,
            )

        self.assertEqual(
            str(raised.exception),
            "History retention cleanup could not be completed.",
        )
        self.assertNotIn("private database detail", str(raised.exception))
        self.assertEqual(self._table_count("search_runs"), 2)
        self.assertEqual(self._table_count("opportunity_snapshots"), 4)

    def test_confirmed_cleanup_is_backed_up_and_preserves_curated_data(self):
        self._insert_history()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        result = database.apply_history_retention(
            cutoff,
            self.backup_dir,
            confirmed=True,
        )

        self.assertEqual(result["search_runs"], 1)
        self.assertEqual(result["opportunity_snapshots"], 2)
        self.assertEqual(self._table_count("search_runs"), 1)
        with database.connect() as conn:
            batches = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT batch_id FROM opportunity_snapshots"
                ).fetchall()
            }
            saved = conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0]
            watched = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        self.assertEqual(batches, {"recent-batch", "latest-old-batch"})
        self.assertEqual(saved, 1)
        self.assertEqual(watched, 1)

        backup_path = result["backup_path"]
        with sqlite3.connect(backup_path) as backup:
            old_snapshots = backup.execute(
                "SELECT COUNT(*) FROM opportunity_snapshots WHERE batch_id = ?",
                ("old-batch",),
            ).fetchone()[0]
            old_runs = backup.execute(
                "SELECT COUNT(*) FROM search_runs WHERE query = ?",
                ("old search",),
            ).fetchone()[0]
        self.assertEqual(old_snapshots, 2)
        self.assertEqual(old_runs, 1)

    def test_invalid_and_future_cutoffs_are_rejected(self):
        invalid_cutoffs = (
            None,
            "2020-01-01",
            datetime.now(),
            datetime.now(timezone.utc) + timedelta(days=1),
        )
        for cutoff in invalid_cutoffs:
            with self.subTest(cutoff=cutoff):
                with self.assertRaisesRegex(
                    database.DatabaseMaintenanceError,
                    "timezone-aware past datetime",
                ):
                    database.preview_history_retention(cutoff)


class AppDatabaseMaintenanceWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def assert_button_contains_call(self, label, expected_call):
        block = _button_block(self.tree, label)
        calls = {_call_name(call) for call in _calls_in(block)}
        self.assertIn(expected_call, calls)

    def test_backup_runs_only_from_explicit_button(self):
        self.assert_button_contains_call(
            "Create Database Backup",
            "create_database_backup",
        )

    def test_preview_runs_only_from_explicit_button(self):
        self.assert_button_contains_call(
            "Preview History Cleanup",
            "preview_history_retention",
        )

    def test_cleanup_runs_only_from_explicit_confirmed_button(self):
        block = _button_block(self.tree, "Back Up and Delete Old History")
        calls = {_call_name(call) for call in _calls_in(block)}
        self.assertIn("apply_history_retention", calls)
        button_call = block.test
        disabled = next(
            keyword.value
            for keyword in button_call.keywords
            if keyword.arg == "disabled"
        )
        self.assertIsInstance(disabled, ast.UnaryOp)
        self.assertIsInstance(disabled.op, ast.Not)


if __name__ == "__main__":
    unittest.main()
