from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator

import pandas as pd

from seller_eligibility import evaluate_seller_eligibility
from valuation_safety import (
    valuation_notes_are_non_actionable,
    valuation_provenance_flags,
)

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "card_profit_hunter.db"
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_DATABASE_MODE = 0o600
SCHEMA_V1_REQUIRED_SCHEMA_COLUMNS = {
    "saved_searches": frozenset({
        "id", "name", "query", "limit_count", "sort_order", "max_price",
        "category_ids", "created_at", "updated_at",
    }),
    "search_runs": frozenset({
        "id", "saved_search_id", "query", "result_count", "created_at",
    }),
    "watchlist": frozenset({
        "id", "item_id", "title", "item_url", "total_price",
        "recommended_action", "expected_profit", "expected_roi_pct", "notes",
        "payload_json", "created_at",
    }),
    "opportunity_snapshots": frozenset({
        "id", "batch_id", "saved_search_id", "saved_search_name", "query",
        "item_id", "title", "item_url", "total_price", "recommended_action",
        "total_score", "expected_profit", "expected_roi_pct", "suggested_offer",
        "payload_json", "created_at",
    }),
}
REQUIRED_SCHEMA_COLUMNS = {
    **SCHEMA_V1_REQUIRED_SCHEMA_COLUMNS,
    "opportunity_batches": frozenset({
        "batch_id", "status", "attempted_count", "successful_count",
        "empty_count", "failed_count", "result_count", "completed_at",
    }),
}
REQUIRED_SCHEMA_FOREIGN_KEYS = {
    "search_runs": frozenset({
        ("saved_search_id", "saved_searches", "id", "SET NULL"),
    }),
    "opportunity_snapshots": frozenset({
        ("saved_search_id", "saved_searches", "id", "SET NULL"),
    }),
}
REQUIRED_SCHEMA_INDEXES = {
    "idx_opportunity_batch": ("opportunity_snapshots", ("batch_id",)),
    "idx_opportunity_created": ("opportunity_snapshots", ("created_at",)),
}

ACTIONABLE_ACTIONS = frozenset({
    "BUY",
    "OFFER",
    "BUY_RAW_FLIP",
    "BUY_GRADE_PSA",
})
ACTIONABLE_ACTIONS_SQL = "'BUY','OFFER','BUY_RAW_FLIP','BUY_GRADE_PSA'"
DIRECT_BUY_ACTIONS_SQL = "'BUY','BUY_RAW_FLIP','BUY_GRADE_PSA'"
ALLOWED_BATCH_STATUSES = frozenset({"success", "empty", "partial", "failed"})

NON_ACTIONABLE_FINANCIAL_FIELDS = {
    "best_expected_profit",
    "best_expected_roi_pct",
    "raw_flip_profit",
    "raw_flip_roi_pct",
    "psa_expected_profit",
    "psa_expected_roi_pct",
    "psa_expected_sale_value",
    "max_buy_price_raw_flip",
    "max_buy_price_psa_flip",
    "suggested_offer",
    "raw_market_value",
    "psa9_value",
    "psa10_value",
    "gem_rate_estimate",
    "psa9_rate_estimate",
}

_LATEST_RECORDED_BATCH_ID_SQL = """
    SELECT batch_id
    FROM opportunity_batches
    ORDER BY completed_at DESC, rowid DESC
    LIMIT 1
"""

_LATEST_SNAPSHOT_BATCH_ID_SQL = """
    SELECT batch_id
    FROM opportunity_snapshots
    GROUP BY batch_id
    ORDER BY MAX(id) DESC
    LIMIT 1
"""

_PROTECTED_RETENTION_BATCH_IDS_SQL = f"""
    SELECT batch_id FROM ({_LATEST_RECORDED_BATCH_ID_SQL})
    UNION
    SELECT batch_id FROM ({_LATEST_SNAPSHOT_BATCH_ID_SQL})
"""

_OLD_OPPORTUNITY_BATCHES_SQL = f"""
    SELECT batch_id
    FROM opportunity_snapshots
    GROUP BY batch_id
    HAVING MAX(created_at) < ?
       AND batch_id NOT IN (
           {_PROTECTED_RETENTION_BATCH_IDS_SQL}
       )
"""

_OLD_RECORDED_BATCHES_SQL = f"""
    SELECT batch_id
    FROM opportunity_batches
    WHERE completed_at < ?
      AND batch_id NOT IN (
          {_PROTECTED_RETENTION_BATCH_IDS_SQL}
      )
"""


class DatabaseMaintenanceError(RuntimeError):
    """A sanitized database-maintenance error safe for the local UI."""


