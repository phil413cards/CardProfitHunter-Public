from listing_classifier import (
    BOX_BREAK, GRADED_CARD, PICK_YOUR_CARD, RAW_AUTOGRAPH, RAW_PARALLEL,
    classify_listing,
)


def test_classifies_parallel_as_actionable():
    result = classify_listing("2024 Topps Chrome Shohei Ohtani Gold Refractor /50")
    assert result.listing_class == RAW_PARALLEL
    assert result.actionable


def test_rejects_pick_your_card():
    result = classify_listing("2024 Topps Chrome Pick Your Card Shohei Ohtani")
    assert result.listing_class == PICK_YOUR_CARD
    assert not result.actionable


def test_rejects_break():
    assert classify_listing("Shohei Ohtani Case Break").listing_class == BOX_BREAK


def test_recognizes_graded():
    assert classify_listing("Shohei Ohtani PSA 10").listing_class == GRADED_CARD


def test_recognizes_raw_autograph():
    assert classify_listing("Shohei Ohtani On Card Auto").listing_class == RAW_AUTOGRAPH
