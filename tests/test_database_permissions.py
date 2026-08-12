import os
import sqlite3
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import database


REAL_DB_PATH = database.DB_PATH


@unittest.skipUnless(os.name == "posix", "POSIX permission checks require POSIX")
class DatabasePermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "private-data" / "card-profit-hunter-test.db"
        self.backup_dir = self.root / "private-output" / "database_backups"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)

    @staticmethod
    def _mode(path):
        return stat.S_IMODE(path.stat().st_mode)

    def _save_search(self, name):
        database.save_search(
            name,
            f"query for {name}",
            25,
            "newlyListed",
            100.0,
            "183454",
        )

    def test_fresh_database_directory_and_file_are_private(self):
        database.init_db()

        self.assertEqual(self._mode(self.db_path.parent), 0o700)
        self.assertEqual(self._mode(self.db_path), 0o600)

    def test_existing_broad_permissions_are_repaired_without_data_loss(self):
        database.init_db()
        self._save_search("Private Search")
        self.db_path.parent.chmod(0o755)
        self.db_path.chmod(0o644)

        with database.connect() as conn:
            stored = conn.execute(
                "SELECT name FROM saved_searches WHERE name = ?",
                ("Private Search",),
            ).fetchone()

        self.assertEqual(stored["name"], "Private Search")
        self.assertEqual(self._mode(self.db_path.parent), 0o700)
        self.assertEqual(self._mode(self.db_path), 0o600)

    def test_every_connection_repairs_permissions(self):
        database.init_db()
        for _ in range(2):
            self.db_path.parent.chmod(0o755)
            self.db_path.chmod(0o666)
            with database.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            self.assertEqual(self._mode(self.db_path.parent), 0o700)
            self.assertEqual(self._mode(self.db_path), 0o600)

    def test_symlink_database_path_is_rejected_without_touching_target(self):
        target = self.root / "external-target.db"
        sentinel = b"private target contents"
        target.write_bytes(sentinel)
        self.db_path.parent.mkdir(parents=True)
        self.db_path.symlink_to(target)

        with self.assertRaisesRegex(sqlite3.OperationalError, "could not be secured"):
            database.init_db()

        self.assertEqual(target.read_bytes(), sentinel)
        self.assertTrue(self.db_path.is_symlink())

    def test_symlink_database_directory_is_rejected_without_creating_database(self):
        external_directory = self.root / "external-data"
        external_directory.mkdir()
        self.db_path.parent.symlink_to(external_directory, target_is_directory=True)

        with self.assertRaisesRegex(sqlite3.OperationalError, "could not be secured"):
            database.init_db()

        self.assertFalse((external_directory / self.db_path.name).exists())

    def test_non_file_database_path_is_rejected(self):
        self.db_path.mkdir(parents=True)

        with self.assertRaisesRegex(sqlite3.OperationalError, "could not be secured"):
            database.init_db()

    def test_backup_directory_and_file_permissions_are_private_and_repaired(self):
        database.init_db()
        self.backup_dir.mkdir(parents=True)
        self.backup_dir.chmod(0o755)

        backup_path = database.create_database_backup(self.backup_dir)

        self.assertIsNotNone(backup_path)
        self.assertEqual(self._mode(self.backup_dir), 0o700)
        self.assertEqual(self._mode(backup_path), 0o600)

    def test_symlink_backup_directory_is_rejected_safely(self):
        database.init_db()
        external_directory = self.root / "external-backups"
        external_directory.mkdir()
        self.backup_dir.parent.mkdir(parents=True)
        self.backup_dir.symlink_to(external_directory, target_is_directory=True)

        with self.assertRaises(database.DatabaseMaintenanceError) as raised:
            database.create_database_backup(self.backup_dir)

        self.assertEqual(
            str(raised.exception),
            "Database backup could not be created.",
        )
        self.assertEqual(list(external_directory.iterdir()), [])

    def test_restore_keeps_database_and_directory_private(self):
        database.init_db()
        self._save_search("Backup Search")
        source = database.create_database_backup(self.backup_dir)
        with database.connect() as conn:
            conn.execute("DELETE FROM saved_searches")
        self.db_path.parent.chmod(0o755)
        self.db_path.chmod(0o644)

        database.restore_database_backup(
            source,
            self.backup_dir,
            confirmed=True,
        )

        self.assertEqual(self._mode(self.db_path.parent), 0o700)
        self.assertEqual(self._mode(self.db_path), 0o600)
        self.assertEqual(self._mode(self.backup_dir), 0o700)
        for backup_path in self.backup_dir.glob("*.db"):
            self.assertEqual(self._mode(backup_path), 0o600)

    def test_only_temporary_paths_are_used(self):
        self.assertEqual(database.DB_PATH, self.db_path)
        self.assertNotEqual(database.DB_PATH, REAL_DB_PATH)
        self.assertTrue(str(self.db_path).startswith(str(self.root)))
        self.assertTrue(str(self.backup_dir).startswith(str(self.root)))


if __name__ == "__main__":
    unittest.main()
