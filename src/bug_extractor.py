import json
from typing import Callable, List, Optional

from pydantic import BaseModel, TypeAdapter, ValidationError

from .llm import Provider, call_llm_json
from .prompts import BUG_FINDER_SYSTEM, BUG_REPORT_SYSTEM

_CHUNK_SIZE = 40
_CHUNK_OVERLAP = 8


class BugSegment(BaseModel):
    start_ms: int
    end_ms: int
    raw_text: str
    is_bug: bool
    reason: str


class Bug(BaseModel):
    title: str
    severity: str
    description: str
    steps_to_reproduce: Optional[List[str]] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    start_ms: int
    end_ms: int


BugSegmentList = TypeAdapter(List[BugSegment])


def _chunk(segments: list, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[list]:
    if len(segments) <= size:
        return [segments]
    chunks, i = [], 0
    while i < len(segments):
        chunks.append(segments[i : i + size])
        i += size - overlap
    return chunks


def _dedup(bugs: List[Bug], tolerance_ms: int = 3000) -> List[Bug]:
    seen: List[Bug] = []
    for bug in bugs:
        if not any(abs(bug.start_ms - s.start_ms) < tolerance_ms for s in seen):
            seen.append(bug)
    return seen


def find_bug_segments(
    full_transcript: List[dict],
    provider: Provider,
    model_id: str,
    log: Callable[[str], None] = print,
    finder_prompt: str = BUG_FINDER_SYSTEM,
    api_key: Optional[str] = None,
) -> List[BugSegment]:
    chunks = _chunk(full_transcript)
    all_segments: List[BugSegment] = []

    for i, chunk in enumerate(chunks):
        log(f"  Scanning chunk {i + 1}/{len(chunks)}…")
        lines = [f"[{t['start_ms']}-{t['end_ms']}] {t['text']}" for t in chunk]
        raw = call_llm_json(provider, model_id, finder_prompt, "\n".join(lines), api_key=api_key)
        data = json.loads(raw)
        for item in data.get("segments", []):
            try:
                all_segments.append(BugSegment.model_validate(item))
            except ValidationError:
                pass

    return all_segments


def build_bug_reports(
    bug_segments: List[BugSegment],
    provider: Provider,
    model_id: str,
    log: Callable[[str], None] = print,
    report_prompt: str = BUG_REPORT_SYSTEM,
    api_key: Optional[str] = None,
) -> List[Bug]:
    bugs: List[Bug] = []
    bug_segs = [s for s in bug_segments if s.is_bug]

    for i, seg in enumerate(bug_segs):
        log(f"  Building report {i + 1}/{len(bug_segs)}…")
        payload = json.dumps({
            "snippet": seg.raw_text,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
        })
        raw = call_llm_json(provider, model_id, report_prompt, payload, api_key=api_key)
        try:
            bugs.append(Bug.model_validate_json(raw))
        except ValidationError as e:
            log(f"  Validation error on segment {i + 1}: {e}")

    return _dedup(bugs)
