from __future__ import annotations

import ast
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent


class UnittestDiscoveryCompletenessTests(unittest.TestCase):
    def test_no_module_level_test_functions_are_silently_skipped(self):
        skipped: list[str] = []

        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        skipped.append(f"{path.name}:{node.lineno}:{node.name}")

        self.assertEqual(
            skipped,
            [],
            "Canonical unittest discovery skips module-level test functions: "
            + ", ".join(skipped),
        )


if __name__ == "__main__":
    unittest.main()
