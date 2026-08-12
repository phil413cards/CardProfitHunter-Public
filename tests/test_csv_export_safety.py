import ast
import csv
import math
import os
import stat
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from csv_export_safety import (
    CsvExportError,
    dataframe_to_spreadsheet_safe_csv,
    make_dataframe_spreadsheet_safe,
    sanitize_csv_cell,
    write_dataframe_spreadsheet_safe_csv,
)


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls_in(node):
    return [child for child in ast.walk(node) if isinstance(child, ast.Call)]


class CsvCellSafetyTests(unittest.TestCase):
    def test_dangerous_strings_are_neutralized(self):
        cases = (
            ("equals", "=HYPERLINK(\"https://example.invalid\")"),
            ("plus", "+SUM(1,1)"),
            ("minus", "-10+20"),
            ("at", "@cmd"),
            ("leading spaces", "   =HYPERLINK(\"https://example.invalid\")"),
            ("leading tab", "\t=HYPERLINK(\"https://example.invalid\")"),
            ("leading carriage return", "\r=HYPERLINK(\"https://example.invalid\")"),
            ("tab prefix", "\tcmd"),
            ("carriage return prefix", "\rcmd"),
            ("whitespace before tab", "  \tcmd"),
        )

        for name, value in cases:
            with self.subTest(name=name):
                self.assertEqual(sanitize_csv_cell(value), "'" + value)

    def test_safe_strings_and_blank_strings_are_unchanged(self):
        for value in ("Normal card title", "https://example.com/item/123", "", "   "):
            with self.subTest(value=value):
                self.assertEqual(sanitize_csv_cell(value), value)

    def test_real_numbers_remain_numeric(self):
        for value in (0, 42, -10, 3.25, -4.5):
            with self.subTest(value=value):
                result = sanitize_csv_cell(value)
                self.assertEqual(result, value)
                self.assertIs(type(result), type(value))

    def test_missing_values_remain_missing(self):
        self.assertIsNone(sanitize_csv_cell(None))
        nan_value = float("nan")
        self.assertTrue(math.isnan(sanitize_csv_cell(nan_value)))
        self.assertIs(sanitize_csv_cell(pd.NA), pd.NA)

    def test_sanitization_is_idempotent(self):
        for value in ("=1+1", "+SUM(1,1)", "-10+20", "@cmd", "  =1+1", "\t=1+1"):
            with self.subTest(value=value):
                once = sanitize_csv_cell(value)
                twice = sanitize_csv_cell(once)
                self.assertEqual(twice, once)
                self.assertFalse(twice.startswith("''"))


class CsvDataFrameSafetyTests(unittest.TestCase):
    def test_all_untrusted_string_fields_are_sanitized_without_mutation(self):
        source = pd.DataFrame([{
            "title": "=HYPERLINK(\"https://example.invalid\")",
            "notes": "+SUM(1,1)",
            "seller_username": "@cmd",
            "item_url": "  =HYPERLINK(\"https://example.invalid\")",
            "condition": "\t=cmd",
            "flags": "\r=cmd",
            "matched_card": "-10+20",
            "saved_search": " =cmd",
            "price": -10.0,
        }])
        original = source.copy(deep=True)

        safe = make_dataframe_spreadsheet_safe(source)

        pd.testing.assert_frame_equal(source, original)
        self.assertIsNot(safe, source)
        for column in (
            "title",
            "notes",
            "seller_username",
            "item_url",
            "condition",
            "flags",
            "matched_card",
            "saved_search",
        ):
            self.assertTrue(safe.loc[0, column].startswith("'"), column)
        self.assertEqual(safe.loc[0, "price"], -10.0)

    def test_generated_csv_contains_sanitized_cells_and_blank_missing_values(self):
        source = pd.DataFrame([{
            "title": "=HYPERLINK(\"https://example.invalid\")",
            "notes": "+SUM(1,1)",
            "seller_username": "@cmd",
            "price": 12.5,
            "missing_none": None,
            "missing_nan": float("nan"),
            "missing_pd_na": pd.NA,
            "blank": "",
        }])

        exported = dataframe_to_spreadsheet_safe_csv(source)
        row = next(csv.DictReader(StringIO(exported)))

        self.assertEqual(row["title"], "'=HYPERLINK(\"https://example.invalid\")")
        self.assertEqual(row["notes"], "'+SUM(1,1)")
        self.assertEqual(row["seller_username"], "'@cmd")
        self.assertEqual(row["price"], "12.5")
        self.assertEqual(row["missing_none"], "")
        self.assertEqual(row["missing_nan"], "")
        self.assertEqual(row["missing_pd_na"], "")
        self.assertEqual(row["blank"], "")

    def test_generated_file_contains_sanitized_cells(self):
        source = pd.DataFrame([{"title": "=1+1", "price": 10}])

        with TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "export.csv"
            result = dataframe_to_spreadsheet_safe_csv(source, destination)
            with destination.open(encoding="utf-8") as exported_file:
                row = next(csv.DictReader(exported_file))
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(destination.stat().st_mode),
                    0o600,
                )

        self.assertIsNone(result)
        self.assertEqual(row["title"], "'=1+1")
        self.assertEqual(row["price"], "10")
        self.assertEqual(source.loc[0, "title"], "=1+1")


