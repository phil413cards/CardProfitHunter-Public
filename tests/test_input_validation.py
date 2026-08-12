import json
import unittest
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from input_validation import (
    InputValidationError,
    MAX_CSV_BYTES,
    MAX_CSV_COLUMNS,
    MAX_LISTING_ROWS,
    MAX_VALUATION_ROWS,
    load_listing_csv,
    load_settings_file,
    load_valuation_csv,
    validate_listing_frame,
    validate_category_ids,
    validate_search_inputs,
    validate_search_query,
    validate_settings,
    validate_valuation_frame,
)


def valid_settings():
    return {
        "ebay_fee_pct": 0.1325,
        "purchase_tax_pct": 0.10,
        "promoted_listing_fee_pct": 0.05,
        "return_defect_allowance_pct": 0.05,
        "grading_loss_risk_pct": 0.01,
        "raw_flip_shipping_allowance": 6.0,
        "psa_grading_fee": 25.0,
        "psa_shipping_insurance_allowance": 12.0,
        "psa_selling_shipping_allowance": 8.0,
        "minimum_raw_flip_profit": 25.0,
        "minimum_raw_flip_roi_pct": 20.0,
        "minimum_psa_expected_profit": 50.0,
        "minimum_psa_expected_roi_pct": 25.0,
        "offer_safety_margin_pct": 0.85,
        "raw_only": True,
        "max_offer_market_pct": 0.9,
    }


def valid_valuations():
    return pd.DataFrame([{
        "keyword": "Test Player Topps Chrome #10 Refractor",
        "raw_market_value": 100.0,
        "psa9_value": 150.0,
        "psa10_value": 300.0,
        "gem_rate_estimate": 0.4,
        "psa9_rate_estimate": 0.4,
        "verification_status": "verified",
        "verified_at": (date.today() - timedelta(days=1)).isoformat(),
        "expires_at": (date.today() + timedelta(days=30)).isoformat(),
        "source_url": "https://example.com/verified-comps",
        "comp_count": 10,
        "notes": "Verified comps",
    }])


def valid_listings():
    return pd.DataFrame([{
        "title": "Test Player Topps Chrome #10 Refractor Raw",
        "price": 50.0,
        "shipping": 0.0,
        "currency": "usd",
        "buying_options": "FIXED_PRICE",
        "condition": "Used",
    }])


