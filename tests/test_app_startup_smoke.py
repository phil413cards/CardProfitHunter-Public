from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

_SMOKE_SCRIPT = r"""
import os
import stat
from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

import database


network_attempts = []


def block_network(*args, **kwargs):
    network_attempts.append(True)
    raise RuntimeError("Network access is disabled during startup smoke tests.")


requests.sessions.Session.request = block_network

isolated_root = Path.cwd().resolve()
if Path(database.__file__).resolve().parent != isolated_root:
    print("APP_SMOKE_MODULE_ISOLATION_FAILURE")
    raise SystemExit(1)
if database.DB_PATH.resolve() != isolated_root / "data" / "card_profit_hunter.db":
    print("APP_SMOKE_DATABASE_ISOLATION_FAILURE")
    raise SystemExit(1)

try:
    app = AppTest.from_file("app.py", default_timeout=10).run()
except Exception:
    print("APP_SMOKE_STARTUP_FAILURE")
    raise SystemExit(1)

expected_tabs = [
    "Dashboard",
    "Daily Buy Board",
    "Live Search",
    "Saved Searches",
    "Watchlist",
    "Sample Analysis",
    "Card Values",
    "Setup",
]

if app.exception:
    print("APP_SMOKE_RENDER_EXCEPTION")
    raise SystemExit(1)
if app.error:
    print("APP_SMOKE_RENDER_ERROR")
    raise SystemExit(1)
if [tab.label for tab in app.tabs] != expected_tabs:
    print("APP_SMOKE_TAB_MISMATCH")
    raise SystemExit(1)
expected_title = "CardProfitHunter " + Path("VERSION").read_text().strip()
if [title.value for title in app.title] != [expected_title]:
    print("APP_SMOKE_VERSION_MISMATCH")
    raise SystemExit(1)
if network_attempts:
    print("APP_SMOKE_NETWORK_ATTEMPT")
    raise SystemExit(1)
if Path(".env").exists():
    print("APP_SMOKE_ENV_CREATED")
    raise SystemExit(1)

required_runtime_paths = [
    Path("data/card_profit_hunter.db"),
    Path("output/logs/application.log"),
]
if not all(path.is_file() and not path.is_symlink() for path in required_runtime_paths):
    print("APP_SMOKE_RUNTIME_STATE_MISSING")
    raise SystemExit(1)

if os.name == "posix":
    expected_modes = {
        Path("data"): 0o700,
        Path("data/card_profit_hunter.db"): 0o600,
        Path("output/logs"): 0o700,
        Path("output/logs/application.log"): 0o600,
    }
    for path, expected_mode in expected_modes.items():
        if stat.S_IMODE(path.stat().st_mode) != expected_mode:
            print("APP_SMOKE_PRIVATE_MODE_FAILURE")
            raise SystemExit(1)

print("APP_SMOKE_OK")
"""


class IsolatedStreamlitStartupSmokeTests(unittest.TestCase):
    def test_app_starts_without_network_or_real_runtime_state(self):
        with TemporaryDirectory() as temp_dir:
            isolated_root = Path(temp_dir) / "CardProfitHunter"
            isolated_root.mkdir()
            self.assertNotEqual(isolated_root, ROOT)
            for source in ROOT.glob("*.py"):
                shutil.copy2(source, isolated_root / source.name)
            shutil.copy2(ROOT / "VERSION", isolated_root / "VERSION")
            shutil.copytree(ROOT / "config", isolated_root / "config")
            shutil.copytree(ROOT / "sample_data", isolated_root / "sample_data")

            environment = os.environ.copy()
            for key in tuple(environment):
                if key.startswith("EBAY_"):
                    environment.pop(key)
            environment.update({
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(isolated_root),
                "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            })

            try:
                result = subprocess.run(
                    [sys.executable, "-B", "-c", _SMOKE_SCRIPT],
                    cwd=isolated_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self.fail("Isolated Streamlit startup smoke test timed out.")

            self.assertEqual(
                result.returncode,
                0,
                "Isolated Streamlit startup smoke test failed safely.",
            )
            self.assertIn("APP_SMOKE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
