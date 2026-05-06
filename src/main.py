import argparse
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

from .bug_extractor import Bug, build_bug_reports, find_bug_segments
from .exporter import export_csv, export_html
from .llm import DEFAULT_MODEL, DEFAULT_PROVIDER, Provider
from .media import extract_audio, extract_clip, transcode_for_web
from .prompts import BUG_FINDER_SYSTEM, BUG_REPORT_SYSTEM
from .transcription import transcribe_audio

_CLIP_WORKERS = 4  # parallel ffmpeg processes for clip extraction


def run(
    video: Path,
    out_dir: Path,
    provider: Provider = DEFAULT_PROVIDER,
    model_id: str = DEFAULT_MODEL,
    log: Callable[[str], None] = print,
    finder_prompt: Optional[str] = None,
    report_prompt: Optional[str] = None,
    api_key: Optional[str] = None,      # key for the chosen LLM provider
    openai_key: Optional[str] = None,   # key for Whisper (always OpenAI); falls back to api_key
) -> List[Bug]:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Kick off web-compatible transcode in background immediately so it runs
    # in parallel with the slow API steps (2–4) and is ready by clip time.
    web_video_path = out_dir / "video.mp4"
    _bg_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-transcode")
    web_future: Future = _bg_pool.submit(transcode_for_web, video, web_video_path)
    _bg_pool.shutdown(wait=False)
    log("[1/6] Extracting audio… (web video transcoding in background)")
    audio = extract_audio(video, out_dir / (video.stem + ".mp3"))

    log("[2/6] Transcribing…")
    segments = transcribe_audio(audio, api_key=openai_key or api_key)

    log(f"[3/6] Finding bug segments ({provider} / {model_id})…")
    bug_segments = find_bug_segments(
        segments, provider, model_id, log=log,
        finder_prompt=finder_prompt or BUG_FINDER_SYSTEM,
        api_key=api_key,
    )

    log("[4/6] Building bug reports…")
    bugs = build_bug_reports(
        bug_segments, provider, model_id, log=log,
        report_prompt=report_prompt or BUG_REPORT_SYSTEM,
        api_key=api_key,
    )
    log(f"  Found {len(bugs)} bug(s)")

    # Wait for web transcode before extracting clips (clips use the same source).
    # By now steps 2–4 have consumed several minutes so it's usually already done.
    try:
        web_future.result(timeout=1800)
        log("  Web video ready")
    except Exception as exc:
        log(f"  Web video transcode failed (original will be used): {exc}")

    log(f"[5/6] Extracting {len(bugs)} clip(s) with up to {_CLIP_WORKERS} workers…")
    _extract_clips_parallel(video, bugs, out_dir / "clips", log)

    log("[6/6] Exporting…")
    export_csv(bugs, out_dir / "bugs.csv")
    export_html(bugs, video_path=str(video), out_path=out_dir / "report.html",
                provider=provider, model_id=model_id)

    log(f"Done → {out_dir / 'report.html'}")
    return bugs


def _extract_clips_parallel(
    video: Path,
    bugs: List[Bug],
    clips_dir: Path,
    log: Callable[[str], None],
) -> None:
    total = len(bugs)

    def _one(i: int, bug: Bug):
        log(f"  Starting clip {i + 1}/{total}…")
        extract_clip(video, bug.start_ms, bug.end_ms, clips_dir / f"bug_{i + 1}.mp4")

    with ThreadPoolExecutor(max_workers=_CLIP_WORKERS) as pool:
        futures = {pool.submit(_one, i, bug): i for i, bug in enumerate(bugs)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                future.result()
                log(f"  Clip {i + 1}/{total} done")
            except Exception as exc:
                log(f"  Clip {i + 1}/{total} failed: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["openai", "claude", "gemini"])
    parser.add_argument("--model", default=DEFAULT_MODEL, dest="model_id")
    args = parser.parse_args()

    run(args.video, args.out, provider=args.provider, model_id=args.model_id)
