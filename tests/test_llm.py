from src.llm import _strip_markdown_json


def test_strip_plain_json_unchanged():
    assert _strip_markdown_json('{"a": 1}') == '{"a": 1}'


def test_strip_fenced_json_with_lang():
    text = '```json\n{"a": 1}\n```'
    assert _strip_markdown_json(text) == '{"a": 1}'


def test_strip_fenced_json_without_lang():
    text = '```\n{"a": 1}\n```'
    assert _strip_markdown_json(text) == '{"a": 1}'


def test_strip_trims_surrounding_whitespace():
    assert _strip_markdown_json('   {"a": 1}   ') == '{"a": 1}'


def test_strip_extracts_first_fenced_block():
    text = 'preamble ```json\n{"a": 1}\n``` trailing'
    assert _strip_markdown_json(text) == '{"a": 1}'
