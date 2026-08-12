from __future__ import annotations

import contextlib
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.audit_valuations import main
from valuation_renewal import (
    RENEWAL_REPORT_COLUMNS,
    build_valuation_renewal_report,
    summarize_valuation_renewal,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 8, 9)


def valuation(**updates):
    row = {
        "keyword": "2024 Example Card #1 Silver",
        "raw_market_value": 100.0,
        "psa9_value": 150.0,
        "psa10_value": 300.0,
        "gem_rate_estimate": 0.0,
        "psa9_rate_estimate": 0.0,
        "verification_status": "verified",
        "verified_at": "2026-08-01",
        "expires_at": "2026-10-01",
        "source_url": "https://example.com/sold-comps",
        "comp_count": 12,
        "notes": "Verified exact-card sold comps",
    }
    row.update(updates)
    return row


class ValuationRenewalReportTests(unittest.TestCase):
    def test_table_driven_freshness_and_renewal_classification(self):
        rows = (
            (valuation(keyword="Current", expires_at="2026-10-01"), "Current", False, "", 53),
            (valuation(keyword="Due", expires_at="2026-09-08"), "Due soon", True, "expires_within_window", 30),
            (valuation(keyword="Expires today", expires_at="2026-08-09"), "Due soon", True, "expires_within_window", 0),
            (valuation(keyword="Expired", expires_at="2026-08-08"), "Expired", True, "expired", -1),
            (valuation(keyword="Missing", source_url=""), "Missing provenance", True, "missing_provenance", 53),
            (valuation(keyword="Invalid", source_url="http://example.com"), "Invalid provenance", True, "invalid_provenance", 53),
            (valuation(keyword="Demo", verification_status="demonstration", verified_at="", expires_at="", source_url="", comp_count="", notes="Example only"), "Non-actionable", False, "non_actionable", None),
            (valuation(keyword="Verified example", notes="Example only - replace"), "Non-actionable", False, "non_actionable", 53),
        )
        report = build_valuation_renewal_report(
            pd.DataFrame(row[0] for row in rows),
            as_of=AS_OF,
            renewal_window_days=30,
        )

        for index, (_, status, required, reason, days) in enumerate(rows):
            with self.subTest(index=index):
                self.assertEqual(report.loc[index, "freshness_status"], status)
                self.assertEqual(bool(report.loc[index, "renewal_required"]), required)
                self.assertEqual(report.loc[index, "renewal_reason"], reason)
                actual_days = report.loc[index, "days_until_expiry"]
                if days is None:
                    self.assertTrue(pd.isna(actual_days))
                else:
                    self.assertEqual(actual_days, days)

    def test_summary_has_stable_counts(self):
        frame = pd.DataFrame(
            [
                valuation(keyword="Current"),
                valuation(keyword="Due", expires_at="2026-09-01"),
                valuation(keyword="Expired", expires_at="2026-08-01"),
                valuation(keyword="Demo", verification_status="demonstration", verified_at="", expires_at="", source_url="", comp_count="", notes="Demo valuation"),
            ]
        )
        report = build_valuation_renewal_report(frame, as_of=AS_OF)

        self.assertEqual(
            summarize_valuation_renewal(report),
            {
                "total": 4,
                "current": 1,
                "due_soon": 1,
                "expired": 1,
                "missing_provenance": 0,
                "invalid_provenance": 0,
                "non_actionable": 1,
                "renewal_required": 2,
            },
        )

    def test_empty_report_has_stable_schema_and_zero_summary(self):
        report = build_valuation_renewal_report(pd.DataFrame(), as_of=AS_OF)

        self.assertEqual(tuple(report.columns), RENEWAL_REPORT_COLUMNS)
        self.assertEqual(summarize_valuation_renewal(report)["total"], 0)
        self.assertEqual(summarize_valuation_renewal(report)["renewal_required"], 0)

    def test_timezone_aware_datetime_is_utc_normalized(self):
        report = build_valuation_renewal_report(
            pd.DataFrame([valuation(expires_at="2026-08-09")]),
            as_of=datetime(2026, 8, 9, 23, tzinfo=timezone.utc),
        )

        self.assertEqual(report.loc[0, "days_until_expiry"], 0)

    def test_invalid_audit_inputs_fail_safely(self):
        frame = pd.DataFrame([valuation()])
        cases = (
            {"as_of": datetime(2026, 8, 9)},
            {"as_of": "2026-08-09"},
            {"renewal_window_days": -1},
            {"renewal_window_days": 1.5},
            {"renewal_window_days": True},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((TypeError, ValueError)):
                    build_valuation_renewal_report(frame, **kwargs)

    def test_bundled_values_have_a_deterministic_renewal_queue(self):
        bundled = pd.read_csv(ROOT / "sample_data" / "card_values.csv")
        report = build_valuation_renewal_report(
            bundled,
            as_of=date(2026, 8, 12),
            renewal_window_days=30,
        )
        summary = summarize_valuation_renewal(report)

        self.assertEqual(summary["total"], 16)
        self.assertEqual(summary["due_soon"], 6)
        self.assertEqual(summary["non_actionable"], 10)
        self.assertEqual(summary["renewal_required"], 6)


class ValuationRenewalCliTests(unittest.TestCase):
    def test_cli_reports_queue_without_writing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "values.csv"
            pd.DataFrame([valuation(expires_at="2026-09-01")]).to_csv(
                source,
                index=False,
            )
            stdout = StringIO()
            stderr = StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--input",
                        str(source),
                        "--as-of",
                        "2026-08-09",
                        "--renewal-window-days",
                        "30",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("renewal_required: 1", stdout.getvalue())
            self.assertIn("'2024 Example Card #1 Silver'", stdout.getvalue())
            self.assertIn("days=23", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(list(temp_path.iterdir()), [source])

    def test_cli_error_is_sanitized(self):
        stderr = StringIO()
        unsafe_path = "/missing/PRIVATE_TOKEN_values.csv"

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--input", unsafe_path, "--as-of", "2026-08-09"])

        self.assertEqual(exit_code, 1)
        self.assertNotIn("PRIVATE_TOKEN", stderr.getvalue())
        self.assertIn("could not be completed", stderr.getvalue())

    def test_ci_gate_allows_due_soon_and_non_actionable_rows(self):
        rows = [
            valuation(keyword="Due", expires_at="2026-09-01"),
            valuation(
                keyword="Demo",
                verification_status="demonstration",
                verified_at="",
                expires_at="",
                source_url="",
                comp_count="",
                notes="Example only",
            ),
        ]

        exit_code, stdout, stderr = self._run_cli(rows, "--fail-on-blocking")

        self.assertEqual(exit_code, 0)
        self.assertIn("due_soon: 1", stdout)
        self.assertIn("non_actionable: 1", stdout)
        self.assertEqual(stderr, "")

    def test_ci_gate_rejects_expired_verified_valuation(self):
        row = valuation(expires_at="2026-08-08")

        exit_code, stdout, stderr = self._run_cli(
            [row],
            "--fail-on-blocking",
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("expired: 1", stdout)
        self.assertIn("blocking valuation data", stderr)
        self.assertNotIn(row["keyword"], stderr)

    def test_default_audit_remains_informational_for_expired_rows(self):
        exit_code, stdout, stderr = self._run_cli(
            [valuation(expires_at="2026-08-08")]
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("expired: 1", stdout)
        self.assertEqual(stderr, "")

    def test_ci_rejects_missing_or_invalid_provenance_during_input_validation(self):
        rows = (
            valuation(keyword="PRIVATE_MISSING", source_url=""),
            valuation(
                keyword="PRIVATE_INVALID",
                source_url="http://example.com/sold-comps",
            ),
        )

        for row in rows:
            with self.subTest(keyword=row["keyword"]):
                exit_code, stdout, stderr = self._run_cli(
                    [row],
                    "--fail-on-blocking",
                )

                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout, "")
                self.assertIn("could not be completed", stderr)
                self.assertNotIn(row["keyword"], stderr)

    @staticmethod
    def _run_cli(rows, *extra_args):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "values.csv"
            pd.DataFrame(rows).to_csv(source, index=False)
            stdout = StringIO()
            stderr = StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--input",
                        str(source),
                        "--as-of",
                        "2026-08-09",
                        "--renewal-window-days",
                        "30",
                        *extra_args,
                    ]
                )

            return exit_code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