class SettingsValidationTests(unittest.TestCase):
    def test_valid_settings_are_normalized_and_unknown_keys_are_preserved(self):
        settings = valid_settings()
        settings["future_setting"] = "preserve"

        result = validate_settings(settings)

        self.assertEqual(result["ebay_fee_pct"], 0.1325)
        self.assertEqual(result["future_setting"], "preserve")
        self.assertIs(result["raw_only"], True)

    def test_invalid_settings_are_rejected(self):
        cases = [
            ("not an object", [], None),
            ("missing required", valid_settings(), "psa_grading_fee"),
            ("boolean number", valid_settings(), "ebay_fee_pct"),
            ("not numeric", valid_settings(), "minimum_raw_flip_profit"),
            ("not finite", valid_settings(), "minimum_psa_expected_roi_pct"),
            ("negative cost", valid_settings(), "raw_flip_shipping_allowance"),
            ("fee above one", valid_settings(), "ebay_fee_pct"),
            ("purchase tax above one", valid_settings(), "purchase_tax_pct"),
            (
                "promoted fee below zero",
                valid_settings(),
                "promoted_listing_fee_pct",
            ),
            (
                "return allowance above one",
                valid_settings(),
                "return_defect_allowance_pct",
            ),
            (
                "grading risk above one",
                valid_settings(),
                "grading_loss_risk_pct",
            ),
            ("margin above one", valid_settings(), "offer_safety_margin_pct"),
            ("raw only not bool", valid_settings(), "raw_only"),
        ]
        replacements = {
            "psa_grading_fee": None,
            "ebay_fee_pct": True,
            "minimum_raw_flip_profit": "abc",
            "minimum_psa_expected_roi_pct": float("nan"),
            "raw_flip_shipping_allowance": -1,
            "purchase_tax_pct": 1.1,
            "promoted_listing_fee_pct": -0.1,
            "return_defect_allowance_pct": 1.1,
            "grading_loss_risk_pct": 1.1,
            "offer_safety_margin_pct": 1.1,
            "raw_only": "true",
        }

        for name, source, field in cases:
            with self.subTest(name=name):
                if name == "missing required":
                    source.pop(field)
                elif name == "fee above one":
                    source[field] = 1.1
                elif field is not None:
                    source[field] = replacements[field]
                with self.assertRaises(InputValidationError):
                    validate_settings(source)

    def test_combined_selling_cost_rates_cannot_exceed_sale_value(self):
        settings = valid_settings()
        settings.update({
            "ebay_fee_pct": 0.50,
            "promoted_listing_fee_pct": 0.30,
            "return_defect_allowance_pct": 0.30,
        })

        with self.assertRaisesRegex(InputValidationError, "Combined marketplace"):
            validate_settings(settings)

    def test_bundled_settings_enable_all_approved_cost_categories(self):
        settings = load_settings_file(
            Path(__file__).resolve().parents[1] / "config" / "settings.json"
        )

        for key in (
            "purchase_tax_pct",
            "promoted_listing_fee_pct",
            "return_defect_allowance_pct",
            "grading_loss_risk_pct",
        ):
            with self.subTest(key=key):
                self.assertGreater(settings[key], 0)

    def test_settings_file_errors_are_sanitized(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text('{"private": "unterminated"', encoding="utf-8")

            with self.assertRaisesRegex(
                InputValidationError,
                "Settings file could not be read as valid JSON",
            ) as raised:
                load_settings_file(path)

        self.assertNotIn("private", str(raised.exception))

    def test_valid_settings_file_loads(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(json.dumps(valid_settings()), encoding="utf-8")
            result = load_settings_file(path)

        self.assertEqual(result["max_offer_market_pct"], 0.9)


class ValuationValidationTests(unittest.TestCase):
    def test_valid_and_demonstration_valuations_are_allowed(self):
        frame = valid_valuations()
        frame.loc[0, "notes"] = "Example only - non-actionable"
        frame.loc[0, "verification_status"] = "demonstration"
        for column in ("verified_at", "expires_at", "source_url", "comp_count"):
            frame[column] = frame[column].astype(object)
            frame.loc[0, column] = None

        result = validate_valuation_frame(frame)

        self.assertEqual(result.loc[0, "keyword"], frame.loc[0, "keyword"])
        self.assertEqual(result.loc[0, "verification_status"], "demonstration")
        self.assertIn("Example only", result.loc[0, "notes"])

    def test_expired_verified_valuation_can_load_for_review(self):
        frame = valid_valuations()
        frame.loc[0, "expires_at"] = (date.today() - timedelta(days=1)).isoformat()
        frame.loc[0, "verified_at"] = (date.today() - timedelta(days=30)).isoformat()

        result = validate_valuation_frame(frame)

        self.assertEqual(result.loc[0, "verification_status"], "verified")

    def test_verified_provenance_must_be_complete_and_well_formed(self):
        cases = (
            ("missing verified date", "verified_at", None, "missing required provenance"),
            ("missing expiry", "expires_at", "", "missing required provenance"),
            ("missing source", "source_url", None, "missing required provenance"),
            ("missing comp count", "comp_count", None, "missing required provenance"),
            ("bad verified date", "verified_at", "08/09/2026", "malformed"),
            ("bad expiry", "expires_at", "tomorrow", "malformed"),
            ("http source", "source_url", "http://example.com/private", "malformed"),
            ("fractional comp count", "comp_count", 1.5, "malformed"),
            ("zero comp count", "comp_count", 0, "malformed"),
        )

        for name, field, value, expected_message in cases:
            with self.subTest(name=name):
                frame = valid_valuations()
                frame[field] = frame[field].astype(object)
                frame.loc[0, field] = value
                with self.assertRaisesRegex(
                    InputValidationError,
                    expected_message,
                ):
                    validate_valuation_frame(frame)

    def test_unsupported_verification_status_is_rejected_without_echoing_it(self):
        frame = valid_valuations()
        frame.loc[0, "verification_status"] = "PRIVATE_UNSAFE_STATUS"

        with self.assertRaisesRegex(InputValidationError, "unsupported status") as raised:
            validate_valuation_frame(frame)

        self.assertNotIn("PRIVATE_UNSAFE_STATUS", str(raised.exception))

    def test_invalid_valuation_rows_are_rejected(self):
        cases = [
            ("blank keyword", "keyword", " "),
            ("blank notes", "notes", None),
            ("zero raw value", "raw_market_value", 0),
            ("negative psa9", "psa9_value", -1),
            ("malformed psa10", "psa10_value", "abc"),
            ("boolean psa10", "psa10_value", True),
            ("infinite raw value", "raw_market_value", float("inf")),
            ("negative gem rate", "gem_rate_estimate", -0.1),
            ("gem rate above one", "gem_rate_estimate", 1.1),
            ("psa9 rate above one", "psa9_rate_estimate", 1.1),
        ]

        for name, column, value in cases:
            with self.subTest(name=name):
                frame = valid_valuations()
                frame[column] = frame[column].astype(object)
                frame.loc[0, column] = value
                with self.assertRaises(InputValidationError):
                    validate_valuation_frame(frame)

    def test_probability_total_above_one_is_rejected(self):
        frame = valid_valuations()
        frame.loc[0, "gem_rate_estimate"] = 0.7
        frame.loc[0, "psa9_rate_estimate"] = 0.4

        with self.assertRaisesRegex(InputValidationError, "must total 1 or less"):
            validate_valuation_frame(frame)

    def test_duplicate_identities_are_case_insensitive(self):
        frame = valid_valuations()
        duplicate = frame.copy()
        duplicate.loc[0, "keyword"] = "  TEST  PLAYER TOPPS CHROME #10 REFRACTOR  "
        frame = pd.concat([frame, duplicate], ignore_index=True)

        with self.assertRaisesRegex(InputValidationError, "duplicate card identities"):
            validate_valuation_frame(frame)

    def test_missing_columns_and_empty_files_are_rejected(self):
        missing = valid_valuations().drop(columns=["verification_status"])
        empty = valid_valuations().iloc[0:0]

        with self.assertRaisesRegex(InputValidationError, "missing required columns"):
            validate_valuation_frame(missing)
        with self.assertRaisesRegex(InputValidationError, "at least one data row"):
            validate_valuation_frame(empty)

    def test_valuation_row_and_column_limits_are_enforced(self):
        too_many_rows = pd.concat(
            [valid_valuations()] * (MAX_VALUATION_ROWS + 1),
            ignore_index=True,
        )
        too_many_columns = valid_valuations()
        for index in range(MAX_CSV_COLUMNS):
            too_many_columns[f"extra_{index}"] = index

        with self.assertRaisesRegex(InputValidationError, "no more than 1000"):
            validate_valuation_frame(too_many_rows)
        with self.assertRaisesRegex(InputValidationError, "no more than 64"):
            validate_valuation_frame(too_many_columns)

    def test_malformed_valuation_csv_error_is_sanitized(self):
        source = StringIO('keyword,notes\n"private malformed value')

        with self.assertRaisesRegex(InputValidationError, "Valuation CSV could not be read") as raised:
            load_valuation_csv(source)

        self.assertNotIn("private malformed value", str(raised.exception))


class ListingValidationTests(unittest.TestCase):
    def test_valid_listing_allows_free_shipping_and_normalizes_currency(self):
        result = validate_listing_frame(valid_listings())

        self.assertEqual(result.loc[0, "shipping"], 0.0)
        self.assertEqual(result.loc[0, "currency"], "USD")

    def test_unsupported_currency_remains_valid_input(self):
        frame = valid_listings()
        frame.loc[0, "currency"] = "eur"

        result = validate_listing_frame(frame)

        self.assertEqual(result.loc[0, "currency"], "EUR")

    def test_invalid_listing_rows_are_rejected(self):
        cases = [
            ("blank title", "title", ""),
            ("zero price", "price", 0),
            ("malformed price", "price", "abc"),
            ("boolean price", "price", True),
            ("nonfinite price", "price", float("nan")),
            ("negative shipping", "shipping", -1),
            ("nonfinite shipping", "shipping", float("inf")),
            ("blank currency", "currency", None),
            ("blank option", "buying_options", " "),
            ("blank condition", "condition", None),
        ]

        for name, column, value in cases:
            with self.subTest(name=name):
                frame = valid_listings()
                frame[column] = frame[column].astype(object)
                frame.loc[0, column] = value
                with self.assertRaises(InputValidationError):
                    validate_listing_frame(frame)

    def test_missing_columns_and_empty_files_are_rejected(self):
        missing = valid_listings().drop(columns=["shipping"])
        empty = valid_listings().iloc[0:0]

        with self.assertRaisesRegex(InputValidationError, "missing required columns"):
            validate_listing_frame(missing)
        with self.assertRaisesRegex(InputValidationError, "at least one data row"):
            validate_listing_frame(empty)

    def test_valid_listing_csv_loads(self):
        source = StringIO(
            "title,price,shipping,currency,buying_options,condition\n"
            "Test Card,10,0,usd,FIXED_PRICE,Used\n"
        )

        result = load_listing_csv(source)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "currency"], "USD")

    def test_listing_row_limit_is_enforced_before_analysis(self):
        too_many_rows = pd.concat(
            [valid_listings()] * (MAX_LISTING_ROWS + 1),
            ignore_index=True,
        )

        with self.assertRaisesRegex(InputValidationError, "no more than 1000"):
            validate_listing_frame(too_many_rows)

    def test_csv_loader_stops_after_the_listing_row_limit(self):
        source = StringIO(
            "title,price,shipping,currency,buying_options,condition\n"
            + "Test Card,10,0,USD,FIXED_PRICE,Used\n" * (MAX_LISTING_ROWS + 1)
        )

        with self.assertRaisesRegex(InputValidationError, "no more than 1000"):
            load_listing_csv(source)

    def test_oversized_csv_is_rejected_without_reading_or_echoing_content(self):
        class OversizedUpload:
            size = MAX_CSV_BYTES + 1

            def read(self, *args, **kwargs):
                raise AssertionError("private submitted content")

        with self.assertRaisesRegex(InputValidationError, "5 MB or smaller") as raised:
            load_listing_csv(OversizedUpload())

        self.assertNotIn("private submitted content", str(raised.exception))