class PrivateCsvFileSafetyTests(unittest.TestCase):
    def test_private_writer_is_atomic_and_spreadsheet_safe(self):
        source = pd.DataFrame([{"title": "=1+1", "price": 10}])
        original = source.copy(deep=True)

        with TemporaryDirectory() as temp_dir:
            output_directory = Path(temp_dir) / "output"
            destination = output_directory / "results.csv"

            result = write_dataframe_spreadsheet_safe_csv(source, destination)

            with destination.open(encoding="utf-8") as exported_file:
                row = next(csv.DictReader(exported_file))
            self.assertEqual(result, destination)
            self.assertEqual(row["title"], "'=1+1")
            self.assertEqual(row["price"], "10")
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(output_directory.stat().st_mode),
                    0o700,
                )
                self.assertEqual(
                    stat.S_IMODE(destination.stat().st_mode),
                    0o600,
                )

        pd.testing.assert_frame_equal(source, original)

    def test_replace_failure_preserves_original_and_removes_temporary_file(self):
        source = pd.DataFrame([{"title": "safe replacement"}])

        with TemporaryDirectory() as temp_dir:
            output_directory = Path(temp_dir) / "output"
            output_directory.mkdir()
            destination = output_directory / "results.csv"
            destination.write_text("original private output", encoding="utf-8")

            with patch(
                "local_runtime_security.os.replace",
                side_effect=OSError("private filesystem detail"),
            ):
                with self.assertRaises(CsvExportError) as raised:
                    write_dataframe_spreadsheet_safe_csv(source, destination)

            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                "original private output",
            )
            self.assertEqual(list(output_directory.iterdir()), [destination])
            self.assertEqual(
                str(raised.exception),
                "Generated CSV could not be saved safely.",
            )
            self.assertNotIn("private filesystem detail", str(raised.exception))
            self.assertNotIn(str(destination), str(raised.exception))

    def test_symlink_destination_is_rejected_without_touching_target(self):
        source = pd.DataFrame([{"title": "safe replacement"}])

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_directory = root / "output"
            output_directory.mkdir()
            external_file = root / "private-target.csv"
            external_file.write_text("private existing content", encoding="utf-8")
            destination = output_directory / "results.csv"
            try:
                destination.symlink_to(external_file)
            except OSError:
                self.skipTest("Symlinks are unavailable")

            with self.assertRaises(CsvExportError):
                write_dataframe_spreadsheet_safe_csv(source, destination)

            self.assertEqual(
                external_file.read_text(encoding="utf-8"),
                "private existing content",
            )

    def test_symlink_output_directory_is_rejected_without_writing_target(self):
        source = pd.DataFrame([{"title": "safe replacement"}])

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            external_directory = root / "external"
            external_directory.mkdir()
            output_directory = root / "output"
            try:
                output_directory.symlink_to(
                    external_directory,
                    target_is_directory=True,
                )
            except OSError:
                self.skipTest("Symlinks are unavailable")

            with self.assertRaises(CsvExportError):
                write_dataframe_spreadsheet_safe_csv(
                    source,
                    output_directory / "results.csv",
                )

            self.assertEqual(list(external_directory.iterdir()), [])


class AppCsvExportWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_save_output_uses_safe_csv_helper(self):
        save_output = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "save_output"
        )
        calls = {_call_name(call) for call in _calls_in(save_output)}
        self.assertIn("write_dataframe_spreadsheet_safe_csv", calls)
        self.assertNotIn("dataframe_to_spreadsheet_safe_csv", calls)
        self.assertNotIn("to_csv", calls)
        self.assertNotIn("mkdir", calls)

    def test_downloads_use_safe_csv_helper(self):
        expected_labels = {
            "Download Daily Buy Board CSV",
            "Download Search Results CSV",
            "Download Watchlist CSV",
        }
        checked_labels = set()

        for call in _calls_in(self.tree):
            if _call_name(call) != "download_button" or not call.args:
                continue
            label = call.args[0]
            if not isinstance(label, ast.Constant) or label.value not in expected_labels:
                continue
            nested_calls = {_call_name(nested) for nested in _calls_in(call)}
            self.assertIn("dataframe_to_spreadsheet_safe_csv", nested_calls)
            self.assertNotIn("to_csv", nested_calls)
            checked_labels.add(label.value)

        self.assertEqual(checked_labels, expected_labels)

    def test_card_values_persistence_uses_internal_atomic_helper(self):
        card_value_writes = [
            call
            for call in _calls_in(self.tree)
            if _call_name(call) == "save_valuation_frame_atomically"
        ]

        self.assertEqual(len(card_value_writes), 1)
        self.assertIn("CARD_VALUES_PATH", ast.unparse(card_value_writes[0]))
        nested_calls = {_call_name(call) for call in _calls_in(card_value_writes[0])}
        self.assertNotIn("dataframe_to_spreadsheet_safe_csv", nested_calls)


if __name__ == "__main__":
    unittest.main()
