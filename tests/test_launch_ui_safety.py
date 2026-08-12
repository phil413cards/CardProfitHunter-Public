from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def _streamlit_calls(tree: ast.AST, method: str) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "st"
            and function.attr == method
        ):
            calls.append(node)
    return calls


def _literal_label(call: ast.Call) -> str | None:
    if not call.args:
        return None
    value = call.args[0]
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


class LaunchUiSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_version_display_is_sourced_from_version_file(self):
        self.assertIn('VERSION_PATH.read_text(encoding="utf-8")', self.source)
        self.assertIn('page_title=f"CardProfitHunter {APPLICATION_VERSION}"', self.source)
        self.assertIn('st.title(f"CardProfitHunter {APPLICATION_VERSION}")', self.source)
        self.assertNotIn("Card Profit Hunter V5.1", self.source)
        self.assertNotIn("Professional Edition", self.source)

    def test_unfinished_dashboard_promises_are_not_rendered(self):
        self.assertNotIn("Inventory Manager", self.source)
        self.assertNotIn("PSA Pipeline", self.source)
        self.assertNotIn("arrives in V5.2", self.source)
        self.assertNotIn("arrives in V5.3", self.source)

    def test_destructive_buttons_require_explicit_confirmation(self):
        expected = {
            "Delete Search": "delete_confirmed",
            "Remove Item": "removal_confirmed",
        }
        buttons = {
            _literal_label(call): call
            for call in _streamlit_calls(self.tree, "button")
            if _literal_label(call) in expected
        }

        self.assertEqual(set(buttons), set(expected))
        for label, confirmation_name in expected.items():
            with self.subTest(button=label):
                disabled = next(
                    (keyword.value for keyword in buttons[label].keywords if keyword.arg == "disabled"),
                    None,
                )
                self.assertIsInstance(disabled, ast.UnaryOp)
                self.assertIsInstance(disabled.op, ast.Not)
                self.assertIsInstance(disabled.operand, ast.Name)
                self.assertEqual(disabled.operand.id, confirmation_name)

    def test_confirmation_widgets_are_scoped_to_selected_records(self):
        checkbox_keys = []
        for call in _streamlit_calls(self.tree, "checkbox"):
            label = _literal_label(call)
            if label and label.startswith("Confirm "):
                key = next(
                    (keyword.value for keyword in call.keywords if keyword.arg == "key"),
                    None,
                )
                checkbox_keys.append(ast.unparse(key) if key is not None else "")

        self.assertIn("f'confirm_saved_search_delete_{int(delete_id)}'", checkbox_keys)
        self.assertIn("f'confirm_watchlist_remove_{int(delete_id)}'", checkbox_keys)


if __name__ == "__main__":
    unittest.main()