class SearchInputValidationTests(unittest.TestCase):
    def test_valid_query_is_trimmed(self):
        self.assertEqual(validate_search_query("  rookie card  "), "rookie card")

    def test_invalid_queries_are_rejected(self):
        for name, query in (
            ("empty", ""),
            ("whitespace", "   \t"),
            ("missing", None),
            ("integer", 123),
            ("list", ["rookie"]),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(InputValidationError, "nonempty text"):
                    validate_search_query(query)

    def test_optional_and_valid_category_ids_are_normalized(self):
        cases = (
            ("empty", "", ""),
            ("whitespace", "   ", ""),
            ("missing", None, ""),
            ("one", "183454", "183454"),
            ("multiple", "183454,261328", "183454,261328"),
            ("normalized whitespace", " 183454,  261328 ", "183454,261328"),
        )
        for name, source, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(validate_category_ids(source), expected)

    def test_invalid_category_ids_are_rejected(self):
        cases = (
            ("letters", "abc"),
            ("mixed letters", "183454,abc"),
            ("positive sign", "+183454"),
            ("negative sign", "-183454"),
            ("decimal", "183454.0"),
            ("semicolon", "183454;261328"),
            ("leading empty token", ",183454"),
            ("middle empty token", "183454,,261328"),
            ("trailing empty token", "183454,"),
            ("list", ["183454"]),
            ("dict", {"id": "183454"}),
            ("integer", 183454),
        )
        for name, category_ids in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    InputValidationError,
                    "comma-separated numeric identifiers",
                ):
                    validate_category_ids(category_ids)

    def test_validation_errors_do_not_echo_submitted_content(self):
        unsafe_query = "private-query-value"
        unsafe_category = "private-category-value"

        with self.assertRaises(InputValidationError) as query_error:
            validate_search_inputs([unsafe_query], unsafe_category)
        with self.assertRaises(InputValidationError) as category_error:
            validate_search_inputs("valid query", unsafe_category)

        self.assertNotIn(unsafe_query, str(query_error.exception))
        self.assertNotIn(unsafe_category, str(query_error.exception))
        self.assertNotIn(unsafe_query, str(category_error.exception))
        self.assertNotIn(unsafe_category, str(category_error.exception))


if __name__ == "__main__":
    unittest.main()
