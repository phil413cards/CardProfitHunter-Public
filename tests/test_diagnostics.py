import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diagnostics import (
    ApplicationStartupError,
    LOGGER_NAME,
    REDACTED,
    StartupStep,
    build_sanitized_diagnostics,
    configure_local_logger,
    format_exception_diagnostic,
    log_sanitized_exception,
    redact_sensitive_text,
    run_startup_steps,
    startup_failure_diagnostics,
)


class DiagnosticsTestCase(unittest.TestCase):
    def tearDown(self):
        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


class SensitiveTextRedactionTests(DiagnosticsTestCase):
    def test_authorization_header_values_are_fully_redacted(self):
        cases = (
            (
                "Authorization: Basic PRIVATE_BASIC_VALUE",
                "Authorization: [REDACTED]",
                ("Basic", "PRIVATE_BASIC_VALUE"),
            ),
            (
                "Authorization: Bearer PRIVATE_TOKEN",
                "Authorization: [REDACTED]",
                ("Bearer", "PRIVATE_TOKEN"),
            ),
            (
                'Authorization: Digest username="private", realm="secret", nonce="abc"',
                "Authorization: [REDACTED]",
                ("Digest", "private", "secret", "abc"),
            ),
            (
                "Authorization: Custom multi token private value",
                "Authorization: [REDACTED]",
                ("Custom", "multi", "private", "value"),
            ),
            (
                "authorization: lowercase private value",
                "authorization: [REDACTED]",
                ("lowercase", "private", "value"),
            ),
            (
                "AuThOrIzAtIoN: Mixed CASE private value",
                "AuThOrIzAtIoN: [REDACTED]",
                ("Mixed", "CASE", "private", "value"),
            ),
        )

        for source, expected, private_fragments in cases:
            with self.subTest(source=source):
                redacted = redact_sensitive_text(source)
                self.assertEqual(redacted, expected)
                for fragment in private_fragments:
                    self.assertNotIn(fragment, redacted)

    def test_sensitive_key_values_are_redacted(self):
        cases = (
            "token=private-token-value",
            "secret: private-secret-value",
            "password='private-password-value'",
            'client_secret="private-client-secret"',
            "authorization=private-authorization-value",
            "api_key: private-api-key",
            '"access_token": "private-json-token"',
        )

        for text in cases:
            with self.subTest(text=text):
                redacted = redact_sensitive_text(text)
                self.assertIn(REDACTED, redacted)
                self.assertNotIn("private-", redacted)

    def test_bearer_values_are_redacted(self):
        raw_token = "private-bearer-token.abc123"

        redacted = redact_sensitive_text(
            f"Request rejected for Bearer {raw_token}"
        )

        self.assertIn(REDACTED, redacted)
        self.assertNotIn(raw_token, redacted)

    def test_env_style_lines_are_redacted_without_losing_safe_context(self):
        text = (
            "EBAY_CLIENT_SECRET=private-client-secret\n"
            "export ACCESS_TOKEN = private-access-token\n"
            "EBAY_ENVIRONMENT=sandbox\n"
        )

        redacted = redact_sensitive_text(text)

        self.assertNotIn("private-client-secret", redacted)
        self.assertNotIn("private-access-token", redacted)
        self.assertIn("EBAY_CLIENT_SECRET=[REDACTED]", redacted)
        self.assertIn("EBAY_ENVIRONMENT=sandbox", redacted)

    def test_normal_operational_text_is_preserved(self):
        text = "event=DATABASE_BACKUP_FAILED context=database.backup.create"

        self.assertEqual(redact_sensitive_text(text), text)


