import ast
import csv
import math
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from csv_export_safety import (
    dataframe_to_spreadsheet_safe_csv,
    make_dataframe_spreadsheet_safe,
    sanitize_csv_cell,
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

        self.assertIsNone(result)
        self.assertEqual(row["title"], "'=1+1")
        self.assertEqual(row["price"], "10")
        self.assertEqual(source.loc[0, "title"], "=1+1")


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
        self.assertIn("dataframe_to_spreadsheet_safe_csv", calls)
        self.assertNotIn("to_csv", calls)

    def test_downloads_use_safe_csv_helper(self):
        expected_labels = {
            "Download Daily Buy Board CSV",
            "Download Buy Board CSV",
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

    def test_card_values_persistence_remains_unsanitized_internal_data(self):
        card_value_writes = [
            call
            for call in _calls_in(self.tree)
            if _call_name(call) == "to_csv"
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "validated_values"
        ]

        self.assertEqual(len(card_value_writes), 1)
        self.assertIn("CARD_VALUES_PATH", ast.unparse(card_value_writes[0]))


if __name__ == "__main__":
    unittest.main()
