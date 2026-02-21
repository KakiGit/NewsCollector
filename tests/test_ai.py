"""Tests for newscollector.utils.ai pure functions."""

from __future__ import annotations

from newscollector.utils.ai import (
    _build_page_summary_prompt,
    _build_prompt,
    _clamp_score,
    _extract_json_text,
    _first_choice_content,
    _format_items_for_verdict,
    _normalize_extracted_items,
    _normalize_labels,
    _parse_verdict_response,
    is_ai_configured,
)


class TestExtractJsonText:
    def test_plain_json(self):
        assert _extract_json_text('{"a": 1}') == '{"a": 1}'

    def test_fenced_json(self):
        raw = '```json\n{"a": 1}\n```'
        assert _extract_json_text(raw) == '{"a": 1}'

    def test_fenced_no_lang(self):
        raw = '```\n{"a": 1}\n```'
        assert _extract_json_text(raw) == '{"a": 1}'

    def test_no_fences(self):
        assert _extract_json_text("hello world") == "hello world"

    def test_empty_string(self):
        assert _extract_json_text("") == ""


class TestFirstChoiceContent:
    def test_valid_choices(self):
        data = {"choices": [{"message": {"content": "hello"}}]}
        assert _first_choice_content(data) == "hello"

    def test_empty_choices(self):
        assert _first_choice_content({"choices": []}) == ""

    def test_missing_choices(self):
        assert _first_choice_content({}) == ""

    def test_none_content(self):
        data = {"choices": [{"message": {"content": None}}]}
        assert _first_choice_content(data) == ""


class TestIsAiConfigured:
    def test_all_set(self, ai_config):
        assert is_ai_configured(ai_config) is True

    def test_missing_url(self):
        cfg = {"ai": {"ai_model": "m", "ai_api_key": "k"}}
        assert is_ai_configured(cfg) is False

    def test_missing_model(self):
        cfg = {"ai": {"ai_base_url": "u", "ai_api_key": "k"}}
        assert is_ai_configured(cfg) is False

    def test_missing_key(self):
        cfg = {"ai": {"ai_base_url": "u", "ai_model": "m"}}
        assert is_ai_configured(cfg) is False

    def test_empty_config(self, empty_config):
        assert is_ai_configured(empty_config) is False

    def test_no_ai_section(self):
        assert is_ai_configured({"twitter": {}}) is False


class TestBuildPrompt:
    def test_contains_title(self):
        prompt = _build_prompt("Big News", None)
        assert "Big News" in prompt

    def test_contains_description(self):
        prompt = _build_prompt("T", "Details here")
        assert "Details here" in prompt

    def test_language_instruction(self):
        prompt = _build_prompt("T", None, response_language="中文")
        assert "中文" in prompt

    def test_no_language_instruction_when_none(self):
        prompt = _build_prompt("T", None, response_language=None)
        assert "Respond in" not in prompt


class TestBuildPageSummaryPrompt:
    def test_contains_page_text(self):
        prompt = _build_page_summary_prompt("Title", "Full page content here")
        assert "Full page content here" in prompt
        assert "Title" in prompt

    def test_language_instruction(self):
        prompt = _build_page_summary_prompt("T", "text", response_language="日本語")
        assert "日本語" in prompt


class TestNormalizeLabels:
    def test_valid_list(self):
        assert _normalize_labels(["a", "b", "c"]) == ["a", "b", "c"]

    def test_caps_at_three(self):
        assert len(_normalize_labels(["a", "b", "c", "d"])) == 3

    def test_strips_whitespace(self):
        assert _normalize_labels(["  a  ", "b"]) == ["a", "b"]

    def test_filters_empty(self):
        assert _normalize_labels(["a", "", "  ", "b"]) == ["a", "b"]

    def test_non_list_returns_empty(self):
        assert _normalize_labels("not a list") == []
        assert _normalize_labels(None) == []
        assert _normalize_labels(42) == []


class TestNormalizeExtractedItems:
    def test_basic_extraction(self):
        raw = [{"title": "Hello", "url": "https://a.com"}]
        result = _normalize_extracted_items(raw, max_items=10)
        assert len(result) == 1
        assert result[0]["title"] == "Hello"
        assert result[0]["url"] == "https://a.com"

    def test_dedup_by_title(self):
        raw = [{"title": "Same"}, {"title": "Same"}]
        result = _normalize_extracted_items(raw, max_items=10)
        assert len(result) == 1

    def test_invalid_url_set_to_none(self):
        raw = [{"title": "T", "url": "not-a-url"}]
        result = _normalize_extracted_items(raw, max_items=10)
        assert result[0]["url"] is None

    def test_caps_at_max_items(self):
        raw = [{"title": f"Item {i}"} for i in range(20)]
        result = _normalize_extracted_items(raw, max_items=5)
        assert len(result) == 5

    def test_skips_empty_title(self):
        raw = [{"title": ""}, {"title": "Valid"}]
        result = _normalize_extracted_items(raw, max_items=10)
        assert len(result) == 1

    def test_non_list_returns_empty(self):
        assert _normalize_extracted_items("bad", max_items=10) == []


class TestClampScore:
    def test_valid_int(self):
        assert _clamp_score(50) == 50

    def test_zero(self):
        assert _clamp_score(0) == 0

    def test_hundred(self):
        assert _clamp_score(100) == 100

    def test_clamps_high(self):
        assert _clamp_score(150) == 100

    def test_clamps_low(self):
        assert _clamp_score(-10) == 0

    def test_string_number(self):
        assert _clamp_score("75") == 75

    def test_invalid_returns_none(self):
        assert _clamp_score("abc") is None
        assert _clamp_score(None) is None


class TestParseVerdictResponse:
    def test_valid_response(self):
        content = '{"summary":"Ok.","global_political_score":60,"global_economic_score":70,"domestic_political_score":50,"domestic_economic_score":55}'
        result = _parse_verdict_response(content)
        assert result is not None
        assert result["summary"] == "Ok."
        assert result["global_political_score"] == 60

    def test_fenced_response(self):
        content = '```json\n{"summary":"Ok.","global_political_score":60,"global_economic_score":70,"domestic_political_score":50,"domestic_economic_score":55}\n```'
        result = _parse_verdict_response(content)
        assert result is not None

    def test_missing_field_returns_none(self):
        content = '{"summary":"Ok.","global_political_score":60}'
        assert _parse_verdict_response(content) is None

    def test_invalid_json_returns_none(self):
        assert _parse_verdict_response("not json") is None

    def test_empty_returns_none(self):
        assert _parse_verdict_response("") is None


class TestFormatItemsForVerdict:
    def test_basic_formatting(self):
        items = [
            {
                "title": "Item A",
                "summary": "Summary A",
                "source": "S",
                "platform": "P",
                "region": "R",
            },
        ]
        text = _format_items_for_verdict(items)
        assert "1. Item A" in text
        assert "Summary A" in text

    def test_empty_items(self):
        assert _format_items_for_verdict([]) == "(no items)"

    def test_custom_start_idx(self):
        items = [{"title": "X"}]
        text = _format_items_for_verdict(items, start_idx=5)
        assert "5. X" in text
