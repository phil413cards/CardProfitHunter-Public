from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database


REAL_DB_PATH = database.DB_PATH


class DatabaseSchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "data" / "schema-validation.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)

    def raw_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def table_names(self) -> set[str]:
        with self.raw_connection() as conn:
            return {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }

    def test_fresh_empty_database_initializes_normally(self):
        database.init_db()

        with self.raw_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertTrue(set(database.REQUIRED_SCHEMA_COLUMNS).issubset(self.table_names()))

    def test_unversioned_database_with_missing_column_fails_without_adoption(self):
        database.init_db()
        database.save_search(
            "Preserved Search",
            "private preserved query",
            25,
            "newlyListed",
            100.0,
            "183454",
        )
        with self.raw_connection() as conn:
            conn.execute(
                "ALTER TABLE saved_searches RENAME COLUMN query TO removed_query"
            )
            conn.execute("PRAGMA user_version = 0")

        with self.assertRaisesRegex(sqlite3.DatabaseError, "not compatible") as raised:
            database.init_db()

        with self.raw_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            row = conn.execute(
                "SELECT name, removed_query FROM saved_searches"
            ).fetchone()
        self.assertEqual(version, 0)
        self.assertEqual(row, ("Preserved Search", "private preserved query"))
        self.assertNotIn("removed_query", str(raised.exception))
        self.assertNotIn("private preserved query", str(raised.exception))

    def test_unrelated_unversioned_database_is_not_converted(self):
        with self.raw_connection() as conn:
            conn.execute("CREATE TABLE private_notes (value TEXT NOT NULL)")
            conn.execute("INSERT INTO private_notes(value) VALUES (?)", ("private",))

        with self.assertRaisesRegex(sqlite3.DatabaseError, "not compatible") as raised:
            database.init_db()

        with self.raw_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            value = conn.execute("SELECT value FROM private_notes").fetchone()[0]
        self.assertEqual(version, 0)
        self.assertEqual(value, "private")
        self.assertEqual(self.table_names(), {"private_notes"})
        self.assertNotIn("private_notes", str(raised.exception))

    def test_current_schema_with_missing_table_fails_without_recreating_it(self):
        database.init_db()
        with self.raw_connection() as conn:
            conn.execute("DROP TABLE watchlist")

        with self.assertRaisesRegex(sqlite3.DatabaseError, "not compatible"):
            database.init_db()

        with self.raw_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertNotIn("watchlist", self.table_names())

    def test_unversioned_schema_without_required_foreign_key_is_rejected(self):
        database.init_db()
        with self.raw_connection() as conn:
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
            conn.execute("PRAGMA user_version = 0")

        with self.assertRaisesRegex(sqlite3.DatabaseError, "not compatible"):
            database.init_db()

        with self.raw_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_list(search_runs)").fetchall()
        self.assertEqual(version, 0)
        self.assertEqual(foreign_keys, [])

    def test_wrong_required_index_shape_is_rejected(self):
        database.init_db()
        with self.raw_connection() as conn:
            conn.execute("DROP INDEX idx_opportunity_batch")
            conn.execute("DROP INDEX idx_opportunity_created")
            conn.execute(
                "CREATE INDEX idx_opportunity_batch ON opportunity_snapshots(title)"
            )

        with self.assertRaisesRegex(sqlite3.DatabaseError, "not compatible"):
            database.init_db()

        with self.raw_connection() as conn:
            columns = [
                str(row[2])
                for row in conn.execute(
                    "PRAGMA index_info(idx_opportunity_batch)"
                ).fetchall()
            ]
        self.assertEqual(columns, ["title"])
        with self.raw_connection() as conn:
            recreated = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'index' AND name = 'idx_opportunity_created'"
            ).fetchone()
        self.assertIsNone(recreated)

    def test_missing_required_index_is_repaired_without_data_loss(self):
        database.init_db()
        database.save_search(
            "Index Repair Search",
            "preserve this query",
            25,
            "newlyListed",
            None,
            "",
        )
        with self.raw_connection() as conn:
            conn.execute("DROP INDEX idx_opportunity_created")

        database.init_db()

        with self.raw_connection() as conn:
            columns = [
                str(row[2])
                for row in conn.execute(
                    "PRAGMA index_info(idx_opportunity_created)"
                ).fetchall()
            ]
            query = conn.execute(
                "SELECT query FROM saved_searches WHERE name = ?",
                ("Index Repair Search",),
            ).fetchone()[0]
        self.assertEqual(columns, ["created_at"])
        self.assertEqual(query, "preserve this query")

    def test_only_temporary_database_path_is_used(self):
        database.init_db()

        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(str(self.db_path).startswith(str(self.root)))


if __name__ == "__main__":
    unittest.main()
