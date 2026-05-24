"""Universal ingest router — NotebookLM-style "drop anything" → org graph.

Sniffs the input (URL, CSV, PDF, EML, plain text, JSON, audio) and routes to
the right adapter. Returns a uniform result dict for the UI to render.

Usage from server:
    from adapters.ingest import ingest_anything
    result = ingest_anything(raw_bytes, filename="leads.csv", mime="text/csv")
    # or
    result = ingest_anything(b"https://acme.com", filename=None, mime="text/plain")
"""
from __future__ import annotations
import io
import json
import re
import email
import email.policy
from pathlib import Path
from typing import Any

from ._common import slugify, write_org, ollama_extract


URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def ingest_anything(data: bytes, filename: str | None = None, mime: str | None = None) -> dict[str, Any]:
    """Single entry point. Returns {kind, orgs, summary, warnings}."""
    kind = _sniff(data, filename, mime)
    handler = _HANDLERS.get(kind, _ingest_text)
    return handler(data, filename)


def _sniff(data: bytes, filename: str | None, mime: str | None) -> str:
    """Decide how to parse this input. Filename extension wins over MIME."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".eml", ".mbox")):
        return "email"
    if name.endswith(".json"):
        return "json"
    if name.endswith((".md", ".txt", ".markdown")):
        return "text"
    if name.endswith((".wav", ".mp3", ".m4a", ".aiff", ".flac")):
        return "audio"

    if mime:
        m = mime.lower().split(";")[0].strip()
        if m == "text/csv":
            return "csv"
        if m == "application/pdf":
            return "pdf"
        if m in ("message/rfc822", "application/mbox"):
            return "email"
        if m == "application/json":
            return "json"
        if m.startswith("audio/"):
            return "audio"

    head = data[:8]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio"

    try:
        s = data.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        return "binary_unknown"

    if URL_RE.match(s.splitlines()[0] if s else ""):
        return "url"
    if s.startswith("{") and s.endswith("}"):
        try:
            json.loads(s)
            return "json"
        except json.JSONDecodeError:
            pass
    return "text"


def _ingest_url(data: bytes, filename: str | None) -> dict:
    url = data.decode("utf-8").strip().splitlines()[0]
    from .website import ingest_website
    org = ingest_website(url, force=False)
    if not org:
        return {"kind": "url", "orgs": [], "summary": "",
                "warnings": [f"Couldn't extract content from {url} — try a deeper crawl with the firecrawl adapter or paste page text directly"]}
    return {
        "kind": "url",
        "orgs": [org["slug"]],
        "summary": f"Ingested {org['company']} from {url}",
        "warnings": [],
    }


def _ingest_csv(data: bytes, filename: str | None) -> dict:
    """CSV → bulk org creation. Reuses csv_import adapter."""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb")
    tmp.write(data)
    tmp.close()
    try:
        from .csv_import import import_csv
        result = import_csv(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return {
        "kind": "csv",
        "orgs": result.get("created", []),
        "summary": f"Imported {len(result.get('created', []))} orgs from CSV",
        "warnings": result.get("warnings", []),
    }


def _ingest_pdf(data: bytes, filename: str | None) -> dict:
    """PDF → text → Gemma extraction → single org."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {
            "kind": "pdf",
            "orgs": [],
            "summary": "",
            "warnings": ["pypdf not installed — run `pip install pypdf`"],
        }
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for p in reader.pages[:30]:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pass
    text = "\n\n".join(pages).strip()
    if not text:
        return {"kind": "pdf", "orgs": [], "summary": "PDF contained no extractable text",
                "warnings": ["Image-only PDFs need OCR — not wired up yet"]}
    return _extract_org_from_text(text, source=f"PDF: {filename or 'upload'}")


