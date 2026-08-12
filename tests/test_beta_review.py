from __future__ import annotations

import contextlib
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from beta_review import (
    BETA_REVIEW_COLUMNS,
    MAX_BETA_REVIEW_BYTES,
    BetaReviewValidationError,
    load_beta_review_csv,
    summarize_beta_review,
    validate_beta_review_frame,
)
from scripts.summarize_beta_review import main


ROOT = Path(__file__).resolve().parents[1]


def review_row(**updates):
    row = {
        "session_id": "session-2026-08-12",
        "reviewed_at": "2026-08-12",
        "workflow": "production",
        "listing_reference": "local-listing-1",
        "system_action": "PASS",
        "human_verdict": "non_actionable",
        "identity_verdict": "correct",
        "money_verdict": "reasonable",
        "usefulness": "useful",
        "issue_category": "none",
        "notes": "Reviewed manually",
    }
    row.update(updates)
    return row


class BetaReviewValidationTests(unittest.TestCase):
    def test_valid_rows_are_normalized_without_mutating_source(self):
        source = pd.DataFrame(
            [
                review_row(
                    session_id=" session-a ",
                    workflow=" Production ",
                    system_action="offer",
                    human_verdict=" Actionable ",
                    notes=None,
                )
            ]
        )
        original = source.copy(deep=True)

        validated = validate_beta_review_frame(source)

        pd.testing.assert_frame_equal(source, original)
        self.assertEqual(validated.loc[0, "session_id"], "session-a")
        self.assertEqual(validated.loc[0, "workflow"], "production")
        self.assertEqual(validated.loc[0, "system_action"], "OFFER")
        self.assertEqual(validated.loc[0, "human_verdict"], "actionable")
        self.assertEqual(validated.loc[0, "notes"], "")

    def test_pandas_missing_optional_notes_remain_blank(self):
        frame = pd.DataFrame(
            [
                review_row(listing_reference="nan", notes=float("nan")),
                review_row(listing_reference="pd-na", notes=pd.NA),
            ]
        )

        validated = validate_beta_review_frame(frame)

        self.assertEqual(list(validated["notes"]), ["", ""])

    def test_missing_columns_empty_rows_and_excess_rows_are_rejected(self):
        cases = (
            pd.DataFrame([review_row()]).drop(columns=["human_verdict"]),
            pd.DataFrame(columns=BETA_REVIEW_COLUMNS),
            pd.DataFrame([review_row()] * 5_001),
        )
        for frame in cases:
            with self.subTest(shape=frame.shape):
                with self.assertRaises(BetaReviewValidationError):
                    validate_beta_review_frame(frame)

    def test_invalid_required_and_enum_values_are_rejected(self):
        cases = (
            {"session_id": ""},
            {"listing_reference": None},
            {"reviewed_at": "08/12/2026"},
            {"workflow": "live"},
            {"system_action": "PURCHASE"},
            {"human_verdict": "maybe"},
            {"identity_verdict": "mostly"},
            {"money_verdict": "profitable"},
            {"usefulness": "sometimes"},
            {"issue_category": "secret_problem"},
            {"notes": []},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                with self.assertRaises(BetaReviewValidationError):
                    validate_beta_review_frame(pd.DataFrame([review_row(**updates)]))

    def test_duplicate_listing_reference_within_session_is_rejected(self):
        frame = pd.DataFrame([review_row(), review_row()])

        with self.assertRaises(BetaReviewValidationError):
            validate_beta_review_frame(frame)

    def test_same_listing_reference_in_different_sessions_is_allowed(self):
        frame = pd.DataFrame(
            [review_row(), review_row(session_id="session-2")]
        )

        self.assertEqual(len(validate_beta_review_frame(frame)), 2)

    def test_tracked_template_has_exact_stable_header(self):
        template = ROOT / "docs" / "templates" / "beta_review_template.csv"
        frame = pd.read_csv(template)

        self.assertEqual(tuple(frame.columns), BETA_REVIEW_COLUMNS)
        self.assertTrue(frame.empty)


class BetaReviewSummaryTests(unittest.TestCase):
    def test_confusion_matrix_and_quality_counts_are_deterministic(self):
        frame = pd.DataFrame(
            [
                review_row(listing_reference="tp", system_action="BUY", human_verdict="actionable"),
                review_row(listing_reference="fp", system_action="OFFER", human_verdict="non_actionable", identity_verdict="incorrect", issue_category="wrong_card_match"),
                review_row(listing_reference="tn", system_action="PASS", human_verdict="non_actionable"),
                review_row(listing_reference="fn", system_action="WATCH", human_verdict="actionable", money_verdict="unreasonable", usefulness="not_useful", issue_category="false_negative"),
                review_row(listing_reference="uncertain", system_action="BUY_GRADE_PSA", human_verdict="uncertain", usefulness="unknown"),
            ]
        )

        summary = summarize_beta_review(frame)

        self.assertEqual(summary["reviewed_rows"], 5)
        self.assertEqual(summary["conclusive_rows"], 4)
        self.assertEqual(summary["uncertain_rows"], 1)
        self.assertEqual(summary["system_actionable"], 3)
        self.assertEqual(summary["human_actionable"], 2)
        self.assertEqual(summary["true_positive"], 1)
        self.assertEqual(summary["false_positive"], 1)
        self.assertEqual(summary["true_negative"], 1)
        self.assertEqual(summary["false_negative"], 1)
        self.assertEqual(summary["precision_pct"], 50.0)
        self.assertEqual(summary["recall_pct"], 50.0)
        self.assertEqual(summary["identity_incorrect"], 1)
        self.assertEqual(summary["money_unreasonable"], 1)
        self.assertEqual(summary["not_useful_rows"], 1)
        self.assertEqual(summary["issue_rows"], 2)
        self.assertEqual(summary["issue_wrong_card_match"], 1)
        self.assertEqual(summary["issue_false_negative"], 1)
        self.assertEqual(summary["issue_crash_error"], 0)

    def test_zero_denominators_are_reported_as_unavailable(self):
        summary = summarize_beta_review(pd.DataFrame([review_row()]))

        self.assertIsNone(summary["precision_pct"])
        self.assertIsNone(summary["recall_pct"])


class BetaReviewCliTests(unittest.TestCase):
    def test_cli_prints_aggregate_metrics_without_private_row_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "review.csv"
            pd.DataFrame(
                [
                    review_row(
                        listing_reference="PRIVATE_LISTING_URL",
                        notes="PRIVATE_NOTES",
                        system_action="BUY_RAW_FLIP",
                        human_verdict="actionable",
                    )
                ]
            ).to_csv(source, index=False)
            stdout = StringIO()
            stderr = StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["--input", str(source)])

            self.assertEqual(exit_code, 0)
            self.assertIn("true_positive: 1", stdout.getvalue())
            self.assertIn("precision_pct: 100.0", stdout.getvalue())
            self.assertIn("issue_wrong_card_match: 0", stdout.getvalue())
            self.assertNotIn("PRIVATE_LISTING_URL", stdout.getvalue())
            self.assertNotIn("PRIVATE_NOTES", stdout.getvalue())
            self.assertEqual(stderr.getvalue(), "")

    def test_invalid_csv_error_is_sanitized(self):
        stderr = StringIO()
        unsafe_path = "/missing/PRIVATE_BETA_REVIEW.csv"

        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--input", unsafe_path])

        self.assertEqual(exit_code, 1)
        self.assertIn("could not be completed", stderr.getvalue())
        self.assertNotIn("PRIVATE_BETA_REVIEW", stderr.getvalue())

    def test_loader_preserves_valid_local_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "review.csv"
            pd.DataFrame([review_row()]).to_csv(source, index=False)

            loaded = load_beta_review_csv(source)

            self.assertEqual(loaded.loc[0, "listing_reference"], "local-listing-1")

    def test_loader_rejects_oversized_file_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "oversized.csv"
            with source.open("wb") as handle:
                handle.seek(MAX_BETA_REVIEW_BYTES)
                handle.write(b"x")

            with self.assertRaises(BetaReviewValidationError):
                load_beta_review_csv(source)


if __name__ == "__main__":
    unittest.main()
