from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "card_profit_hunter.db"
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

ACTIONABLE_ACTIONS = frozenset({
    "BUY",
    "OFFER",
    "BUY_RAW_FLIP",
    "BUY_GRADE_PSA",
})
ACTIONABLE_ACTIONS_SQL = "'BUY','OFFER','BUY_RAW_FLIP','BUY_GRADE_PSA'"
DIRECT_BUY_ACTIONS_SQL = "'BUY','BUY_RAW_FLIP','BUY_GRADE_PSA'"

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

_OLD_OPPORTUNITY_BATCHES_SQL = """
    SELECT batch_id
    FROM opportunity_snapshots
    GROUP BY batch_id
    HAVING MAX(created_at) < ?
       AND batch_id NOT IN (
           SELECT batch_id
           FROM opportunity_snapshots
           ORDER BY id DESC
           LIMIT 1
       )
"""


class DatabaseMaintenanceError(RuntimeError):
    """A sanitized database-maintenance error safe for the local UI."""


def _snapshot_payload(row: dict) -> dict:
    payload = dict(row)
    action = str(payload.get("recommended_action", ""))
    if action not in ACTIONABLE_ACTIONS:
        payload["best_path"] = "NONE"
        for field in NON_ACTIONABLE_FINANCIAL_FIELDS:
            payload[field] = None
    return payload


def _open_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        return conn
    except BaseException:
        conn.close()
        raise


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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


def create_database_backup(backup_dir: Path) -> Path | None:
    if not DB_PATH.exists():
        return None

    destination_path: Path | None = None
    try:
        if not DB_PATH.is_file():
            raise OSError("Database source is not a file.")
        destination_dir = Path(backup_dir)
        destination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
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
    return {
        "search_runs": int(search_runs),
        "opportunity_snapshots": int(opportunities),
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
            search_cursor = conn.execute(
                "DELETE FROM search_runs WHERE created_at < ?",
                (cutoff_text,),
            )
            deleted = {
                "search_runs": max(int(search_cursor.rowcount), 0),
                "opportunity_snapshots": max(int(opportunity_cursor.rowcount), 0),
                "backup_path": backup_path,
            }
    except DatabaseMaintenanceError:
        raise
    except Exception:
        raise DatabaseMaintenanceError(
            "History retention cleanup could not be completed."
        ) from None
    return deleted


def init_db() -> None:
    with connect() as conn:
        current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                "Database schema version is newer than this application supports."
            )

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
            CREATE INDEX IF NOT EXISTS idx_opportunity_batch ON opportunity_snapshots(batch_id);
            CREATE INDEX IF NOT EXISTS idx_opportunity_created ON opportunity_snapshots(created_at);
            """
        )
        if current_version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
    with connect() as conn:
        conn.execute(
            """INSERT INTO watchlist(item_id, title, item_url, total_price, recommended_action,
               expected_profit, expected_roi_pct, notes, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(row.get("item_id", "")), str(row.get("title", "")), str(row.get("item_url", "")),
                float(row.get("total_price", 0) or 0), str(row.get("recommended_action", "")),
                float(row.get("best_expected_profit", 0) or 0), float(row.get("best_expected_roi_pct", 0) or 0),
                notes, json.dumps(row, default=str), utc_now(),
            ),
        )


def list_watchlist() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """SELECT id, title, total_price, recommended_action, expected_profit,
               expected_roi_pct, notes, item_url, created_at FROM watchlist ORDER BY id DESC""", conn
        )


