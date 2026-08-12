import ast
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database


REAL_DB_PATH = database.DB_PATH
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TEST_PATH = Path(__file__).resolve()


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


class DatabaseRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "card-profit-hunter-test.db"
        self.backup_dir = self.root / "output" / "database_backups"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        database.init_db()

    def _save_search(self, name):
        database.save_search(
            name,
            f"query for {name}",
            25,
            "newlyListed",
            100.0,
            "183454",
        )

    def _search_names(self, path=None):
        if path is None:
            with database.connect() as conn:
                rows = conn.execute(
                    "SELECT name FROM saved_searches ORDER BY name"
                ).fetchall()
        else:
            with sqlite3.connect(path) as conn:
                rows = conn.execute(
                    "SELECT name FROM saved_searches ORDER BY name"
                ).fetchall()
        return [row[0] for row in rows]

    def _prepare_restore_source(self):
        self._save_search("Backup Search")
        source = database.create_database_backup(self.backup_dir)
        self.assertIsNotNone(source)
        with database.connect() as conn:
            conn.execute("DELETE FROM saved_searches")
        self._save_search("Current Search")
        return source

    def test_uses_only_temporary_database_and_backup_paths(self):
        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(str(self.db_path).startswith(str(self.root)))
        self.assertTrue(str(self.backup_dir).startswith(str(self.root)))

    def test_inspection_returns_only_safe_metadata(self):
        source = self._prepare_restore_source()

        metadata = database.inspect_database_backup(source, self.backup_dir)

        self.assertEqual(metadata["filename"], source.name)
        self.assertEqual(metadata["schema_version"], database.SCHEMA_VERSION)
        self.assertEqual(metadata["integrity"], "ok")
        self.assertGreater(metadata["size_bytes"], 0)
        self.assertNotIn("Backup Search", repr(metadata))
        self.assertNotIn(str(source), repr(metadata))

    def test_missing_corrupt_and_symlink_sources_are_rejected_safely(self):
        invalid_sources = []
        missing = self.backup_dir / "missing.db"
        invalid_sources.append(missing)

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        corrupt = self.backup_dir / "corrupt.db"
        corrupt.write_bytes(b"private malformed database contents")
        invalid_sources.append(corrupt)

        source = self._prepare_restore_source()
        symlink = self.backup_dir / "linked.db"
        try:
            symlink.symlink_to(source)
        except (NotImplementedError, OSError):
            symlink = None
        if symlink is not None:
            invalid_sources.append(symlink)

        for candidate in invalid_sources:
            with self.subTest(candidate=candidate.name):
                with self.assertRaises(database.DatabaseMaintenanceError) as raised:
                    database.inspect_database_backup(candidate, self.backup_dir)
                message = str(raised.exception)
                self.assertIn("could not be verified", message)
                self.assertNotIn("private malformed", message)
                self.assertNotIn(str(candidate), message)

    def test_incompatible_schema_version_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "not compatible",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_missing_required_table_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute("DROP TABLE watchlist")

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "not compatible",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_missing_required_column_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute(
                "ALTER TABLE saved_searches RENAME COLUMN query TO removed_query"
            )

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "not compatible",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_missing_required_foreign_key_definition_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("ALTER TABLE search_runs RENAME TO search_runs_old")
            conn.execute(
                """CREATE TABLE search_runs (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       saved_search_id INTEGER,
                       query TEXT NOT NULL,
                       result_count INTEGER NOT NULL,
                       created_at TEXT NOT NULL
                   )"""
            )
            conn.execute("DROP TABLE search_runs_old")

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "not compatible",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_wrong_required_index_shape_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute("DROP INDEX idx_opportunity_batch")
            conn.execute(
                "CREATE INDEX idx_opportunity_batch ON opportunity_snapshots(title)"
            )

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "not compatible",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_foreign_key_violation_is_rejected(self):
        source = self._prepare_restore_source()
        with sqlite3.connect(source) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """INSERT INTO search_runs(
                       saved_search_id, query, result_count, created_at
                   ) VALUES (?, ?, ?, ?)""",
                (999999, "orphan", 1, "2026-08-09T00:00:00+00:00"),
            )

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "could not be verified",
        ):
            database.inspect_database_backup(source, self.backup_dir)

    def test_restore_requires_explicit_confirmation(self):
        source = self._prepare_restore_source()

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "explicit confirmation",
        ):
            database.restore_database_backup(source, self.backup_dir)

        self.assertEqual(self._search_names(), ["Current Search"])
        self.assertEqual(len(list(self.backup_dir.glob("*.db"))), 1)

    def test_confirmed_restore_creates_safety_backup_and_restores_source(self):
        source = self._prepare_restore_source()
        source_bytes = source.read_bytes()

        result = database.restore_database_backup(
            source,
            self.backup_dir,
            confirmed=True,
        )

        self.assertEqual(self._search_names(), ["Backup Search"])
        safety_backup = result["safety_backup_path"]
        self.assertNotEqual(source, safety_backup)
        self.assertTrue(safety_backup.is_file())
        self.assertEqual(self._search_names(safety_backup), ["Current Search"])
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(result["restored_from"], source.name)
        self.assertEqual(result["schema_version"], database.SCHEMA_VERSION)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0],
                database.SCHEMA_VERSION,
            )

    def test_backup_failure_blocks_restore_without_changing_current_data(self):
        source = self._prepare_restore_source()
        current_bytes = self.db_path.read_bytes()

        with patch.object(
            database,
            "create_database_backup",
            side_effect=database.DatabaseMaintenanceError("private backup detail"),
        ):
            with self.assertRaises(database.DatabaseMaintenanceError) as raised:
                database.restore_database_backup(
                    source,
                    self.backup_dir,
                    confirmed=True,
                )

        self.assertEqual(
            str(raised.exception),
            "Database restore could not be completed.",
        )
        self.assertNotIn("private backup detail", str(raised.exception))
        self.assertEqual(self.db_path.read_bytes(), current_bytes)
        self.assertEqual(self._search_names(), ["Current Search"])

    def test_atomic_replace_failure_preserves_current_database_and_cleans_temp(self):
        source = self._prepare_restore_source()
        current_bytes = self.db_path.read_bytes()

        with patch.object(
            database.os,
            "replace",
            side_effect=OSError("private replace detail"),
        ):
            with self.assertRaises(database.DatabaseMaintenanceError) as raised:
                database.restore_database_backup(
                    source,
                    self.backup_dir,
                    confirmed=True,
                )

        self.assertEqual(
            str(raised.exception),
            "Database restore could not be completed.",
        )
        self.assertNotIn("private replace detail", str(raised.exception))
        self.assertEqual(self.db_path.read_bytes(), current_bytes)
        self.assertEqual(self._search_names(), ["Current Search"])
        self.assertEqual(list(self.db_path.parent.glob(".*.restore-*")), [])

    def test_restore_rejects_source_outside_the_backup_directory(self):
        source = self._prepare_restore_source()
        outside = self.root / "outside.db"
        outside.write_bytes(source.read_bytes())

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "could not be verified",
        ):
            database.restore_database_backup(
                outside,
                self.backup_dir,
                confirmed=True,
            )

        self.assertEqual(self._search_names(), ["Current Search"])

    def test_missing_current_database_fails_without_creating_a_target(self):
        source = self._prepare_restore_source()
        self.db_path.unlink()

        with self.assertRaisesRegex(
            database.DatabaseMaintenanceError,
            "could not be completed",
        ):
            database.restore_database_backup(
                source,
                self.backup_dir,
                confirmed=True,
            )

        self.assertFalse(self.db_path.exists())

    def test_invalid_path_types_are_sanitized(self):
        for backup_path, backup_dir in ((None, self.backup_dir), ({}, [])):
            with self.subTest(backup_path=type(backup_path).__name__):
                with self.assertRaisesRegex(
                    database.DatabaseMaintenanceError,
                    "could not be verified",
                ):
                    database.restore_database_backup(
                        backup_path,
                        backup_dir,
                        confirmed=True,
                    )


class AppDatabaseRestoreWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.test_source = TEST_PATH.read_text(encoding="utf-8")

    def test_app_is_not_imported_by_restore_tests(self):
        test_tree = ast.parse(self.test_source)
        imported_modules = {
            alias.name
            for node in ast.walk(test_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(test_tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertNotIn("app", imported_modules)

    def test_verification_runs_only_from_explicit_button(self):
        block = _button_block(self.tree, "Verify Selected Database Backup")
        calls = {_call_name(call) for call in ast.walk(block) if isinstance(call, ast.Call)}
        self.assertIn("inspect_database_backup", calls)

    def test_restore_runs_only_from_explicit_confirmed_button(self):
        block = _button_block(self.tree, "Restore Selected Database Backup")
        calls = {_call_name(call) for call in ast.walk(block) if isinstance(call, ast.Call)}
        self.assertIn("restore_database_backup", calls)
        disabled = next(
            keyword.value
            for keyword in block.test.keywords
            if keyword.arg == "disabled"
        )
        self.assertIsInstance(disabled, ast.UnaryOp)
        self.assertIsInstance(disabled.op, ast.Not)

    def test_restore_helpers_are_not_called_outside_button_blocks(self):
        protected_calls = {
            "inspect_database_backup": "Verify Selected Database Backup",
            "restore_database_backup": "Restore Selected Database Backup",
        }
        for function_name, button_label in protected_calls.items():
            all_calls = [
                call
                for call in ast.walk(self.tree)
                if isinstance(call, ast.Call) and _call_name(call) == function_name
            ]
            button_calls = [
                call
                for call in ast.walk(_button_block(self.tree, button_label))
                if isinstance(call, ast.Call) and _call_name(call) == function_name
            ]
            self.assertEqual(len(all_calls), 1)
            self.assertEqual(len(button_calls), 1)


if __name__ == "__main__":
    unittest.main()
