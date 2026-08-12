from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


MAX_BETA_REVIEW_ROWS = 5_000
MAX_BETA_REVIEW_BYTES = 5 * 1024 * 1024

BETA_REVIEW_COLUMNS = (
    "session_id",
    "reviewed_at",
    "workflow",
    "listing_reference",
    "system_action",
    "human_verdict",
    "identity_verdict",
    "money_verdict",
    "usefulness",
    "issue_category",
    "notes",
)

ACTIONABLE_ACTIONS = {
    "BUY",
    "OFFER",
    "BUY_RAW_FLIP",
    "BUY_GRADE_PSA",
}
SYSTEM_ACTIONS = ACTIONABLE_ACTIONS | {"PASS", "WATCH"}
WORKFLOWS = {"sample", "sandbox", "production"}
HUMAN_VERDICTS = {"actionable", "non_actionable", "uncertain"}
IDENTITY_VERDICTS = {"correct", "incorrect", "unknown"}
MONEY_VERDICTS = {"reasonable", "unreasonable", "unknown"}
USEFULNESS_VALUES = {"useful", "not_useful", "unknown"}
ISSUE_CATEGORIES = {
    "none",
    "false_positive",
    "false_negative",
    "wrong_card_match",
    "bad_profit_roi_assumption",
    "search_result_quality",
    "export_issue",
    "crash_error",
    "missing_feature",
    "other",
}


class BetaReviewValidationError(ValueError):
    """Raised when a local beta review file is not safe to summarize."""


def _required_text(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column]
    valid_types = values.map(lambda value: isinstance(value, str))
    normalized = values.map(
        lambda value: value.strip() if isinstance(value, str) else ""
    )
    invalid = ~valid_types | normalized.eq("")
    if invalid.any():
        raise BetaReviewValidationError(
            f"Beta review column '{column}' contains missing or invalid values."
        )
    return normalized