def delete_watchlist_item(item_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE id = ?", (int(item_id),))


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
            batch_id, search_id, search_name, query, str(row.get("item_id", "")),
            str(row.get("title", "")), str(row.get("item_url", "")),
            float(row.get("total_price", 0) or 0), action,
            float(row.get("total_score", 0) or 0),
            float(row.get("best_expected_profit", 0) or 0) if actionable else None,
            float(row.get("best_expected_roi_pct", 0) or 0) if actionable else None,
            float(row.get("suggested_offer", 0) or 0) if actionable else None,
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
        return pd.read_sql_query(
            """SELECT id, batch_id, saved_search_name, query, item_id, title, total_price,
                      recommended_action, total_score, expected_profit, expected_roi_pct,
                      suggested_offer, item_url, created_at
               FROM opportunity_snapshots
               ORDER BY id DESC LIMIT ?""", conn, params=(int(limit),)
        )


def latest_batch_summary() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            f"""WITH latest AS (SELECT batch_id FROM opportunity_snapshots ORDER BY id DESC LIMIT 1)
               SELECT saved_search_name, COUNT(*) AS listings,
                      SUM(CASE WHEN recommended_action IN ({DIRECT_BUY_ACTIONS_SQL}) THEN 1 ELSE 0 END) AS buy_candidates,
                      COALESCE(ROUND(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL}) THEN expected_roi_pct END), 1), 0) AS best_roi_pct,
                      COALESCE(ROUND(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL}) THEN expected_profit END), 2), 0) AS best_profit
               FROM opportunity_snapshots
               WHERE batch_id = (SELECT batch_id FROM latest)
               GROUP BY saved_search_name ORDER BY buy_candidates DESC, best_roi_pct DESC""", conn
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
        batch = conn.execute(
            "SELECT batch_id, MAX(created_at) AS created_at FROM opportunity_snapshots GROUP BY batch_id ORDER BY MAX(id) DESC LIMIT 1"
        ).fetchone()
        if not batch:
            return {
                "batch_id": None, "created_at": None, "listings_analyzed": 0,
                "buy_candidates": 0, "potential_profit": 0.0, "average_roi_pct": 0.0,
                "highest_score": 0.0, "best_opportunity": None,
            }
        row = conn.execute(
            f"""SELECT COUNT(*) AS listings_analyzed,
                      SUM(CASE WHEN recommended_action IN ({DIRECT_BUY_ACTIONS_SQL}) THEN 1 ELSE 0 END) AS buy_candidates,
                      COALESCE(SUM(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL}) AND expected_profit > 0 THEN expected_profit ELSE 0 END), 0) AS potential_profit,
                      COALESCE(AVG(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL}) AND expected_roi_pct > 0 THEN expected_roi_pct END), 0) AS average_roi_pct,
                      COALESCE(MAX(CASE WHEN recommended_action IN ({ACTIONABLE_ACTIONS_SQL}) THEN total_score END), 0) AS highest_score
               FROM opportunity_snapshots WHERE batch_id = ?""",
            (batch["batch_id"],),
        ).fetchone()
        best = conn.execute(
            f"""SELECT title, expected_profit, expected_roi_pct, total_score, item_url
               FROM opportunity_snapshots WHERE batch_id = ?
                 AND recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
               ORDER BY total_score DESC, expected_roi_pct DESC LIMIT 1""",
            (batch["batch_id"],),
        ).fetchone()
    return {
        "batch_id": batch["batch_id"],
        "created_at": batch["created_at"],
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
        return pd.read_sql_query(
            """SELECT activity_type, description, detail, created_at FROM (
                   SELECT 'Search' AS activity_type, query AS description,
                          CAST(result_count AS TEXT) || ' results' AS detail, created_at, id AS sort_id
                   FROM search_runs
                   UNION ALL
                   SELECT 'Watchlist' AS activity_type, title AS description,
                          COALESCE(recommended_action, '') AS detail, created_at, id AS sort_id
                   FROM watchlist
               ) ORDER BY created_at DESC, sort_id DESC LIMIT ?""",
            conn, params=(int(limit),)
        )


def latest_batch_opportunities(limit: int = 25) -> pd.DataFrame:
    """Return only opportunities from the most recent Daily Buy Board batch."""
    with connect() as conn:
        return pd.read_sql_query(
            f"""WITH latest AS (SELECT batch_id FROM opportunity_snapshots ORDER BY id DESC LIMIT 1)
               SELECT saved_search_name, title, total_price, recommended_action, total_score,
                      expected_profit, expected_roi_pct, suggested_offer, item_url, created_at
               FROM opportunity_snapshots
               WHERE batch_id = (SELECT batch_id FROM latest)
                 AND recommended_action IN ({ACTIONABLE_ACTIONS_SQL})
               ORDER BY total_score DESC, expected_roi_pct DESC LIMIT ?""",
            conn, params=(int(limit),)
        )
