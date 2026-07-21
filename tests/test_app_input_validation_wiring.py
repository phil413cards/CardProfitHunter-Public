import ast
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _called_function_names(node):
    calls = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.append((child.func.id, child.lineno))
        elif isinstance(child.func, ast.Attribute):
            calls.append((child.func.attr, child.lineno))
    return calls


def _button_block(tree, label):
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
            continue
        call = node.test
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "button"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == label
        ):
            continue
        return node
    raise AssertionError(f"Button block not found: {label}")


class AppInputValidationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def assert_call_precedes(self, block, earlier, later):
        calls = _called_function_names(block)
        earlier_lines = [line for name, line in calls if name == earlier]
        later_lines = [line for name, line in calls if name == later]
        self.assertTrue(earlier_lines, f"{earlier} call not found")
        self.assertTrue(later_lines, f"{later} call not found")
        self.assertLess(min(earlier_lines), min(later_lines))

    def test_save_search_validates_before_database_write(self):
        block = _button_block(self.tree, "Save / Update Search")
        self.assert_call_precedes(block, "validate_search_inputs", "save_search")

    def test_live_search_validates_before_credentials_and_network(self):
        block = _button_block(self.tree, "Run Live Search & Score")
        self.assert_call_precedes(block, "validate_search_inputs", "EbayCredentials")
        self.assert_call_precedes(block, "validate_search_inputs", "search_ebay")

    def test_daily_board_validates_each_search_before_network(self):
        block = _button_block(self.tree, "Run Daily Buy Board")
        self.assert_call_precedes(block, "validate_search_inputs", "search_ebay")

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())


if __name__ == "__main__":
    unittest.main()