def _append_payload_flags(payload: dict, flags: tuple[str, ...]) -> None:
    existing = payload.get("flags", "")
    values = (
        [part for part in existing.split(";") if part]
        if isinstance(existing, str)
        else []
    )
    for flag in flags:
        if flag not in values:
            values.append(flag)
    payload["flags"] = ";".join(values)


def _scrub_non_actionable_payload(payload: dict) -> None:
    payload["best_path"] = "NONE"
    for field in NON_ACTIONABLE_FINANCIAL_FIELDS:
        payload[field] = None


def _snapshot_payload(row: dict) -> dict:
    payload = dict(row)
    action = str(payload.get("recommended_action", ""))
    if action in ACTIONABLE_ACTIONS:
        seller = evaluate_seller_eligibility(payload)
        rejection_flags = list(seller.flags)
        if valuation_notes_are_non_actionable(payload.get("valuation_notes")):
            rejection_flags.append("non_actionable_valuation")
        rejection_flags.extend(valuation_provenance_flags(payload))
        if rejection_flags:
            action = "PASS"
            payload["recommended_action"] = action
            payload["matched_card"] = ""
            payload["match_strength"] = 0.0
            payload["valuation_available"] = False
            payload["financially_verified"] = False
            _append_payload_flags(payload, tuple(rejection_flags))
    if action not in ACTIONABLE_ACTIONS:
        _scrub_non_actionable_payload(payload)
    return payload


