from pathlib import Path
from typing import List, Optional

from openai import OpenAI

from . import cache
from .config import OPENAI_API_KEY, OPENAI_TRANSCRIPTION_MODEL

# OpenAI's transcription endpoint rejects files larger than 25 MB.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


def transcribe_audio(audio_path: Path, api_key: Optional[str] = None) -> List[dict]:
    """Return a list of {text, start_ms, end_ms} segments, using disk cache when available."""
    cached = cache.load(audio_path)
    if cached is not None:
        return cached

    size = audio_path.stat().st_size
    if size > _MAX_AUDIO_BYTES:
        raise RuntimeError(
            f"Extracted audio is {size / 1024 / 1024:.0f} MB, over OpenAI's 25 MB "
            f"transcription limit. The video is too long to transcribe in one pass — "
            f"split it into shorter segments and run them separately."
        )

    client = OpenAI(api_key=api_key or OPENAI_API_KEY)
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model=OPENAI_TRANSCRIPTION_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )

    segments = _flatten(resp)
    cache.save(audio_path, segments)
    return segments


def _flatten(result) -> List[dict]:
    # result is a Transcription object; segments are accessible as an attribute or via dict
    segments = getattr(result, "segments", None) or result.get("segments", [])
    return [
        {
            "text": seg["text"] if isinstance(seg, dict) else seg.text,
            "start_ms": int((seg["start"] if isinstance(seg, dict) else seg.start) * 1000),
            "end_ms": int((seg["end"] if isinstance(seg, dict) else seg.end) * 1000),
        }
        for seg in segments
    ]
