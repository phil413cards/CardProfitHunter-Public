import ast
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class AppExportTraceabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.prepare_calls = [
            call
            for call in ast.walk(cls.tree)
            if isinstance(call, ast.Call)
            and _call_name(call) == "prepare_results_export"
        ]

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())

    def test_search_file_and_download_exports_add_version_and_completion(self):
        self.assertEqual(len(self.prepare_calls), 4)

        for call in self.prepare_calls:
            with self.subTest(line=call.lineno):
                source = ast.unparse(call)
                self.assertIn("application_version=APPLICATION_VERSION", source)
                self.assertIn("completed_at=", source)

    def test_live_export_uses_query_captured_from_completed_run(self):
        live_calls = [
            call
            for call in self.prepare_calls
            if any(keyword.arg == "search_query" for keyword in call.keywords)
        ]

        self.assertEqual(len(live_calls), 2)
        self.assertIn(
            'st.session_state["live_search_query"] = completed_query',
            self.source,
        )
        self.assertIn(
            'st.session_state.pop("live_search_query", None)',
            self.source,
        )
        self.assertNotIn("search_query=q", self.source)

    def test_daily_export_preserves_per_row_query(self):
        daily_calls = [
            call
            for call in self.prepare_calls
            if not any(keyword.arg == "search_query" for keyword in call.keywords)
        ]

        self.assertEqual(len(daily_calls), 2)
        for call in daily_calls:
            self.assertEqual(ast.unparse(call.args[0]), "board")


if __name__ == "__main__":
    unittest.main()
