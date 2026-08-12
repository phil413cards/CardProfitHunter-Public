from __future__ import annotations

import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from input_validation import InputValidationError, load_settings_file, load_valuation_csv
from local_file_persistence import (
    LocalPersistenceError,
    save_settings_atomically,
    save_valuation_frame_atomically,
)


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def valid_settings() -> dict:
    return {
        "ebay_fee_pct": 0.1325,
        "purchase_tax_pct": 0.08,
        "promoted_listing_fee_pct": 0.02,
        "return_defect_allowance_pct": 0.03,
        "grading_loss_risk_pct": 0.05,
        "raw_flip_shipping_allowance": 5.0,
        "psa_grading_fee": 25.0,
        "psa_shipping_insurance_allowance": 10.0,
        "psa_selling_shipping_allowance": 5.0,
        "minimum_raw_flip_profit": 20.0,
        "minimum_raw_flip_roi_pct": 30.0,
        "minimum_psa_expected_profit": 40.0,
        "minimum_psa_expected_roi_pct": 40.0,
        "offer_safety_margin_pct": 0.05,
        "max_offer_market_pct": 0.9,
        "raw_only": True,
    }


def valid_valuations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "keyword": "2024 Topps Chrome Test Player #150 Refractor",
                "raw_market_value": 50.0,
                "psa9_value": 70.0,
                "psa10_value": 150.0,
                "gem_rate_estimate": 0.25,
                "psa9_rate_estimate": 0.50,
                "verification_status": "verified",
                "verified_at": "2026-08-01",
                "expires_at": "2026-09-01",
                "source_url": "https://example.com/verified-comps",
                "comp_count": 3,
                "notes": "Verified sold comparables",
            }
        ]
    )


class AtomicSettingsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "settings.json"

    def temp_files(self) -> list[Path]:
        return list(self.path.parent.glob(f".{self.path.name}.*.tmp"))

    def test_valid_settings_are_written_and_round_trip(self):
        result = save_settings_atomically(self.path, valid_settings())

        self.assertEqual(result, load_settings_file(self.path))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), result)
        self.assertEqual(self.temp_files(), [])

    def test_existing_file_mode_is_preserved(self):
        self.path.write_text(json.dumps(valid_settings()), encoding="utf-8")
        self.path.chmod(0o640)

        save_settings_atomically(self.path, valid_settings())

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_invalid_settings_preserve_original(self):
        original = b"original-settings"
        self.path.write_bytes(original)
        settings = valid_settings()
        settings["ebay_fee_pct"] = -1

        with self.assertRaises(InputValidationError):
            save_settings_atomically(self.path, settings)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])

    def test_replace_failure_preserves_original_and_removes_temp(self):
        original = b"original-settings"
        self.path.write_bytes(original)

        with patch("local_file_persistence.os.replace", side_effect=OSError("PRIVATE_PATH")):
            with self.assertRaisesRegex(
                LocalPersistenceError,
                "Local file could not be saved safely",
            ) as raised:
                save_settings_atomically(self.path, valid_settings())

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])
        self.assertNotIn("PRIVATE_PATH", str(raised.exception))
        self.assertNotIn(str(self.path), str(raised.exception))

    def test_serialization_failure_preserves_original_and_is_sanitized(self):
        original = b"original-settings"
        self.path.write_bytes(original)
        settings = valid_settings()
        settings["private_extension"] = object()

        with self.assertRaises(LocalPersistenceError) as raised:
            save_settings_atomically(self.path, settings)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])
        self.assertNotIn("private_extension", str(raised.exception))

    def test_fsync_failure_preserves_original_and_removes_temp(self):
        original = b"original-settings"
        self.path.write_bytes(original)

        with patch("local_file_persistence.os.fsync", side_effect=OSError("PRIVATE_DATA")):
            with self.assertRaises(LocalPersistenceError) as raised:
                save_settings_atomically(self.path, valid_settings())

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])
        self.assertNotIn("PRIVATE_DATA", str(raised.exception))


class AtomicValuationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "card_values.csv"

    def temp_files(self) -> list[Path]:
        return list(self.path.parent.glob(f".{self.path.name}.*.tmp"))

    def test_valid_valuations_are_written_without_mutating_source(self):
        source = valid_valuations()
        original = source.copy(deep=True)

        result = save_valuation_frame_atomically(self.path, source)
        loaded = load_valuation_csv(self.path)

        pd.testing.assert_frame_equal(source, original)
        pd.testing.assert_frame_equal(result, loaded)
        self.assertEqual(self.temp_files(), [])

    def test_invalid_valuations_preserve_original(self):
        original = b"original-valuations"
        self.path.write_bytes(original)
        frame = valid_valuations()
        frame.loc[0, "raw_market_value"] = -1

        with self.assertRaises(InputValidationError):
            save_valuation_frame_atomically(self.path, frame)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])

    def test_temp_validation_failure_preserves_original_and_is_sanitized(self):
        original = b"original-valuations"
        self.path.write_bytes(original)

        with patch(
            "local_file_persistence.load_valuation_csv",
            side_effect=InputValidationError("PRIVATE_CARD_CONTENT"),
        ):
            with self.assertRaises(LocalPersistenceError) as raised:
                save_valuation_frame_atomically(self.path, valid_valuations())

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])
        self.assertNotIn("PRIVATE_CARD_CONTENT", str(raised.exception))

    def test_serialization_failure_preserves_original_and_is_sanitized(self):
        original = b"original-valuations"
        self.path.write_bytes(original)

        with patch.object(
            pd.DataFrame,
            "to_csv",
            side_effect=OSError("PRIVATE_CARD_CONTENT"),
        ):
            with self.assertRaises(LocalPersistenceError) as raised:
                save_valuation_frame_atomically(self.path, valid_valuations())

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.temp_files(), [])
        self.assertNotIn("PRIVATE_CARD_CONTENT", str(raised.exception))


class AppAtomicPersistenceWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")

    def test_settings_save_uses_atomic_helper(self):
        self.assertIn("save_settings_atomically(SETTINGS_PATH, settings)", self.source)
        self.assertNotIn("SETTINGS_PATH.write_text", self.source)

    def test_card_values_save_uses_atomic_helper(self):
        self.assertIn(
            "save_valuation_frame_atomically(CARD_VALUES_PATH, validated_values)",
            self.source,
        )
        self.assertNotIn("validated_values.to_csv(CARD_VALUES_PATH", self.source)

    def test_app_is_inspected_without_importing_it(self):
        self.assertNotIn("app", globals())


if __name__ == "__main__":
    unittest.main()
