import unittest

import pandas as pd

from recommendation_engine import is_unverified_scout_candidate
from scout_engine import enrich_listings
from search_relevance import (
    is_relevant_search_result,
    query_identity_issue,
)


EXACT_QUERY = "2018 Topps Chrome Shohei Ohtani #150 Rookie"


def candidate_row(**overrides) -> pd.Series:
    row = {
        "recommended_action": "PASS",
        "valuation_available": False,
        "listing_actionable": True,
        "listing_listing_class": "RAW_PARALLEL",
        "grading_candidate": True,
        "grading_signal_score": 65,
        "parsed_print_run": 99,
        "parsed_rookie": True,
        "parsed_autograph": False,
        "parsed_parallel": "Refractor",
        "parsed_card_number": "150",
        "seller_feedback_pct": 99.9,
        "title": "2018 Topps Chrome Shohei Ohtani #150 Rookie Refractor",
        "condition": "Ungraded",
        "query_identity_match": True,
    }
    row.update(overrides)
    return pd.Series(row)


class ScoutQueryIdentityTests(unittest.TestCase):
    def test_exact_query_accepts_matching_listing(self):
        title = "2018 Topps Chrome Shohei Ohtani Rookie Card #150"

        self.assertIsNone(query_identity_issue(title, EXACT_QUERY))
        self.assertTrue(is_relevant_search_result(title, EXACT_QUERY))

    def test_exact_query_rejects_observed_beta_false_positives(self):
        titles = (
            "2026 Topps Chrome Black Shohei Ohtani #1 Los Angeles Dodgers",
            "2022 Topps Pristine Shohei Ohtani Pristine Borders Refractor #PB-13",
            "2025 Topps Stadium Club Shohei Ohtani #58 Red Foil",
            "2020 Shohei Ohtani Topps Chrome 35th Anniversary 1985 Refractor",
            "2022 Shohei Ohtani Topps Chrome 1987 35th Anniversary Refractor",
        )

        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(is_relevant_search_result(title, EXACT_QUERY))

    def test_explicit_query_identity_conflicts_and_gaps_fail_closed(self):
        cases = (
            (
                "2020 Topps Chrome Shohei Ohtani #150 Rookie",
                EXACT_QUERY,
                "query_identity_conflict_year",
            ),
            (
                "2018 Bowman Chrome Shohei Ohtani #150 Rookie",
                EXACT_QUERY,
                "query_identity_conflict_manufacturer",
            ),
            (
                "2018 Topps Stadium Club Shohei Ohtani #150 Rookie",
                EXACT_QUERY,
                "query_identity_conflict_product",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #1 Rookie",
                EXACT_QUERY,
                "query_identity_conflict_card_number",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani Rookie",
                EXACT_QUERY,
                "query_identity_missing_card_number",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150",
                EXACT_QUERY,
                "query_identity_missing_rookie",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150 Rookie",
                f"{EXACT_QUERY} Refractor",
                "query_identity_missing_parallel",
            ),
            (
                "2018 Topps Chrome Shohei Ohtani #150 Rookie",
                f"{EXACT_QUERY} Autograph",
                "query_identity_missing_autograph",
            ),
        )

        for title, query, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(query_identity_issue(title, query), expected)
                self.assertFalse(is_relevant_search_result(title, query))

    def test_player_only_query_preserves_broad_discovery(self):
        title = "2026 Topps Chrome Black Shohei Ohtani #1"

        self.assertIsNone(query_identity_issue(title, "Shohei Ohtani"))
        self.assertTrue(is_relevant_search_result(title, "Shohei Ohtani"))

    def test_enrichment_records_query_identity_rejection_reason(self):
        listings = pd.DataFrame(
            [
                {
                    "title": "2026 Topps Chrome Black Shohei Ohtani #1",
                    "condition": "Ungraded",
                }
            ]
        )

        enriched = enrich_listings(listings, EXACT_QUERY)

        self.assertFalse(bool(enriched.iloc[0]["query_identity_match"]))
        self.assertEqual(
            enriched.iloc[0]["query_identity_issue"],
            "query_identity_conflict_year",
        )

    def test_scout_eligibility_rejects_query_identity_mismatch(self):
        row = candidate_row(
            query_identity_match=False,
            query_identity_issue="query_identity_conflict_year",
        )

        self.assertFalse(is_unverified_scout_candidate(row, 25))
        self.assertEqual(row["recommended_action"], "PASS")


if __name__ == "__main__":
    unittest.main()
