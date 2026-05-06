"""Linear GraphQL API client.

Flow for create_session_issue():
  1. issueCreate mutation → top-level "Testing session — May 6, 2026" issue

Flow for create_issue():
  1. fileUpload mutation  → UploadFile {uploadUrl, assetUrl, headers}  (non-fatal if it fails)
  2. PUT clip to S3       → file now hosted at Linear CDN              (non-fatal if it fails)
  3. issueCreate mutation → sub-issue under the session (parentId set if provided)
  4. attachmentCreate     → clip shown as native attachment             (non-fatal if it fails)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import requests

_GQL = "https://api.linear.app/graphql"

_SEV_TO_PRIORITY: dict[str, int] = {
    "critical": 1,  # Urgent
    "high":     2,  # High
    "medium":   3,  # Medium
    "low":      4,  # Low
}


# ── GraphQL helper ────────────────────────────────────────────────────────────

def _call(api_key: str, query: str, variables: dict | None = None) -> dict:
    resp = requests.post(
        _GQL,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    if not resp.ok:
        # Include the response body so callers can see the actual error
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:400]
        raise RuntimeError(f"HTTP {resp.status_code} from Linear API: {detail}")
    body = resp.json()
    if "errors" in body:
        msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
        raise RuntimeError(msgs)
    return body["data"]


# ── Public API ────────────────────────────────────────────────────────────────

def get_teams(api_key: str) -> list[dict]:
    """Return [{id, name, key}, …] for all teams the key has access to."""
    data = _call(api_key, "query { teams { nodes { id name key } } }")
    return data["teams"]["nodes"]


def create_session_issue(api_key: str, team_id: str, date_str: str) -> dict:
    """Create the top-level 'Testing session — <date>' parent issue.

    Returns {"id": "…uuid…", "identifier": "ENG-42", "url": "https://…"}.
    """
    return _create_issue(
        api_key=api_key,
        team_id=team_id,
        title=f"Testing session — {date_str}",
        md="",
        severity="medium",
    )


def create_issue(
    api_key:     str,
    team_id:     str,
    title:       str,
    description: str,
    severity:    str,
    clip_path:   Optional[Path] = None,
    start_ms:    int = 0,
    end_ms:      int = 0,
    parent_id:   Optional[str] = None,
) -> dict:
    """Create a Linear issue (optionally as sub-issue), upload the clip if possible.

    Clip upload failures are non-fatal: the issue is still created, just
    without the video attachment.

    Returns {"identifier": "ENG-123", "url": "https://linear.app/…"}.
    """
    # Step 1: try to upload the clip (best-effort)
    asset_url:    str | None = None
    clip_warning: str | None = None

    if clip_path and clip_path.exists():
        try:
            asset_url = _upload_clip(api_key, clip_path)
        except Exception as exc:
            clip_warning = str(exc)
            print(f"[linear] clip upload failed (issue will be created without video): {exc}",
                  file=sys.stderr)

    # Step 2: create the issue
    md    = _build_description(description, asset_url, start_ms, end_ms)
    issue = _create_issue(api_key, team_id, title, md, severity, parent_id=parent_id)

    # Step 3: add native attachment (best-effort)
    if asset_url:
        try:
            _attach_file(api_key, issue["id"], asset_url)
        except Exception as exc:
            print(f"[linear] attachmentCreate failed (issue exists, just no sidebar attachment): {exc}",
                  file=sys.stderr)

    result: dict = {"identifier": issue["identifier"], "url": issue["url"]}
    if clip_warning:
        result["clip_warning"] = clip_warning
    return result


# ── Private helpers ───────────────────────────────────────────────────────────

def _upload_clip(api_key: str, path: Path) -> str:
    """Upload *path* to Linear's S3 storage; return the public asset URL.

    Linear's UploadPayload.uploadFile is an UploadFile object with:
      - uploadUrl  — pre-signed S3 PUT URL
      - assetUrl   — permanent CDN URL (use this as the attachment link)
      - headers    — [{key, value}, …] required by S3 alongside the PUT
    """
    size = path.stat().st_size

    # Step 1: request a pre-signed upload URL from Linear
    data = _call(api_key, """
        mutation FileUpload($contentType: String!, $filename: String!, $size: Int!) {
            fileUpload(contentType: $contentType, filename: $filename, size: $size) {
                uploadFile {
                    uploadUrl
                    assetUrl
                    headers {
                        key
                        value
                    }
                }
            }
        }
    """, {
        "contentType": "video/mp4",
        "filename":    path.name,
        "size":        size,
    })

    uf         = data["fileUpload"]["uploadFile"]
    upload_url = uf["uploadUrl"]
    asset_url  = uf["assetUrl"]

    # Build the header dict Linear wants us to forward to S3
    extra_headers = {h["key"]: h["value"] for h in (uf.get("headers") or [])}
    extra_headers.setdefault("Content-Type", "video/mp4")

    # Step 2: stream the file to S3
    with open(path, "rb") as fh:
        put = requests.put(
            upload_url,
            data=fh,
            headers=extra_headers,
            timeout=300,
        )
    if not put.ok:
        raise RuntimeError(f"S3 upload failed: HTTP {put.status_code} — {put.text[:200]}")

    return asset_url


def _ms_to_ts(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _build_description(
    description: str,
    asset_url:   str | None,
    start_ms:    int,
    end_ms:      int,
) -> str:
    parts = [description]
    if asset_url:
        parts.append(f"\n[🎬 Bug clip]({asset_url})")
    return "\n".join(parts)


def _create_issue(
    api_key:   str,
    team_id:   str,
    title:     str,
    md:        str,
    severity:  str,
    parent_id: Optional[str] = None,
) -> dict:
    variables: dict = {
        "input": {
            "teamId":      team_id,
            "title":       title,
            "description": md,
            "priority":    _SEV_TO_PRIORITY.get(severity.lower(), 3),
        }
    }
    if parent_id:
        variables["input"]["parentId"] = parent_id

    data = _call(api_key, """
        mutation IssueCreate($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue { id identifier url }
            }
        }
    """, variables)
    return data["issueCreate"]["issue"]


def _attach_file(api_key: str, issue_id: str, asset_url: str) -> None:
    """Add the uploaded clip as a native attachment in the issue sidebar."""
    _call(api_key, """
        mutation AttachmentCreate($input: AttachmentCreateInput!) {
            attachmentCreate(input: $input) { success }
        }
    """, {
        "input": {
            "issueId": issue_id,
            "title":   "Bug clip",
            "url":     asset_url,
        }
    })
