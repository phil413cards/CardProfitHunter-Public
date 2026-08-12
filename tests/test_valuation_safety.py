from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import pandas as pd

from valuation_safety import (
    normalize_verification_status,
    valuation_freshness_label,
    valuation_provenance_flags,
)


def verified_row(**overrides):
    row = {
        "verification_status": "verified",
        "verified_at": "2026-08-01",
        "expires_at": "2026-09-01",
        "source_url": "https://example.com/sold-comps",
        "comp_count": 12,
        "notes": "Verified sold comparables",
    }
    row.update(overrides)
    return row


class ValuationSafetyTests(unittest.TestCase):
    AS_OF = date(2026, 8, 9)

    def test_current_verified_row_has_no_safety_flags(self):
        self.assertEqual(
            valuation_provenance_flags(verified_row(), as_of=self.AS_OF),
            (),
        )
        self.assertEqual(
            valuation_freshness_label(verified_row(), as_of=self.AS_OF),
            "Current",
        )

    def test_expired_row_is_non_actionable(self):
        row = verified_row(expires_at="2026-08-08")

        self.assertEqual(
            valuation_provenance_flags(row, as_of=self.AS_OF),
            ("expired_valuation",),
        )
        self.assertEqual(
            valuation_freshness_label(row, as_of=self.AS_OF),
            "Expired",
        )

    def test_missing_provenance_values_are_detected_without_crashing(self):
        for field in (
            "verification_status",
            "verified_at",
            "expires_at",
            "source_url",
            "comp_count",
        ):
            for missing in (None, "", float("nan"), pd.NA):
                with self.subTest(field=field, missing=repr(missing)):
                    row = verified_row(**{field: missing})
                    self.assertEqual(
                        valuation_provenance_flags(row, as_of=self.AS_OF),
                        ("missing_valuation_provenance",),
                    )

    def test_malformed_verified_provenance_is_detected(self):
        cases = (
            {"verified_at": "08/01/2026"},
            {"verified_at": "2026-08-32"},
            {"verified_at": "2026-08-10"},
            {"expires_at": "2026/09/01"},
            {"expires_at": "2026-07-31"},
            {"source_url": "http://example.com/comps"},
            {"source_url": "https://user:secret@example.com/comps"},
            {"comp_count": True},
            {"comp_count": 0},
            {"comp_count": 1.5},
            {"comp_count": "many"},
        )

        for override in cases:
            with self.subTest(override=override):
                self.assertEqual(
                    valuation_provenance_flags(
                        verified_row(**override),
                        as_of=self.AS_OF,
                    ),
                    ("invalid_valuation_provenance",),
                )

    def test_nonverified_statuses_are_non_actionable(self):
        for status in ("demonstration", "unverified", "non-actionable"):
            with self.subTest(status=status):
                row = verified_row(verification_status=status)
                self.assertEqual(
                    valuation_provenance_flags(row, as_of=self.AS_OF),
                    ("unverified_valuation_status",),
                )
                self.assertEqual(
                    valuation_freshness_label(row, as_of=self.AS_OF),
                    "Non-actionable",
                )

    def test_example_notes_remain_non_actionable_even_with_verified_status(self):
        row = verified_row(notes="Example only - replace with verified comps")

        self.assertEqual(
            valuation_freshness_label(row, as_of=self.AS_OF),
            "Non-actionable",
        )

    def test_status_normalization_is_deterministic(self):
        self.assertEqual(
            normalize_verification_status("  Non-Actionable "),
            "non_actionable",
        )

    def test_timezone_aware_datetime_is_supported_and_naive_is_rejected(self):
        aware = datetime(2026, 8, 9, 8, tzinfo=timezone.utc)
        self.assertEqual(valuation_provenance_flags(verified_row(), as_of=aware), ())
        with self.assertRaisesRegex(ValueError, "timezone"):
            valuation_provenance_flags(
                verified_row(),
                as_of=datetime(2026, 8, 9, 8),
            )


if __name__ == "__main__":
    unittest.main()
