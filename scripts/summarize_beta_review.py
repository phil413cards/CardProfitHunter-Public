from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from beta_review import (
    BetaReviewValidationError,
    ISSUE_CATEGORIES,
    load_beta_review_csv,
    summarize_beta_review,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize a local CardProfitHunter beta review CSV.",
    )
    parser.add_argument("--input", type=Path, required=True)
    return parser


def _percentage(value: object) -> str:
    return "not_available" if value is None else f"{float(value):.1f}"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        reviewed = load_beta_review_csv(args.input)
        summary = summarize_beta_review(reviewed)
    except (BetaReviewValidationError, OSError, TypeError, ValueError):
        print(
            "Beta review summary could not be completed because the input is invalid.",
            file=sys.stderr,
        )
        return 1

    print("Beta decision-quality summary")
    for key in (
        "reviewed_rows",
        "conclusive_rows",
        "uncertain_rows",
        "system_actionable",
        "human_actionable",
        "true_positive",
        "false_positive",
        "true_negative",
        "false_negative",
        "identity_incorrect",
        "money_unreasonable",
        "useful_rows",
        "not_useful_rows",
        "issue_rows",
    ):
        print(f"{key}: {summary[key]}")
    for category in sorted(ISSUE_CATEGORIES - {"none"}):
        key = f"issue_{category}"
        print(f"{key}: {summary[key]}")
    print(f"precision_pct: {_percentage(summary['precision_pct'])}")
    print(f"recall_pct: {_percentage(summary['recall_pct'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
