import json

from src import bug_extractor
from src.bug_extractor import (
    Bug,
    BugSegment,
    _chunk,
    _dedup,
    build_bug_reports,
    find_bug_segments,
)


def _seg(start_ms, is_bug=True, text="x"):
    return BugSegment(
        start_ms=start_ms, end_ms=start_ms + 500,
        raw_text=text, is_bug=is_bug, reason="r",
    )


# ── _chunk ──────────────────────────────────────────────────────────────────

def test_chunk_short_input_single_chunk():
    items = list(range(10))
    assert _chunk(items, size=40, overlap=8) == [items]


def test_chunk_overlaps_and_covers_all():
    items = list(range(100))
    chunks = _chunk(items, size=40, overlap=8)
    # advances by size-overlap = 32 each step
    assert chunks[0] == items[0:40]
    assert chunks[1][0] == 32  # overlap of 8 with previous chunk's tail
    # every original item appears in at least one chunk
    covered = {x for c in chunks for x in c}
    assert covered == set(items)


# ── _dedup ──────────────────────────────────────────────────────────────────

def test_dedup_drops_near_duplicates():
    segs = [_seg(0), _seg(1000), _seg(10000)]  # 0 and 1000 within 3s tolerance
    kept = _dedup(segs, tolerance_ms=3000)
    assert [s.start_ms for s in kept] == [0, 10000]


def test_dedup_keeps_distinct():
    segs = [_seg(0), _seg(5000), _seg(10000)]
    assert len(_dedup(segs, tolerance_ms=3000)) == 3


def test_dedup_works_on_bug_objects():
    bugs = [
        Bug(title="a", severity="low", description="d", start_ms=0, end_ms=1),
        Bug(title="b", severity="low", description="d", start_ms=500, end_ms=1),
    ]
    assert len(_dedup(bugs, tolerance_ms=3000)) == 1


# ── find_bug_segments: filters non-bugs and dedups before report building ─────

def test_find_bug_segments_filters_and_dedups(monkeypatch):
    payload = {
        "segments": [
            _seg(0).model_dump(),
            _seg(1000).model_dump(),         # dup of the first (within 3s)
            _seg(20000, is_bug=False).model_dump(),  # not a bug
            _seg(60000).model_dump(),
        ]
    }
    monkeypatch.setattr(bug_extractor, "call_llm_json", lambda *a, **k: json.dumps(payload))
    out = find_bug_segments([{"start_ms": 0, "end_ms": 1, "text": "t"}], "openai", "m")
    assert [s.start_ms for s in out] == [0, 60000]
    assert all(s.is_bug for s in out)


# ── build_bug_reports: parallel, preserves order, skips invalid ───────────────

def test_build_bug_reports_preserves_order(monkeypatch):
    def fake_llm(provider, model_id, system, user, api_key=None):
        data = json.loads(user)
        return json.dumps({
            "title": f"bug@{data['start_ms']}",
            "severity": "medium",
            "description": "d",
            "start_ms": data["start_ms"],
            "end_ms": data["end_ms"],
        })

    monkeypatch.setattr(bug_extractor, "call_llm_json", fake_llm)
    segs = [_seg(0), _seg(5000), _seg(10000)]
    bugs = build_bug_reports(segs, "openai", "m")
    assert [b.start_ms for b in bugs] == [0, 5000, 10000]


def test_build_bug_reports_skips_invalid_json(monkeypatch):
    def fake_llm(provider, model_id, system, user, api_key=None):
        data = json.loads(user)
        if data["start_ms"] == 0:
            return "{}"  # missing required fields -> ValidationError, skipped
        return json.dumps({
            "title": "ok", "severity": "low", "description": "d",
            "start_ms": data["start_ms"], "end_ms": data["end_ms"],
        })

    monkeypatch.setattr(bug_extractor, "call_llm_json", fake_llm)
    bugs = build_bug_reports([_seg(0), _seg(5000)], "openai", "m")
    # the start_ms=0 segment failed validation -> only the other Bug returned
    assert [b.start_ms for b in bugs] == [5000]
