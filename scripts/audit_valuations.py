from __future__ import annotations

import argparse
from datetime import date
import math
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from input_validation import InputValidationError, load_valuation_csv
from valuation_renewal import (
    build_valuation_renewal_report,
    summarize_valuation_renewal,
)


DEFAULT_INPUT = ROOT / "sample_data" / "card_values.csv"


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("as-of must use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a read-only CardProfitHunter valuation renewal report.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--as-of", type=_iso_date, default=None)
    parser.add_argument("--renewal-window-days", type=int, default=30)
    parser.add_argument(
        "--fail-on-blocking",
        action="store_true",
        help=(
            "exit unsuccessfully when verified valuations are expired or have "
            "missing or invalid provenance"
        ),
    )
    return parser


def _days_text(value: object) -> str:
    if value is None:
        return "unknown"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "unknown"
    return str(int(parsed)) if math.isfinite(parsed) else "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        valuations = load_valuation_csv(args.input)
        report = build_valuation_renewal_report(
            valuations,
            as_of=args.as_of,
            renewal_window_days=args.renewal_window_days,
        )
    except (InputValidationError, OSError, TypeError, ValueError):
        print(
            "Valuation audit could not be completed because the input or audit "
            "settings are invalid.",
            file=sys.stderr,
        )
        return 1

    summary = summarize_valuation_renewal(report)
    print("Valuation renewal summary")
    for key in (
        "total",
        "current",
        "due_soon",
        "expired",
        "missing_provenance",
        "invalid_provenance",
        "non_actionable",
        "renewal_required",
    ):
        print(f"{key}: {summary[key]}")

    queue = report.loc[report["renewal_required"]]
    print("Renewal queue")
    if queue.empty:
        print("none")
    else:
        for row in queue.itertuples(index=False):
            print(
                f"- {row.keyword!r} | {row.freshness_status} | "
                f"expires={row.expires_at or 'unknown'} | "
                f"days={_days_text(row.days_until_expiry)}"
            )

    blocking_count = (
        summary["expired"]
        + summary["missing_provenance"]
        + summary["invalid_provenance"]
    )
    if args.fail_on_blocking and blocking_count:
        print(
            "Valuation audit found blocking valuation data. Review the renewal "
            "summary before release.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
