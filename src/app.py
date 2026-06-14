"""Flask web app entry point: python -m src.app"""
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from .linear_client import create_issue as _linear_create_issue
from .linear_client import create_session_issue as _linear_create_session_issue
from .linear_client import get_teams as _linear_get_teams
from .llm import DEFAULT_MODEL, DEFAULT_PROVIDER, PROVIDER_MODELS
from .main import run
from .prompts import BUG_FINDER_SYSTEM, BUG_REPORT_SYSTEM

_TEMPLATES = Path(__file__).parent.parent / "templates"
_UPLOAD_DIR = Path("uploads")
_OUT_DIR = Path("out")

_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg"}

app = Flask(__name__, template_folder=str(_TEMPLATES))
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB

# job_id -> {status, log, bugs, video_url}
_jobs: dict[str, dict] = {}
# Guards _jobs: the worker thread mutates job state (e.g. appends to "log")
# while /status serializes it, which can otherwise read a list mid-append.
_jobs_lock = threading.Lock()

# Cap on in-memory jobs. Finished jobs are persisted to out/<id>/meta.json and
# reloaded on demand (see linear_create / history), so evicting the oldest
# completed entries here is lossless and just prevents unbounded growth.
_MAX_JOBS = 50


def _evict_jobs_locked() -> None:
    """Drop oldest finished jobs once over _MAX_JOBS. Caller must hold _jobs_lock."""
    if len(_jobs) <= _MAX_JOBS:
        return
    finished = [jid for jid, j in _jobs.items() if j.get("status") in ("done", "error")]
    for jid in finished:
        if len(_jobs) <= _MAX_JOBS:
            break
        _jobs.pop(jid, None)


@app.route("/")
def index():
    return render_template(
        "index.html",
        providers=PROVIDER_MODELS,
        finder_prompt=BUG_FINDER_SYSTEM.strip(),
        report_prompt=BUG_REPORT_SYSTEM.strip(),
        output_dir=str(_OUT_DIR.resolve()),
        uploads_dir=str(_UPLOAD_DIR.resolve()),
    )


@app.route("/open-storage")
def open_storage():
    """Open the output folder in the OS file manager (Finder / Explorer / Nautilus)."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = str(_OUT_DIR.resolve())
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)          # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/uploads/<path:filename>")
def serve_upload(filename: str):
    return send_from_directory(_UPLOAD_DIR.resolve(), filename)


@app.route("/out/<path:filename>")
def serve_out(filename: str):
    return send_from_directory(_OUT_DIR.resolve(), filename)


@app.route("/run", methods=["POST"])
def run_job():
    provider    = request.form.get("provider",    DEFAULT_PROVIDER)
    model_id    = request.form.get("model_id",    DEFAULT_MODEL)
    finder_prompt = request.form.get("finder_prompt", "").strip() or None
    report_prompt = request.form.get("report_prompt", "").strip() or None
    api_key     = request.form.get("ai_api_key",  "").strip() or None
    # Whisper always uses OpenAI; if provider is OpenAI the same key covers both.
    # For Claude/Gemini users a separate openai_transcription_key can be supplied.
    openai_key  = request.form.get("openai_transcription_key", "").strip() or None
    if not openai_key and provider == "openai":
        openai_key = api_key

    uploaded = request.files.get("video")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "No file uploaded"}), 400

    ext = Path(uploaded.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported format '{ext}'. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"}), 400

    _UPLOAD_DIR.mkdir(exist_ok=True)
    filename = str(uuid.uuid4()) + ext
    video_path = _UPLOAD_DIR / filename
    uploaded.save(str(video_path))

    job_id = str(uuid.uuid4())
    video_url = f"/uploads/{filename}"
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running", "log": [], "bugs": None, "video_url": video_url,
            "original_filename": uploaded.filename,
            "provider": provider, "model_id": model_id,
        }
        _evict_jobs_locked()

    def worker():
        job = _jobs[job_id]

        def log(msg: str):
            with _jobs_lock:
                job["log"].append(msg)

        try:
            out_dir = _OUT_DIR / job_id
            bugs = run(
                video_path, out_dir,
                provider=provider, model_id=model_id,
                log=log,
                finder_prompt=finder_prompt,
                report_prompt=report_prompt,
                api_key=api_key,
                openai_key=openai_key,
            )
            bugs_data = []
            for i, b in enumerate(bugs):
                d = b.model_dump()
                clip_path = out_dir / "clips" / f"bug_{i + 1}.mp4"
                d["clip_url"] = f"/out/{job_id}/clips/bug_{i + 1}.mp4" if clip_path.exists() else None
                bugs_data.append(d)
            job["bugs"] = bugs_data
            # Use the browser-safe transcoded video if available, else original upload
            web_video = out_dir / "video.mp4"
            if web_video.exists():
                job["video_url"] = f"/out/{job_id}/video.mp4"
            job["status"] = "done"
            # Persist metadata so history survives server restarts
            try:
                meta = {
                    "job_id":            job_id,
                    "created_at":        datetime.now(timezone.utc).isoformat(),
                    "original_filename": job.get("original_filename", ""),
                    "provider":          job.get("provider", ""),
                    "model_id":          job.get("model_id", ""),
                    "bug_count":         len(bugs_data),
                    "video_url":         job["video_url"],
                    "bugs":              bugs_data,
                }
                (out_dir / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2)
                )
            except Exception:
                pass  # metadata loss is non-fatal
        except Exception as exc:
            job["log"].append(f"ERROR: {exc}")
            job["status"] = "error"

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "unknown job"}), 404
        # Snapshot under the lock so we never serialize "log" mid-append.
        snapshot = {**job, "log": list(job["log"])}
    return jsonify(snapshot)


@app.route("/history")
def history():
    """Return past completed jobs, newest first, by scanning out/*/meta.json."""
    entries = []
    if _OUT_DIR.exists():
        metas = []
        for p in _OUT_DIR.glob("*/meta.json"):
            try:
                metas.append(json.loads(p.read_text()))
            except Exception:
                pass
        metas.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        entries = metas
    return jsonify({"history": entries})


