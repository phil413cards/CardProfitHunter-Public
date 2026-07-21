import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


class AppEnvironmentSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_environment_lookup_has_no_production_fallback(self):
        calls = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == "getenv"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "EBAY_ENVIRONMENT"
        ]

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args), 1)
        self.assertEqual(calls[0].keywords, [])
        self.assertNotIn('os.getenv("EBAY_ENVIRONMENT", "production")', self.source)

    def test_missing_environment_defaults_to_sandbox(self):
        self.assertIn(
            "if configured_environment is None or not configured_environment.strip():",
            self.source,
        )
        self.assertIn('env_default = "sandbox"', self.source)

    def test_invalid_environment_is_rejected_without_a_default(self):
        self.assertIn("except EbayApiError as exc:", self.source)
        self.assertIn("env_default = None", self.source)
        self.assertIn("environment_error = str(exc)", self.source)
        self.assertIn("st.error(environment_error)", self.source)
        self.assertIn(
            "index=environment_options.index(env_default) if env_default else None",
            self.source,
        )

    def test_sandbox_precedes_explicit_production_option(self):
        assignments = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "environment_options"
                for target in node.targets
            )
        ]

        self.assertEqual(len(assignments), 1)
        self.assertEqual(
            ast.literal_eval(assignments[0].value),
            ["sandbox", "production"],
        )
        self.assertNotIn(
            'environment_options = ["production", "sandbox"]',
            self.source,
        )

        production_values = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.Constant) and node.value == "production"
        ]
        self.assertEqual(len(production_values), 1)


if __name__ == "__main__":
    unittest.main()