class SanitizedExceptionTests(DiagnosticsTestCase):
    def test_exception_diagnostic_excludes_message_and_traceback(self):
        raw_detail = "token=private-token /private/path raw database row"

        message = format_exception_diagnostic(
            "DATABASE_BACKUP_FAILED",
            RuntimeError(raw_detail),
            "database.backup.create",
        )

        self.assertIn("event=DATABASE_BACKUP_FAILED", message)
        self.assertIn("context=database.backup.create", message)
        self.assertIn("exception_type=RuntimeError", message)
        self.assertNotIn(raw_detail, message)
        self.assertNotIn("private-token", message)
        self.assertNotIn("Traceback", message)

    def test_unsafe_event_and_context_fail_closed(self):
        message = format_exception_diagnostic(
            "BAD event private-token",
            ValueError("private-message"),
            "unsafe context /private/path",
        )

        self.assertIn("event=APPLICATION_FAILURE", message)
        self.assertIn("context=application.unknown", message)
        self.assertNotIn("private", message)


class LocalLoggerTests(DiagnosticsTestCase):
    def test_logger_creates_missing_directory_and_writes_utc_diagnostic(self):
        with TemporaryDirectory() as temp_dir:
            log_directory = Path(temp_dir) / "nested" / "logs"
            setup = configure_local_logger(log_directory)

            self.assertTrue(setup.enabled)
            self.assertIsNone(setup.warning)
            log_sanitized_exception(
                setup.logger,
                "SAMPLE_ANALYSIS_FAILED",
                RuntimeError("password=private-password"),
                "sample.analysis.run",
            )
            for handler in setup.logger.handlers:
                handler.flush()
            contents = (log_directory / "application.log").read_text(
                encoding="utf-8"
            )

        self.assertIn("Z level=ERROR", contents)
        self.assertIn("event=SAMPLE_ANALYSIS_FAILED", contents)
        self.assertIn("context=sample.analysis.run", contents)
        self.assertIn("exception_type=RuntimeError", contents)
        self.assertNotIn("private-password", contents)
        self.assertNotIn("Traceback", contents)

    def test_repeated_setup_does_not_add_duplicate_file_handlers(self):
        with TemporaryDirectory() as temp_dir:
            log_directory = Path(temp_dir) / "logs"

            first = configure_local_logger(log_directory)
            second = configure_local_logger(log_directory)

            managed_file_handlers = [
                handler
                for handler in second.logger.handlers
                if getattr(handler, "_card_profit_diagnostics", False)
                and isinstance(handler, logging.FileHandler)
            ]
            self.assertTrue(first.enabled)
            self.assertTrue(second.enabled)
            self.assertEqual(len(managed_file_handlers), 1)

    def test_logger_setup_failure_is_safe_and_nonfatal(self):
        with TemporaryDirectory() as temp_dir:
            with patch(
                "diagnostics.logging.FileHandler",
                side_effect=OSError("private filesystem detail"),
            ):
                setup = configure_local_logger(Path(temp_dir) / "logs")

            self.assertFalse(setup.enabled)
            self.assertIsNotNone(setup.warning)
            self.assertNotIn("private filesystem detail", setup.warning)
            log_sanitized_exception(
                setup.logger,
                "APPLICATION_FAILURE",
                RuntimeError("private exception"),
                "application.unknown",
            )


class StartupBoundaryTests(DiagnosticsTestCase):
    def test_successful_steps_run_in_order_and_return_results(self):
        events = []

        def operation(name, value):
            def run():
                events.append(name)
                return value
            return run

        results = run_startup_steps((
            StartupStep(
                "environment",
                "STARTUP_ENVIRONMENT",
                "Environment failed.",
                operation("environment", True),
            ),
            StartupStep(
                "database",
                "STARTUP_DATABASE",
                "Database failed.",
                operation("database", None),
            ),
            StartupStep(
                "settings",
                "STARTUP_SETTINGS",
                "Settings failed.",
                operation("settings", {"safe": True}),
            ),
        ))

        self.assertEqual(events, ["environment", "database", "settings"])
        self.assertTrue(results["environment"])
        self.assertIsNone(results["database"])
        self.assertEqual(results["settings"], {"safe": True})

    def test_failure_logs_through_callback_and_stops_later_steps(self):
        events = []
        callback_values = []
        raw_detail = "client_secret=private-secret and /private/path"

        def fail():
            events.append("database")
            raise RuntimeError(raw_detail)

        def must_not_run():
            events.append("settings")

        with self.assertRaises(ApplicationStartupError) as raised:
            run_startup_steps((
                StartupStep(
                    "database",
                    "STARTUP_DATABASE",
                    "The local database could not be initialized.",
                    fail,
                ),
                StartupStep(
                    "settings",
                    "STARTUP_SETTINGS",
                    "Settings failed.",
                    must_not_run,
                ),
            ), on_error=lambda code, error, context: callback_values.append(
                format_exception_diagnostic(code, error, context)
            ))

        error = raised.exception
        self.assertEqual(events, ["database"])
        self.assertEqual(error.code, "STARTUP_DATABASE")
        self.assertEqual(
            str(error),
            "The local database could not be initialized.",
        )
        self.assertNotIn(raw_detail, str(error))
        self.assertTrue(error.__suppress_context__)
        self.assertEqual(len(callback_values), 1)
        self.assertIn("context=startup.database", callback_values[0])
        self.assertNotIn(raw_detail, callback_values[0])

        report = startup_failure_diagnostics(error)
        self.assertEqual(report["startup_status"], "failed")
        self.assertEqual(report["diagnostic_code"], "STARTUP_DATABASE")
        self.assertNotIn(raw_detail, json.dumps(report))


