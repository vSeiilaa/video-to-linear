import hashlib
import json
from pathlib import Path
from typing import List, Optional

_CACHE_DIR = Path(".cache/transcripts")


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load(audio_path: Path) -> Optional[List[dict]]:
    p = _CACHE_DIR / f"{_hash(audio_path)}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def save(audio_path: Path, segments: List[dict]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _CACHE_DIR / f"{_hash(audio_path)}.json"
    p.write_text(json.dumps(segments))