@app.route("/linear/teams")
def linear_teams():
    key = request.headers.get("X-Linear-Key", "").strip()
    if not key:
        return jsonify({"error": "Missing API key"}), 400
    try:
        return jsonify({"teams": _linear_get_teams(key)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/linear/create-issue", methods=["POST"])
def linear_create():
    key = request.headers.get("X-Linear-Key", "").strip()
    if not key:
        return jsonify({"error": "Missing API key"}), 400

    body    = request.get_json() or {}
    job_id  = body.get("job_id")
    bug_idx = body.get("bug_index")
    team_id = body.get("team_id")

    if not job_id or bug_idx is None or not team_id:
        return jsonify({"error": "job_id, bug_index and team_id are required"}), 400

    job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        # Fallback: load from persisted meta (e.g. after server restart)
        meta_file = _OUT_DIR / job_id / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                job = {"status": "done", "bugs": meta["bugs"]}
                _jobs[job_id] = job
            except Exception:
                pass
    if not job or job["status"] != "done":
        return jsonify({"error": "Job not found or not finished"}), 404

    bugs = job.get("bugs", [])
    if not (0 <= bug_idx < len(bugs)):
        return jsonify({"error": "bug_index out of range"}), 400

    bug  = bugs[bug_idx]
    clip = _OUT_DIR / job_id / "clips" / f"bug_{bug_idx + 1}.mp4"

    # Allow the UI to send edited title/description (inline editing before push)
    title       = (body.get("title") or "").strip() or bug["title"]
    description = (body.get("description") or "").strip() or bug["description"]

    try:
        # ── Session issue: create once per job, reuse for every subsequent bug ──
        session = job.get("linear_session")
        if not session:
            d        = datetime.now()
            date_str = f"{d.strftime('%B')} {d.day}, {d.year}"   # e.g. "May 6, 2026"
            s_issue  = _linear_create_session_issue(key, team_id, date_str)
            session  = {
                "id":         s_issue["id"],
                "identifier": s_issue["identifier"],
                "url":        s_issue["url"],
            }
            job["linear_session"] = session   # cache for the lifetime of the process

        # ── Bug issue as sub-issue under the session ──────────────────────────
        result = _linear_create_issue(
            api_key=key,
            team_id=team_id,
            title=title,
            description=description,
            severity=bug.get("severity", "medium"),
            clip_path=clip if clip.exists() else None,
            start_ms=bug.get("start_ms", 0),
            end_ms=bug.get("end_ms", 0),
            parent_id=session["id"],
        )
        result["session"] = session   # pass session info back to the UI
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Debug mode enables the Werkzeug interactive debugger, which allows
    # arbitrary code execution from the browser and can leak API keys in
    # tracebacks. Keep it off unless explicitly opted in via FLASK_DEBUG=1.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, threaded=True, port=port)
