from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Iterable, MutableMapping, Sequence

import pandas as pd

from profit_engine import ProfitResult


ANALYSIS_COLUMNS = tuple(field.name for field in fields(ProfitResult))
DAILY_BOARD_METADATA_COLUMNS = ("saved_search", "search_query")
EXPORT_TRACE_COLUMNS = (
    "search_query",
    "application_version",
    "search_completed_at",
)


@dataclass(frozen=True)
class RunOutcome:
    status: str
    attempted_count: int
    successful_count: int
    empty_count: int
    failed_count: int
    result_count: int
    completed_at: str
    errors: tuple[str, ...] = ()


def empty_analysis_frame(extra_columns: Sequence[str] = ()) -> pd.DataFrame:
    columns = list(ANALYSIS_COLUMNS)
    columns.extend(column for column in extra_columns if column not in columns)
    return pd.DataFrame(columns=columns)


def stable_analysis_frame(
    frame: pd.DataFrame | None,
    extra_columns: Sequence[str] = (),
) -> pd.DataFrame:
    stable = pd.DataFrame() if frame is None else frame.copy()
    expected_columns = list(ANALYSIS_COLUMNS)
    expected_columns.extend(
        column for column in extra_columns if column not in expected_columns
    )

    for column in expected_columns:
        if column not in stable.columns:
            stable[column] = pd.Series(index=stable.index, dtype="object")

    remaining = [column for column in stable.columns if column not in expected_columns]
    return stable[expected_columns + remaining]


def prepare_results_export(
    frame: pd.DataFrame,
    *,
    application_version: str,
    completed_at: str,
    search_query: str | None = None,
) -> pd.DataFrame:
    """Return an export-only copy with deterministic run traceability fields."""
    exported = pd.DataFrame() if frame is None else frame.copy(deep=True)

    if search_query is not None:
        exported["search_query"] = str(search_query)
    elif "search_query" not in exported.columns:
        exported["search_query"] = ""

    exported["application_version"] = str(application_version)
    exported["search_completed_at"] = str(completed_at)

    remaining = [
        column
        for column in exported.columns
        if column not in EXPORT_TRACE_COLUMNS
    ]
    return exported[list(EXPORT_TRACE_COLUMNS) + remaining]


def combine_board_results(
    frames: Iterable[pd.DataFrame],
    minimum_score: float = 0.0,
) -> pd.DataFrame:
    stable_frames = [
        stable_analysis_frame(frame, DAILY_BOARD_METADATA_COLUMNS)
        for frame in frames
        if frame is not None and not frame.empty
    ]
    if not stable_frames:
        return empty_analysis_frame(DAILY_BOARD_METADATA_COLUMNS)

    board = pd.concat(stable_frames, ignore_index=True)
    board = stable_analysis_frame(board, DAILY_BOARD_METADATA_COLUMNS)
    scores = pd.to_numeric(board["total_score"], errors="coerce")
    board = board[scores >= float(minimum_score)].copy()
    if board.empty:
        return empty_analysis_frame(DAILY_BOARD_METADATA_COLUMNS)

    board["total_score"] = pd.to_numeric(
        board["total_score"],
        errors="coerce",
    )
    board["best_expected_roi_pct"] = pd.to_numeric(
        board["best_expected_roi_pct"],
        errors="coerce",
    )
    return board.sort_values(
        ["total_score", "best_expected_roi_pct"],
        ascending=False,
        na_position="last",
    ).reset_index(drop=True)


def build_run_outcome(
    *,
    attempted_count: int,
    successful_count: int,
    empty_count: int,
    failed_count: int,
    result_count: int,
    errors: Sequence[str] = (),
    completed_at: str | None = None,
) -> RunOutcome:
    attempted = max(int(attempted_count), 0)
    successful = max(int(successful_count), 0)
    empty = max(int(empty_count), 0)
    failed = max(int(failed_count), 0)
    results = max(int(result_count), 0)

    if failed > 0 and successful == 0:
        status = "failed"
    elif failed > 0 and successful > 0:
        status = "partial"
    elif successful > 0 and empty >= successful:
        status = "empty"
    else:
        status = "success"

    timestamp = completed_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    return RunOutcome(
        status=status,
        attempted_count=attempted,
        successful_count=successful,
        empty_count=empty,
        failed_count=failed,
        result_count=results,
        completed_at=timestamp,
        errors=tuple(str(error) for error in errors),
    )


def clear_result_state(
    state: MutableMapping[str, object],
    result_key: str,
    outcome_key: str,
) -> None:
    state.pop(result_key, None)
    state.pop(outcome_key, None)
