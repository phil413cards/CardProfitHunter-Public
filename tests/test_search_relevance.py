import unittest

from search_relevance import (
    excluded_listing_reason,
    filter_search_results,
    is_relevant_search_result,
    normalize_text,
    score_search_result,
)


def item(title: str) -> dict:
    return {
        "itemId": title,
        "title": title,
    }


class SearchRelevanceTests(unittest.TestCase):
    def test_normalize_text_handles_case_punctuation_and_accents(self):
        self.assertEqual(
            normalize_text("Ronald Acuña Jr. — PSA 10"),
            "ronald acuna jr psa 10",
        )

    def test_exact_player_name_is_relevant(self):
        self.assertTrue(is_relevant_search_result(
            "2024 Topps Shohei Ohtani Dodgers Chrome Card",
            "Shohei Ohtani",
        ))

    def test_missing_first_name_is_rejected_for_player_search(self):
        self.assertFalse(is_relevant_search_result(
            "2024 Topps Ohtani Dodgers Chrome Card",
            "Shohei Ohtani",
        ))

    def test_missing_last_name_is_rejected_for_player_search(self):
        self.assertFalse(is_relevant_search_result(
            "2024 Topps Shohei Dodgers Chrome Card",
            "Shohei Ohtani",
        ))

    def test_unrelated_player_is_rejected(self):
        self.assertFalse(is_relevant_search_result(
            "2024 Topps Aaron Judge Chrome Card",
            "Shohei Ohtani",
        ))

    def test_pick_your_card_listing_is_rejected(self):
        self.assertEqual(
            excluded_listing_reason(
                "2024 Topps Chrome Pick Your Card Shohei Ohtani",
                "Shohei Ohtani",
            ),
            "pick your card",
        )

    def test_team_lot_is_rejected(self):
        self.assertFalse(is_relevant_search_result(
            "Los Angeles Dodgers Team Lot Shohei Ohtani",
            "Shohei Ohtani",
        ))

    def test_reprint_is_rejected(self):
        self.assertFalse(is_relevant_search_result(
            "Shohei Ohtani Rookie Card Reprint",
            "Shohei Ohtani",
        ))

    def test_user_can_explicitly_search_for_a_lot(self):
        self.assertTrue(is_relevant_search_result(
            "Shohei Ohtani Player Lot 10 Cards",
            "Shohei Ohtani player lot",
        ))

    def test_long_card_query_can_score_as_relevant(self):
        score = score_search_result(
            "2018 Topps Update Ronald Acuna Jr US250 Rookie PSA 10",
            "2018 Topps Update Ronald Acuna US250",
        )

        self.assertGreaterEqual(score, 60)

    def test_filter_search_results_removes_irrelevant_items(self):
        results = filter_search_results(
            [
                item("2024 Topps Shohei Ohtani Chrome"),
                item("2024 Topps Aaron Judge Chrome"),
                item("Shohei Ohtani Pick Your Card"),
            ],
            "Shohei Ohtani",
        )

        self.assertEqual(
            [result["title"] for result in results],
            ["2024 Topps Shohei Ohtani Chrome"],
        )

    def test_empty_query_rejects_results(self):
        self.assertEqual(
            filter_search_results([item("Shohei Ohtani")], ""),
            [],
        )


if __name__ == "__main__":
    unittest.main()