def _decode_payload(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _stored_payload_is_actionable(payload_json: Any, stored_action: Any) -> int:
    action = str(stored_action or "")
    if action not in ACTIONABLE_ACTIONS:
        return 0
    payload = _decode_payload(payload_json)
    if str(payload.get("recommended_action", "")) != action:
        return 0
    if not evaluate_seller_eligibility(payload).eligible:
        return 0
    if valuation_notes_are_non_actionable(payload.get("valuation_notes")):
        return 0
    return int(not valuation_provenance_flags(payload))


def _sanitize_persisted_actions(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.copy()
    if safe.empty or "recommended_action" not in safe.columns:
        return safe
    for index, row in safe.iterrows():
        action = str(row.get("recommended_action", ""))
        if action in ACTIONABLE_ACTIONS and not _stored_payload_is_actionable(
            row.get("payload_json"),
            action,
        ):
            safe.at[index, "recommended_action"] = "PASS"
            for field in (
                "expected_profit",
                "expected_roi_pct",
                "suggested_offer",
            ):
                if field in safe.columns:
                    safe.at[index, field] = None
    return safe


def _prepare_private_directory(path: Path) -> Path:
    directory = Path(path)
    try:
        if directory.is_symlink():
            raise OSError
        directory.mkdir(
            mode=PRIVATE_DIRECTORY_MODE,
            parents=True,
            exist_ok=True,
        )
        if directory.is_symlink() or not directory.is_dir():
            raise OSError
        directory.chmod(PRIVATE_DIRECTORY_MODE)
        return directory
    except (OSError, RuntimeError, ValueError):
        raise sqlite3.OperationalError(
            "Local database path could not be secured."
        ) from None


def _prepare_private_database_file(path: Path) -> Path:
    database_path = Path(path)
    _prepare_private_directory(database_path.parent)
    descriptor: int | None = None
    try:
        if database_path.is_symlink():
            raise OSError
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(database_path, flags, PRIVATE_DATABASE_MODE)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, PRIVATE_DATABASE_MODE)
        else:
            database_path.chmod(PRIVATE_DATABASE_MODE)
        return database_path
    except (OSError, RuntimeError, ValueError):
        raise sqlite3.OperationalError(
            "Local database path could not be secured."
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _open_database(path: Path) -> sqlite3.Connection:
    database_path = _prepare_private_database_file(path)
    conn = sqlite3.connect(database_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.create_function(
            "opportunity_actionable",
            2,
            _stored_payload_is_actionable,
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn
    except BaseException:
        conn.close()
        raise


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _open_database(DB_PATH)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _reserve_backup_path(backup_dir: Path) -> Path:
    suffix = DB_PATH.suffix or ".db"
    base_name = f"{DB_PATH.stem}-backup-{_backup_timestamp()}"
    collision = 0
    while True:
        collision_suffix = "" if collision == 0 else f"-{collision}"
        candidate = backup_dir / f"{base_name}{collision_suffix}{suffix}"
        try:
            candidate.touch(mode=0o600, exist_ok=False)
            return candidate
        except FileExistsError:
            collision += 1


def _backup_integrity_is_valid(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    return len(rows) == 1 and str(rows[0][0]).lower() == "ok"


def _database_table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _schema_core_is_compatible(
    conn: sqlite3.Connection,
    tables: set[str] | None = None,
    required_schema_columns: dict[str, frozenset[str]] | None = None,
) -> bool:
    available_tables = _database_table_names(conn) if tables is None else tables
    required_columns_by_table = (
        REQUIRED_SCHEMA_COLUMNS
        if required_schema_columns is None
        else required_schema_columns
    )
    if not set(required_columns_by_table).issubset(available_tables):
        return False

    for table, required_columns in required_columns_by_table.items():
        actual_columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not required_columns.issubset(actual_columns):
            return False

    for table, required_foreign_keys in REQUIRED_SCHEMA_FOREIGN_KEYS.items():
        actual_foreign_keys = {
            (str(row[3]), str(row[2]), str(row[4]), str(row[6]).upper())
            for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        if not required_foreign_keys.issubset(actual_foreign_keys):
            return False
    return True


def _schema_indexes_are_compatible(
    conn: sqlite3.Connection,
    allow_missing: bool = False,
) -> bool:
    for index_name, schema in REQUIRED_SCHEMA_INDEXES.items():
        required_table, required_columns = schema
        row = conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        if row is None:
            if allow_missing:
                continue
            return False
        actual_columns = tuple(
            str(index_row[2])
            for index_row in conn.execute(
                f"PRAGMA index_info({index_name})"
            ).fetchall()
        )
        if str(row[0]) != required_table or actual_columns != required_columns:
            return False
    return True


def _schema_is_compatible(conn: sqlite3.Connection) -> bool:
    return _schema_core_is_compatible(conn) and _schema_indexes_are_compatible(conn)


def _schema_v1_is_compatible(
    conn: sqlite3.Connection,
    tables: set[str] | None = None,
    allow_missing_indexes: bool = False,
) -> bool:
    return _schema_core_is_compatible(
        conn,
        tables,
        SCHEMA_V1_REQUIRED_SCHEMA_COLUMNS,
    ) and _schema_indexes_are_compatible(
        conn,
        allow_missing=allow_missing_indexes,
    )


def _raise_incompatible_schema() -> None:
    raise sqlite3.DatabaseError(
        "Database schema is not compatible with this application version."
    )


def create_database_backup(backup_dir: Path) -> Path | None:
    destination_path: Path | None = None
    try:
        if DB_PATH.is_symlink():
            raise OSError("Database source is not a file.")
        if not DB_PATH.exists():
            return None
        if not DB_PATH.is_file():
            raise OSError("Database source is not a file.")
        destination_dir = _prepare_private_directory(Path(backup_dir))
        destination_path = _reserve_backup_path(destination_dir)

        with closing(_open_database(DB_PATH)) as source:
            with closing(_open_database(destination_path)) as destination:
                source.backup(destination)
                destination.commit()
                if not _backup_integrity_is_valid(destination):
                    raise sqlite3.DatabaseError("Backup integrity verification failed.")
        return destination_path
    except Exception:
        if destination_path is not None:
            try:
                destination_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise DatabaseMaintenanceError("Database backup could not be created.") from None


def _resolve_local_backup(backup_path: Path, backup_dir: Path) -> Path:
    try:
        source = Path(backup_path)
        directory = Path(backup_dir)
        if directory.is_symlink() or not directory.is_dir():
            raise OSError
        if source.is_symlink() or not source.is_file():
            raise OSError
        resolved_directory = directory.resolve(strict=True)
        resolved_source = source.resolve(strict=True)
        if resolved_source.parent != resolved_directory:
            raise OSError
        if resolved_source.suffix.lower() != ".db":
            raise OSError
        if DB_PATH.exists() and os.path.samefile(resolved_source, DB_PATH):
            raise OSError
        return resolved_source
    except (OSError, RuntimeError, ValueError):
        raise DatabaseMaintenanceError(
            "Database backup could not be verified."
        ) from None


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve(strict=True).as_uri()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn
    except BaseException:
        conn.close()
        raise


def _verified_backup_metadata(path: Path, filename: str) -> dict[str, object]:
    with closing(_open_readonly_database(path)) as conn:
        if not _backup_integrity_is_valid(conn):
            raise DatabaseMaintenanceError(
                "Database backup could not be verified."
            )
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == SCHEMA_VERSION:
            schema_is_compatible = _schema_is_compatible(conn)
        elif version == LEGACY_SCHEMA_VERSION:
            schema_is_compatible = _schema_v1_is_compatible(conn)
        else:
            schema_is_compatible = False
        if not schema_is_compatible:
            raise DatabaseMaintenanceError(
                "Database backup is not compatible with this application version."
            )
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise DatabaseMaintenanceError(
                "Database backup could not be verified."
            )
    return {
        "filename": filename,
        "size_bytes": int(path.stat().st_size),
        "schema_version": version,
        "integrity": "ok",
    }


def inspect_database_backup(
    backup_path: Path,
    backup_dir: Path,
) -> dict[str, object]:
    try:
        source = _resolve_local_backup(backup_path, backup_dir)
        return _verified_backup_metadata(source, source.name)
    except DatabaseMaintenanceError:
        raise
    except Exception:
        raise DatabaseMaintenanceError(
            "Database backup could not be verified."
        ) from None


def _remove_restore_artifacts(temporary_path: Path | None) -> None:
    if temporary_path is None:
        return
    for path in (
        temporary_path,
        Path(f"{temporary_path}-journal"),
        Path(f"{temporary_path}-wal"),
        Path(f"{temporary_path}-shm"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def restore_database_backup(
    backup_path: Path,
    backup_dir: Path,
    confirmed: bool = False,
) -> dict[str, object]:
    if confirmed is not True:
        raise DatabaseMaintenanceError(
            "Database restore requires explicit confirmation."
        )

    try:
        source = _resolve_local_backup(backup_path, backup_dir)
        source_metadata = _verified_backup_metadata(source, source.name)
    except DatabaseMaintenanceError:
        raise
    except Exception:
        raise DatabaseMaintenanceError(
            "Database backup could not be verified."
        ) from None
    temporary_path: Path | None = None
    try:
        if DB_PATH.is_symlink() or not DB_PATH.is_file():
            raise OSError("Current database is unavailable.")

        safety_backup = create_database_backup(backup_dir)
        if safety_backup is None:
            raise OSError("Safety backup is unavailable.")

        with NamedTemporaryFile(
            mode="wb",
            prefix=f".{DB_PATH.name}.restore-",
            suffix=".db",
            dir=DB_PATH.parent,
            delete=False,
        ) as reserved:
            temporary_path = Path(reserved.name)

        with closing(_open_readonly_database(source)) as source_conn:
            with closing(_open_database(temporary_path)) as destination_conn:
                source_conn.backup(destination_conn)
                _initialize_schema(destination_conn)
                destination_conn.commit()

        _verified_backup_metadata(temporary_path, source.name)
        os.chmod(temporary_path, 0o600)
        with temporary_path.open("rb") as restored_file:
            os.fsync(restored_file.fileno())
        os.replace(temporary_path, DB_PATH)
        temporary_path = None
        return {
            "restored_from": source_metadata["filename"],
            "schema_version": SCHEMA_VERSION,
            "safety_backup_path": safety_backup,
        }
    except Exception:
        _remove_restore_artifacts(temporary_path)
        raise DatabaseMaintenanceError(
            "Database restore could not be completed."
        ) from None


def _normalize_retention_cutoff(cutoff: Any) -> str:
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise DatabaseMaintenanceError(
            "Retention cutoff must be a timezone-aware past datetime."
        )
    try:
        if cutoff.utcoffset() is None:
            raise ValueError
        normalized = cutoff.astimezone(timezone.utc)
    except Exception:
        raise DatabaseMaintenanceError(
            "Retention cutoff must be a timezone-aware past datetime."
        ) from None
    if normalized >= datetime.now(timezone.utc):
        raise DatabaseMaintenanceError(
            "Retention cutoff must be a timezone-aware past datetime."
        )
    return normalized.isoformat(timespec="seconds")


def _retention_counts(conn: sqlite3.Connection, cutoff_text: str) -> dict[str, int]:
    search_runs = conn.execute(
        "SELECT COUNT(*) FROM search_runs WHERE created_at < ?",
        (cutoff_text,),
    ).fetchone()[0]
    opportunities = conn.execute(
        f"""SELECT COUNT(*)
            FROM opportunity_snapshots
            WHERE batch_id IN ({_OLD_OPPORTUNITY_BATCHES_SQL})""",
        (cutoff_text,),
    ).fetchone()[0]
    batches = conn.execute(
        f"""SELECT COUNT(*)
            FROM opportunity_batches
            WHERE batch_id IN ({_OLD_RECORDED_BATCHES_SQL})""",
        (cutoff_text,),
    ).fetchone()[0]
    return {
        "search_runs": int(search_runs),
        "opportunity_snapshots": int(opportunities),
        "opportunity_batches": int(batches),
    }


def preview_history_retention(cutoff: datetime) -> dict[str, int]:
    cutoff_text = _normalize_retention_cutoff(cutoff)
    try:
        with connect() as conn:
            return _retention_counts(conn, cutoff_text)
    except DatabaseMaintenanceError:
        raise
    except Exception:
        raise DatabaseMaintenanceError(
            "History retention preview could not be completed."
        ) from None


def apply_history_retention(
    cutoff: datetime,
    backup_dir: Path,
    confirmed: bool = False,
) -> dict[str, object]:
    if confirmed is not True:
        raise DatabaseMaintenanceError(
            "Retention cleanup requires explicit confirmation."
        )
    cutoff_text = _normalize_retention_cutoff(cutoff)
    backup_path = create_database_backup(backup_dir)
    if backup_path is None:
        raise DatabaseMaintenanceError(
            "Retention cleanup requires an existing database backup."
        )

    try:
        with connect() as conn:
            opportunity_cursor = conn.execute(
                f"""DELETE FROM opportunity_snapshots
                    WHERE batch_id IN ({_OLD_OPPORTUNITY_BATCHES_SQL})""",
                (cutoff_text,),
            )
            batch_cursor = conn.execute(
                f"""DELETE FROM opportunity_batches
                    WHERE batch_id IN ({_OLD_RECORDED_BATCHES_SQL})""",
                (cutoff_text,),
            )
            search_cursor = conn.execute(
                "DELETE FROM search_runs WHERE created_at < ?",
                (cutoff_text,),
            )
            deleted = {
                "search_runs": max(int(search_cursor.rowcount), 0),
                "opportunity_snapshots": max(int(opportunity_cursor.rowcount), 0),
                "opportunity_batches": max(int(batch_cursor.rowcount), 0),
                "backup_path": backup_path,
            }
    except DatabaseMaintenanceError:
        raise
    except Exception:
        raise DatabaseMaintenanceError(
            "History retention cleanup could not be completed."
        ) from None
    return deleted


def _initialize_schema(conn: sqlite3.Connection) -> None:
    current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current_version > SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            "Database schema version is newer than this application supports."
        )

    existing_tables = _database_table_names(conn)
    if current_version == SCHEMA_VERSION:
        if not _schema_core_is_compatible(
            conn,
            existing_tables,
        ) or not _schema_indexes_are_compatible(conn, allow_missing=True):
            _raise_incompatible_schema()
    elif current_version in (0, LEGACY_SCHEMA_VERSION) and existing_tables:
        if not _schema_v1_is_compatible(
            conn,
            existing_tables,
            allow_missing_indexes=True,
        ):
            _raise_incompatible_schema()
    elif current_version not in (0, LEGACY_SCHEMA_VERSION):
        _raise_incompatible_schema()

    conn.executescript(
        """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                query TEXT NOT NULL,
                limit_count INTEGER NOT NULL DEFAULT 50,
                sort_order TEXT NOT NULL DEFAULT 'newlyListed',
                max_price REAL,
                category_ids TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS search_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_search_id INTEGER,
                query TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(saved_search_id) REFERENCES saved_searches(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT,
                title TEXT NOT NULL,
                item_url TEXT,
                total_price REAL,
                recommended_action TEXT,
                expected_profit REAL,
                expected_roi_pct REAL,
                notes TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                saved_search_id INTEGER,
                saved_search_name TEXT,
                query TEXT NOT NULL,
                item_id TEXT,
                title TEXT NOT NULL,
                item_url TEXT,
                total_price REAL,
                recommended_action TEXT,
                total_score REAL,
                expected_profit REAL,
                expected_roi_pct REAL,
                suggested_offer REAL,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(saved_search_id) REFERENCES saved_searches(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS opportunity_batches (
                batch_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                attempted_count INTEGER NOT NULL,
                successful_count INTEGER NOT NULL,
                empty_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                result_count INTEGER NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_opportunity_batch ON opportunity_snapshots(batch_id);
            CREATE INDEX IF NOT EXISTS idx_opportunity_created ON opportunity_snapshots(created_at);
        """
    )
    if not _schema_is_compatible(conn):
        _raise_incompatible_schema()
    if current_version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def init_db() -> None:
    with connect() as conn:
        _initialize_schema(conn)


def list_saved_searches() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM saved_searches ORDER BY name", conn)


def save_search(name: str, query: str, limit_count: int, sort_order: str,
                max_price: float | None, category_ids: str) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO saved_searches(name, query, limit_count, sort_order, max_price, category_ids, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              query=excluded.query,
              limit_count=excluded.limit_count,
              sort_order=excluded.sort_order,
              max_price=excluded.max_price,
              category_ids=excluded.category_ids,
              updated_at=excluded.updated_at
            """,
            (name.strip(), query.strip(), int(limit_count), sort_order, max_price, category_ids.strip(), now, now),
        )


def delete_saved_search(search_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM saved_searches WHERE id = ?", (int(search_id),))


def log_search_run(query: str, result_count: int, saved_search_id: int | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO search_runs(saved_search_id, query, result_count, created_at) VALUES (?, ?, ?, ?)",
            (saved_search_id, query, int(result_count), utc_now()),
        )


def list_search_runs(limit: int = 50) -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """SELECT r.id, s.name AS saved_search, r.query, r.result_count, r.created_at
               FROM search_runs r LEFT JOIN saved_searches s ON s.id=r.saved_search_id
               ORDER BY r.id DESC LIMIT ?""",
            conn,
            params=(int(limit),),
        )


def add_watchlist_row(row: dict, notes: str = "") -> None:
    payload = _snapshot_payload(row)
    action = str(payload.get("recommended_action", ""))
    actionable = action in ACTIONABLE_ACTIONS
    with connect() as conn:
        conn.execute(
            """INSERT INTO watchlist(item_id, title, item_url, total_price, recommended_action,
               expected_profit, expected_roi_pct, notes, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(payload.get("item_id", "")), str(payload.get("title", "")), str(payload.get("item_url", "")),
                float(payload.get("total_price", 0) or 0), action,
                float(payload.get("best_expected_profit", 0) or 0) if actionable else None,
                float(payload.get("best_expected_roi_pct", 0) or 0) if actionable else None,
                notes, json.dumps(payload, default=str), utc_now(),
            ),
        )


def list_watchlist() -> pd.DataFrame:
    with connect() as conn:
        frame = pd.read_sql_query(
            """SELECT id, title, total_price, recommended_action, expected_profit,
               expected_roi_pct, notes, item_url, payload_json, created_at
               FROM watchlist ORDER BY id DESC""", conn
        )
    return _sanitize_persisted_actions(frame).drop(
        columns=["payload_json"],
        errors="ignore",
    )


def delete_watchlist_item(item_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE id = ?", (int(item_id),))


def _batch_count(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError from None
    if parsed < 0 or not numeric.is_integer():
        raise ValueError
    return parsed


def _batch_completed_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    try:
        parsed = datetime.fromisoformat(value.strip())
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        normalized = parsed.astimezone(timezone.utc)
        if normalized > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError
        return normalized.isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        raise ValueError from None


def save_opportunity_batch_outcome(
    batch_id: str,
    *,
    status: str,
    attempted_count: int,
    successful_count: int,
    empty_count: int,
    failed_count: int,
    result_count: int,
    completed_at: str,
) -> None:
    """Persist one sanitized Daily Buy Board outcome without error details."""
    try:
        if not isinstance(batch_id, str) or not isinstance(status, str):
            raise ValueError
        normalized_batch_id = batch_id.strip()
        normalized_status = status.strip().lower()
        attempted = _batch_count(attempted_count)
        successful = _batch_count(successful_count)
        empty = _batch_count(empty_count)
        failed = _batch_count(failed_count)
        results = _batch_count(result_count)
        completed = _batch_completed_at(completed_at)
        if (
            not normalized_batch_id
            or len(normalized_batch_id) > 128
            or not all(
                character.isalnum() or character in {"-", "_"}
                for character in normalized_batch_id
            )
            or normalized_status not in ALLOWED_BATCH_STATUSES
            or attempted == 0
            or successful + failed != attempted
            or empty > successful
        ):
            raise ValueError
        if failed > 0 and successful == 0:
            expected_status = "failed"
        elif failed > 0:
            expected_status = "partial"
        elif successful > 0 and empty >= successful:
            expected_status = "empty"
        else:
            expected_status = "success"
        if normalized_status != expected_status:
            raise ValueError
        if normalized_status in {"empty", "failed"} and results != 0:
            raise ValueError
        if successful == 0 and results != 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Daily Buy Board outcome is invalid.") from None

    with connect() as conn:
        conn.execute(
            """INSERT INTO opportunity_batches(
                   batch_id, status, attempted_count, successful_count,
                   empty_count, failed_count, result_count, completed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(batch_id) DO UPDATE SET
                   status=excluded.status,
                   attempted_count=excluded.attempted_count,
                   successful_count=excluded.successful_count,
                   empty_count=excluded.empty_count,
                   failed_count=excluded.failed_count,
                   result_count=excluded.result_count,
                   completed_at=excluded.completed_at""",
            (
                normalized_batch_id,
                normalized_status,
                attempted,
                successful,
                empty,
                failed,
                results,
                completed,
            ),
        )


def save_opportunity_batch(batch_id: str, search_id: int | None, search_name: str, query: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    now = utc_now()
    rows = []
    for row in df.to_dict(orient="records"):
        payload = _snapshot_payload(row)
        action = str(payload.get("recommended_action", ""))
        actionable = action in ACTIONABLE_ACTIONS
        rows.append((
            batch_id, search_id, search_name, query, str(payload.get("item_id", "")),
            str(payload.get("title", "")), str(payload.get("item_url", "")),
            float(payload.get("total_price", 0) or 0), action,
            float(payload.get("total_score", 0) or 0),
            float(payload.get("best_expected_profit", 0) or 0) if actionable else None,
            float(payload.get("best_expected_roi_pct", 0) or 0) if actionable else None,
            float(payload.get("suggested_offer", 0) or 0) if actionable else None,
            json.dumps(payload, default=str), now,
        ))
    with connect() as conn:
        conn.executemany(
            """INSERT INTO opportunity_snapshots(
                batch_id, saved_search_id, saved_search_name, query, item_id, title, item_url,
                total_price, recommended_action, total_score, expected_profit, expected_roi_pct,
                suggested_offer, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows
        )


def latest_opportunities(limit: int = 250) -> pd.DataFrame:
    with connect() as conn:
        frame = pd.read_sql_query(
            """SELECT id, batch_id, saved_search_name, query, item_id, title, total_price,
                      recommended_action, total_score, expected_profit, expected_roi_pct,
                      suggested_offer, item_url, payload_json, created_at
               FROM opportunity_snapshots
               ORDER BY id DESC LIMIT ?""", conn, params=(int(limit),)
        )
    return _sanitize_persisted_actions(frame).drop(
        columns=["payload_json"],
        errors="ignore",
    )


def _latest_batch_record(conn: sqlite3.Connection) -> sqlite3.Row | None:
    batch = conn.execute(
        """SELECT batch_id, status, attempted_count, successful_count,
                  empty_count, failed_count, result_count, completed_at
           FROM opportunity_batches
           ORDER BY completed_at DESC, rowid DESC
           LIMIT 1"""
    ).fetchone()
    if batch is not None:
        return batch
    return conn.execute(
        """SELECT batch_id, 'success' AS status, 0 AS attempted_count,
                  0 AS successful_count, 0 AS empty_count, 0 AS failed_count,
                  COUNT(*) AS result_count, MAX(created_at) AS completed_at
           FROM opportunity_snapshots
           GROUP BY batch_id
           ORDER BY MAX(id) DESC
           LIMIT 1"""
    ).fetchone()


def latest_batch_summary() -> pd.DataFrame:
    with connect() as conn:
        batch = _latest_batch_record(conn)
        batch_id = (
            batch["batch_id"]
            if batch and batch["status"] in {"success", "partial"}
            else None
        )
        return pd.read_sql_query(
            f"""SELECT saved_search_name, COUNT(*) AS listings,
                      SUM(CASE WHEN recommended_action IN ({DIRECT_BUY_ACTIONS_SQL})
                                    AND opportunity_actionable(payload_json, recommended_action) = 1
                               THEN 1 ELSE 0 END) AS buy_candidates,
                      COALESCE(ROUND(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                                                   AND opportunity_actionable(payload_json, recommended_action) = 1
                                              THEN expected_roi_pct END), 1), 0) AS best_roi_pct,
                      COALESCE(ROUND(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                                                   AND opportunity_actionable(payload_json, recommended_action) = 1
                                              THEN expected_profit END), 2), 0) AS best_profit
               FROM opportunity_snapshots
               WHERE batch_id = ?
               GROUP BY saved_search_name ORDER BY buy_candidates DESC, best_roi_pct DESC""",
            conn,
            params=(batch_id,),
        )


def dashboard_metrics() -> dict:
    with connect() as conn:
        saved = conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0]
        watch = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
        opps = conn.execute("SELECT COUNT(*) FROM opportunity_snapshots").fetchone()[0]
        latest = conn.execute(
            "SELECT MAX(created_at) FROM opportunity_snapshots"
        ).fetchone()[0]
    return {"saved_searches": saved, "watchlist": watch, "search_runs": runs, "opportunities": opps, "latest_refresh": latest}


def latest_batch_metrics() -> dict:
    """Return executive KPIs for the most recently stored Daily Buy Board batch."""
    with connect() as conn:
        batch = _latest_batch_record(conn)
        if not batch:
            return {
                "batch_id": None, "created_at": None, "status": None,
                "attempted_count": 0, "successful_count": 0,
                "empty_count": 0, "failed_count": 0,
                "listings_analyzed": 0,
                "buy_candidates": 0, "potential_profit": 0.0, "average_roi_pct": 0.0,
                "highest_score": 0.0, "best_opportunity": None,
            }
        if batch["status"] in {"empty", "failed"}:
            return {
                "batch_id": batch["batch_id"],
                "created_at": batch["completed_at"],
                "status": batch["status"],
                "attempted_count": int(batch["attempted_count"] or 0),
                "successful_count": int(batch["successful_count"] or 0),
                "empty_count": int(batch["empty_count"] or 0),
                "failed_count": int(batch["failed_count"] or 0),
                "listings_analyzed": 0,
                "buy_candidates": 0,
                "potential_profit": 0.0,
                "average_roi_pct": 0.0,
                "highest_score": 0.0,
                "best_opportunity": None,
            }
        row = conn.execute(
            f"""SELECT COUNT(*) AS listings_analyzed,
                      SUM(CASE WHEN recommended_action IN ({DIRECT_BUY_ACTIONS_SQL})
                                    AND opportunity_actionable(payload_json, recommended_action) = 1
                               THEN 1 ELSE 0 END) AS buy_candidates,
                      COALESCE(SUM(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                                             AND opportunity_actionable(payload_json, recommended_action) = 1
                                             AND expected_profit > 0
                                        THEN expected_profit ELSE 0 END), 0) AS potential_profit,
                      COALESCE(AVG(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                                             AND opportunity_actionable(payload_json, recommended_action) = 1
                                             AND expected_roi_pct > 0
                                        THEN expected_roi_pct END), 0) AS average_roi_pct,
                      COALESCE(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                                             AND opportunity_actionable(payload_json, recommended_action) = 1
                                        THEN total_score END), 0) AS highest_score
               FROM opportunity_snapshots WHERE batch_id = ?""",
            (batch["batch_id"],),
        ).fetchone()
        best = conn.execute(
            f"""SELECT title, expected_profit, expected_roi_pct, total_score, item_url
               FROM opportunity_snapshots WHERE batch_id = ?
                 AND recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                 AND opportunity_actionable(payload_json, recommended_action) = 1
               ORDER BY total_score DESC, expected_roi_pct DESC LIMIT 1""",
            (batch["batch_id"],),
        ).fetchone()
    return {
        "batch_id": batch["batch_id"],
        "created_at": batch["completed_at"],
        "status": batch["status"],
        "attempted_count": int(batch["attempted_count"] or 0),
        "successful_count": int(batch["successful_count"] or 0),
        "empty_count": int(batch["empty_count"] or 0),
        "failed_count": int(batch["failed_count"] or 0),
        "listings_analyzed": int(row["listings_analyzed"] or 0),
        "buy_candidates": int(row["buy_candidates"] or 0),
        "potential_profit": round(float(row["potential_profit"] or 0), 2),
        "average_roi_pct": round(float(row["average_roi_pct"] or 0), 1),
        "highest_score": round(float(row["highest_score"] or 0), 1),
        "best_opportunity": dict(best) if best else None,
    }


def recent_activity(limit: int = 12) -> pd.DataFrame:
    """Combine recent searches and watchlist additions into one dashboard feed."""
    with connect() as conn:
        frame = pd.read_sql_query(
            """SELECT activity_type, description, detail, created_at, payload_json FROM (
                   SELECT 'Search' AS activity_type, query AS description,
                          CAST(result_count AS TEXT) || ' results' AS detail,
                          created_at, id AS sort_id, NULL AS payload_json
                   FROM search_runs
                   UNION ALL
                   SELECT 'Watchlist' AS activity_type, title AS description,
                          COALESCE(recommended_action, '') AS detail, created_at,
                          id AS sort_id, payload_json
                   FROM watchlist
               ) ORDER BY created_at DESC, sort_id DESC LIMIT ?""",
            conn, params=(int(limit),)
        )
    for index, row in frame.iterrows():
        if row["activity_type"] != "Watchlist":
            continue
        if (
            str(row["detail"]) in ACTIONABLE_ACTIONS
            and not _stored_payload_is_actionable(
                row["payload_json"],
                row["detail"],
            )
        ):
            frame.at[index, "detail"] = "PASS"
    return frame.drop(columns=["payload_json"], errors="ignore")


def latest_batch_opportunities(limit: int = 25) -> pd.DataFrame:
    """Return only opportunities from the most recent Daily Buy Board batch."""
    with connect() as conn:
        batch = _latest_batch_record(conn)
        batch_id = (
            batch["batch_id"]
            if batch and batch["status"] in {"success", "partial"}
            else None
        )
        return pd.read_sql_query(
            f"""SELECT saved_search_name, title, total_price, recommended_action, total_score,
                      expected_profit, expected_roi_pct, suggested_offer, item_url, created_at
               FROM opportunity_snapshots
               WHERE batch_id = ?
                 AND recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
                 AND opportunity_actionable(payload_json, recommended_action) = 1
               ORDER BY total_score DESC, expected_roi_pct DESC LIMIT ?""",
            conn,
            params=(batch_id, int(limit)),
        )
