# Bug Video Reporter

Turn narrated testing videos into structured bug reports — automatically.

Record yourself testing a feature, talking through what you see. Upload the video, and the app:

1. Transcribes your narration (OpenAI Whisper)
2. Finds every moment where you describe a bug (LLM)
3. Writes a structured bug report per issue (title, severity, description, steps to reproduce)
4. Extracts a short video clip for each bug
5. Lets you push each bug directly to Linear as a sub-issue under a "Testing session" parent

---

## Prerequisites

| Requirement | Install |
|---|---|
| Python 3.10+ | `brew install python` |
| ffmpeg | `brew install ffmpeg` |
| pip | comes with Python |

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR-ORG/video-bug-report.git
cd video-bug-report

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e .
# …or, for a reproducible pinned install:
#   pip install -r requirements.lock

# 4. Start the server
python -m src.app
```

Then open **http://localhost:8080** in your browser.

> **Debug mode is off by default.** To enable Flask's auto-reloader/debugger
> (do *not* do this when others can reach the port — it allows code execution),
> set `FLASK_DEBUG=1`.

---

## Usage

### API keys
All keys are entered in the app — no `.env` file needed.

Open **Settings → AI** and paste your API key for whichever provider you want to use:

| Provider | Key type | Where to get it |
|---|---|---|
| OpenAI (default) | `sk-…` | platform.openai.com/api-keys |
| Anthropic (Claude) | `sk-ant-…` | console.anthropic.com/keys |
| Gemini | `AI…` | aistudio.google.com/app/apikey |

> **Note for Claude / Gemini users:** audio transcription always uses OpenAI Whisper, so you'll also need to paste an OpenAI key in the secondary *"OpenAI key (for audio transcription)"* field that appears.

### Linear integration (optional)
1. Open **Settings → Linear**, paste your Linear personal API key (`lin_api_…`) — get one at [linear.app/settings/api](https://linear.app/settings/api)
2. Click **Connect** and pick your team
3. After running an analysis, click **Create in Linear** on any bug — it becomes a sub-issue under a *"Testing session — May 6, 2026"* parent created automatically

### Running an analysis
1. Drag your video into the upload box (MP4, MOV, MKV, WEBM, etc.)
2. Click **▶ Run Analysis**
3. Watch the log — it takes 1–3 minutes depending on video length and provider
4. Click any bug in the left panel to read the report and watch the clip

### Storage
Clips and outputs are saved in `out/` (one folder per run). Open **Settings → Storage** to see the exact path and open it in Finder. Delete old run folders freely — the app doesn't need them.

### History
Previous analyses are listed on the home screen. Click any entry to reload the results without re-running.

---

## Supported video formats

MP4 · MOV · AVI · MKV · WEBM · M4V · MPEG

---

## Running on a different port

```bash
PORT=9000 python -m src.app
```

---

## Development

Run the unit tests (cover the pure logic: chunking/dedup, JSON extraction,
Linear formatting, transcript flattening, ffmpeg error parsing):

```bash
pip install -e ".[dev]"
pytest
```
