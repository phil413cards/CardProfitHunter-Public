import ast
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class AppDiagnosticsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.calls = [
            node for node in ast.walk(cls.tree) if isinstance(node, ast.Call)
        ]

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())

    def test_logger_is_configured_after_page_setup_and_before_startup(self):
        page_config = next(
            call for call in self.calls if _call_name(call) == "set_page_config"
        )
        logger_setup = next(
            call
            for call in self.calls
            if _call_name(call) == "configure_local_logger"
        )
        startup = next(
            call for call in self.calls if _call_name(call) == "run_startup_steps"
        )

        self.assertLess(page_config.lineno, logger_setup.lineno)
        self.assertLess(logger_setup.lineno, startup.lineno)
        self.assertIn('DIAGNOSTIC_LOG_DIR = OUTPUT_DIR / "logs"', self.source)

    def test_startup_steps_are_guarded_and_log_sanitized_failures(self):
        startup_call = next(
            call for call in self.calls if _call_name(call) == "run_startup_steps"
        )
        guarded_names = {
            node.id for node in ast.walk(startup_call) if isinstance(node, ast.Name)
        }
        keyword_names = {keyword.arg for keyword in startup_call.keywords}

        self.assertTrue({
            "load_dotenv",
            "init_db",
            "load_settings",
            "load_valuation_csv",
            "build_sanitized_diagnostics",
            "log_sanitized_exception",
        }.issubset(guarded_names))
        self.assertIn("on_error", keyword_names)

    def test_startup_boundary_stops_with_sanitized_diagnostics(self):
        handlers = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "ApplicationStartupError"
        ]
        self.assertEqual(len(handlers), 1)
        calls = {
            _call_name(call)
            for call in ast.walk(handlers[0])
            if isinstance(call, ast.Call)
        }
        self.assertTrue({"error", "json", "stop"}.issubset(calls))
        self.assertNotIn("exception", calls)

    def test_expected_recoverable_flows_have_diagnostic_event_codes(self):
        expected_event_codes = {
            "SETTINGS_VALIDATION_FAILED",
            "SETTINGS_SAVE_FAILED",
            "DAILY_SEARCH_API_FAILED",
            "DAILY_SEARCH_VALIDATION_FAILED",
            "DAILY_SEARCH_PROCESSING_FAILED",
            "DAILY_OUTPUT_SAVE_FAILED",
            "DAILY_DOWNLOAD_PREPARE_FAILED",
            "LIVE_SEARCH_VALIDATION_FAILED",
            "LIVE_SEARCH_API_FAILED",
            "LIVE_SEARCH_PROCESSING_FAILED",
            "LIVE_OUTPUT_SAVE_FAILED",
            "LIVE_DOWNLOAD_PREPARE_FAILED",
            "WATCHLIST_DOWNLOAD_PREPARE_FAILED",
            "SAMPLE_CSV_VALIDATION_FAILED",
            "SAMPLE_CSV_LOAD_FAILED",
            "SAMPLE_ANALYSIS_FAILED",
            "SAMPLE_OUTPUT_SAVE_FAILED",
            "CARD_VALUES_VALIDATION_FAILED",
            "CARD_VALUES_SAVE_FAILED",
            "DATABASE_BACKUP_FAILED",
            "RETENTION_PREVIEW_FAILED",
            "RETENTION_APPLY_FAILED",
        }

        for event_code in expected_event_codes:
            with self.subTest(event_code=event_code):
                self.assertIn(f'"{event_code}"', self.source)

    def test_downloads_use_guarded_csv_preparation(self):
        download_handlers = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ExceptHandler)
            and any(
                _call_name(call) == "log_sanitized_exception"
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            )
        ]
        handled_event_codes = {
            constant.value
            for handler in download_handlers
            for constant in ast.walk(handler)
            if isinstance(constant, ast.Constant)
            and constant.value in {
                "DAILY_DOWNLOAD_PREPARE_FAILED",
                "LIVE_DOWNLOAD_PREPARE_FAILED",
                "WATCHLIST_DOWNLOAD_PREPARE_FAILED",
            }
        }

        self.assertEqual(handled_event_codes, {
            "DAILY_DOWNLOAD_PREPARE_FAILED",
            "LIVE_DOWNLOAD_PREPARE_FAILED",
            "WATCHLIST_DOWNLOAD_PREPARE_FAILED",
        })

    def test_normal_user_flows_do_not_render_or_log_tracebacks(self):
        self.assertNotIn("st.exception", self.source)
        self.assertNotIn("logger.exception", self.source)
        self.assertNotIn("diagnostic_logger.exception", self.source)
        self.assertNotIn("exc_info=", self.source)

    def test_setup_renders_sanitized_report_and_local_logging_status(self):
        self.assertIn(
            'st.subheader("Sanitized Application Diagnostics")',
            self.source,
        )
        self.assertIn("st.json(startup_diagnostics)", self.source)
        self.assertIn("local_logging_enabled=logger_setup.enabled", self.source)
        self.assertIn("output/logs/application.log", self.source)
        self.assertIn("environ=os.environ", self.source)
        self.assertNotIn("dict(os.environ)", self.source)


if __name__ == "__main__":
    unittest.main()
