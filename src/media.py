import subprocess
from pathlib import Path

_CLIP_TIMEOUT = 300   # seconds per clip before giving up
_WEB_TIMEOUT  = 1800  # seconds for full-video transcode (30 min)

# Each entry is the complete set of video-encoder flags for one attempt.
# -pix_fmt yuv420p is passed directly to the encoder (not as a -vf software
# filter) so VideoToolbox receives proper CoreVideo frames and doesn't produce
# silent black video.  libx264 handles the same flag natively.
_VIDEO_ENCODERS = [
    ["-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p"],
    ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"],
]


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """Extract and re-encode audio to mp3 (supported by OpenAI transcription API)."""
    mp3_path = audio_path.with_suffix(".mp3")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-q:a", "4",
        str(mp3_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return mp3_path


def transcode_for_web(video_path: Path, out_path: Path) -> Path:
    """Re-encode the full video to browser-safe H.264/AAC mp4.

    Uses -pix_fmt yuv420p per encoder (not a -vf software filter) so
    VideoToolbox receives proper CoreVideo frames and produces real video.
    """
    out_path = out_path.with_suffix(".mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-c:a", "aac",
        "-movflags", "+faststart",
    ]

    last_exc: Exception = RuntimeError("No encoders attempted")
    for video_args in _VIDEO_ENCODERS:
        cmd = base + video_args + [str(out_path)]
        try:
            subprocess.run(
                cmd, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=_WEB_TIMEOUT,
            )
            return out_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            out_path.unlink(missing_ok=True)

    raise RuntimeError(f"Web transcode failed: {last_exc}")


def extract_clip(
    video_path: Path,
    start_ms: int,
    end_ms: int,
    out_path: Path,
    buffer_ms: int = 2000,
) -> Path:
    """Cut a clip from *video_path* between start_ms and end_ms.

    Adds a buffer on both sides for context. Uses -pix_fmt yuv420p per encoder
    (not a -vf software filter) to avoid black-video from VideoToolbox.
    """
    start_sec = max(0.0, (start_ms - buffer_ms) / 1000)
    duration_sec = (end_ms - start_ms + 2 * buffer_ms) / 1000

    out_path = out_path.with_suffix(".mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-i", str(video_path),
        "-t", f"{duration_sec:.3f}",
        "-c:a", "aac",
        "-movflags", "+faststart",
    ]

    last_exc: Exception = RuntimeError("No encoders attempted")
    for video_args in _VIDEO_ENCODERS:
        cmd = base + video_args + [str(out_path)]
        try:
            subprocess.run(
                cmd, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=_CLIP_TIMEOUT,
            )
            return out_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            out_path.unlink(missing_ok=True)

    raise RuntimeError(f"All encoders failed for clip {out_path.name}: {last_exc}")
