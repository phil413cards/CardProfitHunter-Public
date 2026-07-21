import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database


REAL_DB_PATH = database.DB_PATH


class DatabaseLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "lifecycle-test.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        database.init_db()

    def test_uses_only_the_patched_temporary_database(self):
        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(self.db_path.exists())

    def test_foreign_keys_are_enabled_on_every_connection(self):
        for _ in range(2):
            with database.connect() as conn:
                enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(enabled, 1)

    def test_foreign_key_enforcement_rejects_invalid_child_reference(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with database.connect() as conn:
                conn.execute(
                    """INSERT INTO search_runs(
                           saved_search_id, query, result_count, created_at
                       ) VALUES (?, ?, ?, ?)""",
                    (999999, "invalid parent", 0, database.utc_now()),
                )

        with database.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
        self.assertEqual(count, 0)

    def test_busy_timeout_is_applied_on_every_connection(self):
        for _ in range(2):
            with database.connect() as conn:
                timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(timeout, database.BUSY_TIMEOUT_MS)

    def test_fresh_and_repeat_initialization_keep_schema_version(self):
        with database.connect() as conn:
            initial_version = conn.execute("PRAGMA user_version").fetchone()[0]

        database.init_db()
        database.init_db()

        with database.connect() as conn:
            repeated_version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(initial_version, database.SCHEMA_VERSION)
        self.assertEqual(repeated_version, database.SCHEMA_VERSION)

    def test_repeat_initialization_preserves_existing_data(self):
        database.save_search(
            "Lifecycle Search",
            "test card",
            25,
            "newlyListed",
            100.0,
            "183454",
        )

        database.init_db()
        database.init_db()

        with database.connect() as conn:
            stored = conn.execute(
                "SELECT name, query, category_ids FROM saved_searches"
            ).fetchone()
        self.assertEqual(stored["name"], "Lifecycle Search")
        self.assertEqual(stored["query"], "test card")
        self.assertEqual(stored["category_ids"], "183454")

    def test_unversioned_existing_database_is_adopted_without_data_loss(self):
        database.save_search(
            "Unversioned Search",
            "existing card",
            25,
            "newlyListed",
            None,
            "",
        )
        with database.connect() as conn:
            conn.execute("PRAGMA user_version = 0")

        database.init_db()

        with database.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            stored = conn.execute(
                "SELECT query FROM saved_searches WHERE name = ?",
                ("Unversioned Search",),
            ).fetchone()
        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertEqual(stored["query"], "existing card")

    def test_failed_transaction_is_rolled_back(self):
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with database.connect() as conn:
                conn.execute(
                    """INSERT INTO saved_searches(
                           name, query, limit_count, sort_order, category_ids,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "Rollback Search",
                        "rollback card",
                        10,
                        "newlyListed",
                        "",
                        database.utc_now(),
                        database.utc_now(),
                    ),
                )
                raise RuntimeError("force rollback")

        with database.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM saved_searches WHERE name = ?",
                ("Rollback Search",),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_newer_schema_version_fails_closed(self):
        newer_version = database.SCHEMA_VERSION + 1
        with database.connect() as conn:
            conn.execute(f"PRAGMA user_version = {newer_version}")

        with self.assertRaisesRegex(sqlite3.DatabaseError, "newer"):
            database.init_db()

        with sqlite3.connect(self.db_path) as conn:
            stored_version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(stored_version, newer_version)


if __name__ == "__main__":
    unittest.main()