def _optional_text(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column]

    def normalize(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if not isinstance(value, (list, tuple, dict, set)):
            try:
                if bool(pd.isna(value)):
                    return ""
            except (TypeError, ValueError):
                pass
        raise BetaReviewValidationError(
            f"Beta review column '{column}' contains invalid values."
        )

    return values.map(normalize)


def _enum_column(
    frame: pd.DataFrame,
    column: str,
    allowed: set[str],
    *,
    uppercase: bool = False,
) -> pd.Series:
    normalized = _required_text(frame, column)
    normalized = normalized.str.upper() if uppercase else normalized.str.casefold()
    if (~normalized.isin(allowed)).any():
        raise BetaReviewValidationError(
            f"Beta review column '{column}' contains unsupported values."
        )
    return normalized


def _iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise BetaReviewValidationError(
            "Beta review dates must use YYYY-MM-DD."
        ) from exc


def validate_beta_review_frame(frame: Any) -> pd.DataFrame:
    """Return a normalized copy of a manually reviewed beta evidence table."""
    if not isinstance(frame, pd.DataFrame):
        raise BetaReviewValidationError(
            "Beta review data must be provided as a table."
        )

    missing = [column for column in BETA_REVIEW_COLUMNS if column not in frame.columns]
    if missing:
        raise BetaReviewValidationError(
            "Beta review data is missing required columns."
        )
    if frame.empty:
        raise BetaReviewValidationError(
            "Beta review data must include at least one reviewed listing."
        )
    if len(frame) > MAX_BETA_REVIEW_ROWS:
        raise BetaReviewValidationError(
            "Beta review data exceeds the supported local row limit."
        )

    validated = frame.loc[:, BETA_REVIEW_COLUMNS].copy(deep=True)
    validated["session_id"] = _required_text(validated, "session_id")
    validated["listing_reference"] = _required_text(
        validated,
        "listing_reference",
    )
    validated["reviewed_at"] = _required_text(validated, "reviewed_at").map(
        _iso_date
    )
    validated["workflow"] = _enum_column(
        validated,
        "workflow",
        WORKFLOWS,
    )
    validated["system_action"] = _enum_column(
        validated,
        "system_action",
        SYSTEM_ACTIONS,
        uppercase=True,
    )
    validated["human_verdict"] = _enum_column(
        validated,
        "human_verdict",
        HUMAN_VERDICTS,
    )
    validated["identity_verdict"] = _enum_column(
        validated,
        "identity_verdict",
        IDENTITY_VERDICTS,
    )
    validated["money_verdict"] = _enum_column(
        validated,
        "money_verdict",
        MONEY_VERDICTS,
    )
    validated["usefulness"] = _enum_column(
        validated,
        "usefulness",
        USEFULNESS_VALUES,
    )
    validated["issue_category"] = _enum_column(
        validated,
        "issue_category",
        ISSUE_CATEGORIES,
    )
    validated["notes"] = _optional_text(validated, "notes")

    duplicate = validated.duplicated(
        subset=("session_id", "listing_reference"),
        keep=False,
    )
    if duplicate.any():
        raise BetaReviewValidationError(
            "Beta review data contains duplicate listing references within a session."
        )
    return validated


def load_beta_review_csv(path: str | Path) -> pd.DataFrame:
    """Load and validate a local beta review CSV without modifying it."""
    source = Path(path)
    try:
        if not source.is_file() or source.stat().st_size > MAX_BETA_REVIEW_BYTES:
            raise BetaReviewValidationError(
                "Beta review CSV is missing or exceeds the local size limit."
            )
        frame = pd.read_csv(source, dtype=object)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise BetaReviewValidationError(
            "Beta review CSV could not be read safely."
        ) from exc
    return validate_beta_review_frame(frame)


def summarize_beta_review(frame: Any) -> dict[str, int | float | None]:
    """Return aggregate decision-quality metrics without listing-level content."""
    reviewed = validate_beta_review_frame(frame)
    system_actionable = reviewed["system_action"].isin(ACTIONABLE_ACTIONS)
    conclusive = reviewed["human_verdict"].ne("uncertain")
    human_actionable = reviewed["human_verdict"].eq("actionable")

    true_positive = int((conclusive & system_actionable & human_actionable).sum())
    false_positive = int((conclusive & system_actionable & ~human_actionable).sum())
    true_negative = int((conclusive & ~system_actionable & ~human_actionable).sum())
    false_negative = int((conclusive & ~system_actionable & human_actionable).sum())

    predicted_positive = true_positive + false_positive
    actual_positive = true_positive + false_negative

    summary: dict[str, int | float | None] = {
        "reviewed_rows": int(len(reviewed)),
        "conclusive_rows": int(conclusive.sum()),
        "uncertain_rows": int((~conclusive).sum()),
        "system_actionable": int(system_actionable.sum()),
        "human_actionable": int((conclusive & human_actionable).sum()),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "false_negative": false_negative,
        "precision_pct": (
            round(100.0 * true_positive / predicted_positive, 1)
            if predicted_positive
            else None
        ),
        "recall_pct": (
            round(100.0 * true_positive / actual_positive, 1)
            if actual_positive
            else None
        ),
        "identity_incorrect": int(
            reviewed["identity_verdict"].eq("incorrect").sum()
        ),
        "money_unreasonable": int(
            reviewed["money_verdict"].eq("unreasonable").sum()
        ),
        "useful_rows": int(reviewed["usefulness"].eq("useful").sum()),
        "not_useful_rows": int(
            reviewed["usefulness"].eq("not_useful").sum()
        ),
        "issue_rows": int(reviewed["issue_category"].ne("none").sum()),
    }
    for category in sorted(ISSUE_CATEGORIES - {"none"}):
        summary[f"issue_{category}"] = int(
            reviewed["issue_category"].eq(category).sum()
        )
    return summary
