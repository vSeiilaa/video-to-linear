from src.linear_client import (
    _SEV_TO_PRIORITY,
    _build_description,
    _ms_to_ts,
)


def test_ms_to_ts_formats_hms():
    assert _ms_to_ts(0) == "00:00:00"
    assert _ms_to_ts(65_000) == "00:01:05"
    assert _ms_to_ts(3_661_000) == "01:01:01"


def test_severity_priority_mapping():
    assert _SEV_TO_PRIORITY["critical"] == 1
    assert _SEV_TO_PRIORITY["high"] == 2
    assert _SEV_TO_PRIORITY["medium"] == 3
    assert _SEV_TO_PRIORITY["low"] == 4


def test_build_description_without_clip():
    assert _build_description("a bug happened", None, 0, 1000) == "a bug happened"


def test_build_description_appends_clip_link():
    md = _build_description("a bug", "https://cdn/clip.mp4", 0, 1000)
    assert "a bug" in md
    assert "(https://cdn/clip.mp4)" in md
    assert "🎬" in md
