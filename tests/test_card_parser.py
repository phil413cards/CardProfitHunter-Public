from card_parser import parse_card_identity


def test_parses_structured_card_identity():
    card = parse_card_identity(
        "2024 Topps Chrome Shohei Ohtani Gold Refractor #17 12/50 Auto",
        "Shohei Ohtani",
    )
    assert card.player == "Shohei Ohtani"
    assert card.year == 2024
    assert card.manufacturer == "Topps"
    assert card.product == "Chrome"
    assert card.card_number == "17"
    assert card.parallel == "Gold Refractor"
    assert card.print_run == 50
    assert card.autograph
