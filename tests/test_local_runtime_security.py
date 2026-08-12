import ast
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from local_runtime_security import (
    LocalRuntimeSecurityError,
    secure_optional_private_file,
    secure_private_directory,
)


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class PrivateRuntimeFileTests(unittest.TestCase):
    def test_missing_optional_file_is_not_created(self):
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"

            result = secure_optional_private_file(env_path)

            self.assertFalse(result)
            self.assertFalse(env_path.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX permission modes required")
    def test_existing_file_is_repaired_without_changing_contents(self):
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
            env_path.chmod(0o644)

            result = secure_optional_private_file(env_path)

            self.assertTrue(result)
            self.assertEqual(env_path.read_text(encoding="utf-8"), "PRIVATE_TEST_VALUE")
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)

    def test_symlink_file_is_rejected_without_touching_target(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "private-target"
            target.write_text("PRIVATE_TEST_VALUE", encoding="utf-8")
            env_path = root / ".env"
            try:
                env_path.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks are unavailable")

            with self.assertRaises(LocalRuntimeSecurityError) as raised:
                secure_optional_private_file(env_path)

            self.assertEqual(target.read_text(encoding="utf-8"), "PRIVATE_TEST_VALUE")
            self.assertNotIn("PRIVATE_TEST_VALUE", str(raised.exception))
            self.assertNotIn(str(env_path), str(raised.exception))

    def test_non_regular_file_is_rejected(self):
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.mkdir()

            with self.assertRaises(LocalRuntimeSecurityError):
                secure_optional_private_file(env_path)

    @unittest.skipUnless(os.name == "posix", "POSIX permission modes required")
    def test_private_directory_is_created_with_private_mode(self):
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "nested" / "logs"

            result = secure_private_directory(directory)

            self.assertEqual(result, directory)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)


class AppEnvironmentSecurityWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())

    def test_environment_file_is_secured_before_loading(self):
        function = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "load_local_environment"
        )
        calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
        ]
        secure_call = next(
            call
            for call in calls
            if _call_name(call) == "secure_optional_private_file"
        )
        load_call = next(
            call for call in calls if _call_name(call) == "load_dotenv"
        )

        self.assertLess(secure_call.lineno, load_call.lineno)
        self.assertIn('ENV_PATH = ROOT / ".env"', self.source)

    def test_startup_uses_secured_environment_wrapper(self):
        startup_call = next(
            call
            for call in ast.walk(self.tree)
            if isinstance(call, ast.Call)
            and _call_name(call) == "run_startup_steps"
        )
        guarded_names = {
            node.id
            for node in ast.walk(startup_call)
            if isinstance(node, ast.Name)
        }

        self.assertIn("load_local_environment", guarded_names)
        self.assertNotIn("load_dotenv", guarded_names)


if __name__ == "__main__":
    unittest.main()