def _ingest_email(data: bytes, filename: str | None) -> dict:
    """Parse .eml file → extract sender/subject/body → org + person."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    sender = msg.get("From", "")
    subject = msg.get("Subject", "")
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body_parts.append(part.get_content())
                except Exception:
                    pass
    else:
        try:
            body_parts.append(msg.get_content())
        except Exception:
            pass
    body = "\n".join(body_parts).strip()
    blob = f"From: {sender}\nSubject: {subject}\n\n{body}"
    return _extract_org_from_text(blob, source=f"Email: {subject or filename or 'upload'}")


def _ingest_json(data: bytes, filename: str | None) -> dict:
    """JSON → assume it's an org or list of orgs in our schema."""
    obj = json.loads(data.decode("utf-8"))
    orgs_in = obj if isinstance(obj, list) else [obj]
    created = []
    for o in orgs_in:
        if not isinstance(o, dict) or "company" not in o:
            continue
        slug = o.get("slug") or slugify(o["company"])
        write_org(slug, o, digital=o.get("digital", []))
        created.append(slug)
    return {
        "kind": "json",
        "orgs": created,
        "summary": f"Imported {len(created)} orgs from JSON",
        "warnings": [] if created else ["No valid org records found — each entry needs at minimum a 'company' field"],
    }


def _ingest_text(data: bytes, filename: str | None) -> dict:
    """Plain text or markdown → Gemma extracts an org (or batch if list-like)."""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return {"kind": "text", "orgs": [], "summary": "", "warnings": ["Empty input"]}
    return _extract_org_from_text(text, source=f"Text: {filename or 'paste'}")


def _ingest_audio(data: bytes, filename: str | None) -> dict:
    """Audio belongs to a specific org — route via /api/upload-call?org=<slug>.

    The universal ingest doesn't have org context, so audio without a target org
    can't be debriefed into the right call log. The drop-zone UI handles this
    by surfacing the warning and prompting for org selection.
    """
    return {
        "kind": "audio",
        "orgs": [],
        "summary": "",
        "warnings": ["Audio files need an org target — use the Record button on a prospect card, or POST to /api/upload-call?org=<slug>"],
    }


def _ingest_binary_unknown(data: bytes, filename: str | None) -> dict:
    return {
        "kind": "binary_unknown",
        "orgs": [],
        "summary": "",
        "warnings": [f"Couldn't determine file type for {filename or 'upload'} — supported: URL, CSV, PDF, EML, JSON, TXT, MD, WAV"],
    }


_HANDLERS = {
    "url": _ingest_url,
    "csv": _ingest_csv,
    "pdf": _ingest_pdf,
    "email": _ingest_email,
    "json": _ingest_json,
    "text": _ingest_text,
    "audio": _ingest_audio,
    "binary_unknown": _ingest_binary_unknown,
}


# ---------------- Gemma extraction ----------------

_EXTRACT_PROMPT = """\
You are extracting sales-prospect data from a document. Read the content below
and pull out the company being described. If multiple companies appear (a
prospect list, a meeting-notes doc covering several leads), return all of them
as a list under "orgs".

Content:
---
{text}
---

For each org, fill what you can — leave fields null if not supported by the text.
Do not fabricate phone numbers or revenue figures. If something feels uncertain,
prefer null over a guess.
"""

_EXTRACT_SCHEMA = """\
{
  "orgs": [
    {
      "company": "string · required",
      "slug": "lowercase-hyphenated or null (will be generated)",
      "role": "buyer's likely title or null",
      "hq": "city, state and optional employee count, or null",
      "phone": "string or null",
      "bio": "2-4 sentence narrative about the company and buying context",
      "what": "one-line description of what they do",
      "techStack": "their stack, tools, key vendors — comma-separated or null",
      "abc": "your best opening line for this prospect, 1-2 sentences"
    }
  ]
}
"""


def _extract_org_from_text(text: str, source: str) -> dict:
    """Common extraction path for text-derived inputs."""
    text = text[:12000]
    try:
        parsed = ollama_extract(_EXTRACT_PROMPT.format(text=text), _EXTRACT_SCHEMA)
    except Exception as e:
        return {"kind": "text", "orgs": [], "summary": "", "warnings": [f"Extraction failed: {e}"]}

    orgs_in = parsed.get("orgs") or []
    if isinstance(orgs_in, dict):
        orgs_in = [orgs_in]

    created = []
    for o in orgs_in:
        if not isinstance(o, dict) or not o.get("company"):
            continue
        slug = o.get("slug") or slugify(o["company"])
        base = {k: v for k, v in o.items() if v is not None}
        base["slug"] = slug
        base.setdefault("zone", "end")
        base.setdefault("source", source)
        write_org(slug, base, digital=[source])
        created.append(slug)

    return {
        "kind": "text",
        "orgs": created,
        "summary": f"Extracted {len(created)} org(s) from {source}",
        "warnings": [] if created else ["Gemma returned no usable org records — try a more specific source document"],
    }
