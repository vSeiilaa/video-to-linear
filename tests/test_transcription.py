from types import SimpleNamespace

from src.transcription import _flatten


def test_flatten_dict_segments():
    result = {"segments": [{"text": "hi", "start": 1.5, "end": 2.0}]}
    assert _flatten(result) == [{"text": "hi", "start_ms": 1500, "end_ms": 2000}]


def test_flatten_object_segments():
    result = SimpleNamespace(
        segments=[SimpleNamespace(text="yo", start=0.0, end=0.25)]
    )
    assert _flatten(result) == [{"text": "yo", "start_ms": 0, "end_ms": 250}]


def test_flatten_empty():
    assert _flatten({"segments": []}) == []