class SanitizedReportTests(DiagnosticsTestCase):
    def setUp(self):
        super().setUp()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.version_path = self.root / "VERSION"
        self.database_path = self.root / "private-user-database.db"
        self.settings_path = self.root / "private-settings.json"
        self.valuation_path = self.root / "private-valuations.csv"
        self.output_path = self.root / "private-output"
        self.version_path.write_text("5.1.1\n", encoding="utf-8")
        self.database_path.touch()
        self.settings_path.touch()
        self.valuation_path.touch()
        self.output_path.mkdir()

    def _build(self, environ, logging_enabled=True):
        return build_sanitized_diagnostics(
            environ=environ,
            version_path=self.version_path,
            database_path=self.database_path,
            settings_path=self.settings_path,
            valuation_path=self.valuation_path,
            output_path=self.output_path,
            supported_schema_version=1,
            local_logging_enabled=logging_enabled,
        )

    def test_report_contains_safe_status_and_presence_fields(self):
        report = self._build({
            "EBAY_ENVIRONMENT": "sandbox",
            "EBAY_CLIENT_ID": "configured-client-id",
            "EBAY_CLIENT_SECRET": "configured-client-secret",
        })

        self.assertEqual(report["startup_status"], "ready")
        self.assertEqual(report["application_version"], "5.1.1")
        self.assertEqual(report["ebay_environment"], "sandbox")
        self.assertTrue(report["ebay_client_id_configured"])
        self.assertTrue(report["ebay_client_secret_configured"])
        self.assertTrue(report["database_present"])
        self.assertTrue(report["settings_file_present"])
        self.assertTrue(report["valuation_file_present"])
        self.assertTrue(report["output_directory_present"])
        self.assertEqual(report["supported_schema_version"], 1)
        self.assertEqual(report["local_diagnostic_logging"], "enabled")
        self.assertEqual(
            set(report["dependencies"]),
            {"streamlit", "pandas", "requests", "python-dotenv"},
        )

    def test_report_never_contains_secrets_paths_or_unrelated_environment(self):
        unsafe_values = (
            "private-client-id-value",
            "private-client-secret-value",
            "private-marketplace-value",
            "unrelated-private-value",
            str(self.root),
        )
        report = self._build({
            "EBAY_ENVIRONMENT": "production-with-private-suffix",
            "EBAY_CLIENT_ID": unsafe_values[0],
            "EBAY_CLIENT_SECRET": unsafe_values[1],
            "EBAY_MARKETPLACE_ID": unsafe_values[2],
            "UNRELATED_SECRET": unsafe_values[3],
        }, logging_enabled=False)

        serialized = json.dumps(report, sort_keys=True)
        self.assertEqual(report["ebay_environment"], "invalid")
        self.assertEqual(report["local_diagnostic_logging"], "unavailable")
        for unsafe in unsafe_values:
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, serialized)


if __name__ == "__main__":
    unittest.main()
