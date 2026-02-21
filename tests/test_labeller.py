"""Tests for newscollector.utils.labeller."""

from __future__ import annotations

from newscollector.utils.labeller import label_item


class TestLabelItem:
    def test_single_label_financial(self):
        assert "financial" in label_item("stock market rally today")

    def test_single_label_politics(self):
        assert "politics" in label_item("President signs new bill")

    def test_single_label_sports(self):
        assert "sports" in label_item("NBA finals game tonight")

    def test_multiple_labels(self):
        labels = label_item("Election day stock market impact on investors")
        assert "financial" in labels
        assert "politics" in labels

    def test_no_match(self):
        assert label_item("Lorem ipsum dolor sit amet") == []

    def test_case_insensitive(self):
        assert "financial" in label_item("BITCOIN crash wipes billions")

    def test_description_contributes(self):
        labels = label_item("Breaking news", "The stock market fell sharply")
        assert "financial" in labels

    def test_empty_inputs(self):
        assert label_item("") == []
        assert label_item("", "") == []
        assert label_item("", None) == []

    def test_technology_label(self):
        assert "technology" in label_item("Apple announces new iPhone AI features")

    def test_health_label(self):
        assert "health" in label_item("New vaccine approved by FDA")

    def test_entertainment_label(self):
        assert "entertainment" in label_item("Oscar nominations revealed for best film")

    def test_game_label(self):
        assert "game" in label_item("Nintendo reveals new console for gamers")

    def test_science_label(self):
        assert "science" in label_item("NASA discovers new planet near solar system")
