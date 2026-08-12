import unittest

from card_parser import parse_card_identity


class CardParserTests(unittest.TestCase):
    def test_parses_structured_card_identity(self):
        card = parse_card_identity(
            "2024 Topps Chrome Shohei Ohtani Gold Refractor #17 12/50 Auto",
            "Shohei Ohtani",
        )

        self.assertEqual(card.player, "Shohei Ohtani")
        self.assertEqual(card.year, 2024)
        self.assertEqual(card.manufacturer, "Topps")
        self.assertEqual(card.product, "Chrome")
        self.assertEqual(card.card_number, "17")
        self.assertEqual(card.parallel, "Gold Refractor")
        self.assertEqual(card.print_run, 50)
        self.assertTrue(card.autograph)


if __name__ == "__main__":
    unittest.main()
