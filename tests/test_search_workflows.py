import unittest

import pandas as pd

from search_workflows import (
    ANALYSIS_COLUMNS,
    DAILY_BOARD_METADATA_COLUMNS,
    EXPORT_TRACE_COLUMNS,
    build_run_outcome,
    clear_result_state,
    combine_board_results,
    empty_analysis_frame,
    prepare_results_export,
    stable_analysis_frame,
)


def scored_frame(title="Card A", score=80, roi=25):
    return pd.DataFrame([{
        "title": title,
        "total_score": score,
        "best_expected_roi_pct": roi,
        "saved_search": "Test Search",
        "search_query": "test cards",
    }])


class SearchWorkflowTests(unittest.TestCase):
    def test_all_empty_run_has_stable_empty_board(self):
        board = combine_board_results([pd.DataFrame(), empty_analysis_frame()])
        outcome = build_run_outcome(
            attempted_count=2,
            successful_count=2,
            empty_count=2,
            failed_count=0,
            result_count=len(board),
            completed_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(outcome.status, "empty")
        self.assertEqual(outcome.attempted_count, 2)
        self.assertEqual(outcome.successful_count, 2)
        self.assertEqual(outcome.empty_count, 2)
        self.assertEqual(outcome.failed_count, 0)
        self.assertEqual(outcome.result_count, 0)
        self.assertTrue(board.empty)
        self.assertIn("total_score", board.columns)
        self.assertIn("best_expected_roi_pct", board.columns)

    def test_all_failed_run_is_explicit(self):
        outcome = build_run_outcome(
            attempted_count=2,
            successful_count=0,
            empty_count=0,
            failed_count=2,
            result_count=0,
            errors=("Search A failed.", "Search B failed."),
            completed_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.failed_count, 2)
        self.assertEqual(len(outcome.errors), 2)

    def test_partial_success_preserves_successful_rows(self):
        board = combine_board_results([scored_frame()])
        outcome = build_run_outcome(
            attempted_count=2,
            successful_count=1,
            empty_count=0,
            failed_count=1,
            result_count=len(board),
            errors=("Search B failed.",),
            completed_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.result_count, 1)
        self.assertEqual(board.iloc[0]["title"], "Card A")

    def test_successful_run_filters_and_sorts_deterministically(self):
        board = combine_board_results([
            scored_frame("Low", score=50, roi=100),
            scored_frame("High", score=90, roi=20),
            scored_frame("Filtered", score=10, roi=500),
        ], minimum_score=25)
        outcome = build_run_outcome(
            attempted_count=3,
            successful_count=3,
            empty_count=0,
            failed_count=0,
            result_count=len(board),
            completed_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(outcome.status, "success")
        self.assertEqual(list(board["title"]), ["High", "Low"])

    def test_empty_analysis_schema_is_derived_from_profit_result(self):
        frame = empty_analysis_frame(DAILY_BOARD_METADATA_COLUMNS)

        self.assertEqual(
            tuple(frame.columns[:len(ANALYSIS_COLUMNS)]),
            ANALYSIS_COLUMNS,
        )
        self.assertEqual(
            tuple(frame.columns[-len(DAILY_BOARD_METADATA_COLUMNS):]),
            DAILY_BOARD_METADATA_COLUMNS,
        )

    def test_columnless_analysis_is_made_schema_stable(self):
        stable = stable_analysis_frame(pd.DataFrame())
        board = combine_board_results([pd.DataFrame()], minimum_score=50)

        self.assertTrue(stable.empty)
        self.assertEqual(tuple(stable.columns), ANALYSIS_COLUMNS)
        self.assertTrue(board.empty)
        self.assertIn("total_score", board.columns)

    def test_live_export_adds_traceability_without_mutating_results(self):
        source = pd.DataFrame([{"title": "Card A", "total_score": 80}])
        original = source.copy(deep=True)

        exported = prepare_results_export(
            source,
            application_version="5.2.46",
            completed_at="2026-08-13T12:00:00+00:00",
            search_query="Shohei Ohtani",
        )

        pd.testing.assert_frame_equal(source, original)
        self.assertEqual(
            tuple(exported.columns[:len(EXPORT_TRACE_COLUMNS)]),
            EXPORT_TRACE_COLUMNS,
        )
        self.assertEqual(exported.loc[0, "search_query"], "Shohei Ohtani")
        self.assertEqual(exported.loc[0, "application_version"], "5.2.46")
        self.assertEqual(
            exported.loc[0, "search_completed_at"],
            "2026-08-13T12:00:00+00:00",
        )

    def test_daily_export_preserves_each_rows_search_query(self):
        source = pd.DataFrame(
            [
                {"title": "Card A", "search_query": "Shohei Ohtani"},
                {"title": "Card B", "search_query": "Aaron Judge"},
            ]
        )

        exported = prepare_results_export(
            source,
            application_version="5.2.46",
            completed_at="2026-08-13T12:00:00+00:00",
        )

        self.assertEqual(
            exported["search_query"].tolist(),
            ["Shohei Ohtani", "Aaron Judge"],
        )
        self.assertEqual(
            exported["application_version"].tolist(),
            ["5.2.46", "5.2.46"],
        )

    def test_beginning_new_run_clears_stale_results_and_outcome(self):
        old_results = scored_frame("Stale Card")
        state = {
            "daily_board": old_results,
            "daily_board_outcome": "old outcome",
            "unrelated": "keep",
        }

        clear_result_state(state, "daily_board", "daily_board_outcome")

        self.assertNotIn("daily_board", state)
        self.assertNotIn("daily_board_outcome", state)
        self.assertEqual(state["unrelated"], "keep")


if __name__ == "__main__":
    unittest.main()
