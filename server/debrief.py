"""
Post-call debrief — the killer feature.

Input:  organizations/<slug>/calls/<call-id>/recording.wav
Output:
  - transcript.txt           ← whisper.cpp
  - extracted.json           ← Gemma structured extraction
  - summary.md               ← human-readable brief
  - metadata.json            ← {date, duration, participants, outcome}
  AND it auto-writes:
  - organizations/<slug>/people/<new-person-slug>/   ← new contacts found
  - organizations/<slug>/deals/<deal-slug>/          ← new/updated deal
  - organizations/<slug>/timeline.md                 ← appended line

The Gemma extraction prompt is structured-output: returns JSON with explicit
fields for speakers, commitments, deal-stage signal, etc. We then map that
into the file structure.

CLI:
    python3 -m server.debrief <org-slug>/<call-id>
"""
from __future__ import annotations
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
ORGS = REPO / "organizations"

# Reuse the server's voice + ollama helpers via module import. Since this
# module may be imported by the server itself, lazy-import to avoid cycles.
def _whisper_model() -> Path:
    """Prefer ggml-small.en.bin (4x more accurate than base) when present;
    fall back to base for graceful behavior before the upgrade."""
    small = REPO / "server" / "models" / "ggml-small.en.bin"
    base  = REPO / "server" / "models" / "ggml-base.en.bin"
    return small if small.exists() else base


def _ollama_extract(prompt: str, schema_hint: str = "", model: str = "gemma2:9b") -> dict:
    """Local Ollama call → parsed JSON."""
    import urllib.request
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You output ONLY valid JSON. No prose, no markdown fences, no explanations."},
            {"role": "user", "content": prompt + ("\n\nReturn this exact schema:\n" + schema_hint if schema_hint else "")},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 16384},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read())
    content = data.get("message", {}).get("content", "").strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```\s*$", "", content)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise RuntimeError(f"Ollama returned no JSON: {content[:200]}")
    return json.loads(m.group(0))


EXTRACTION_PROMPT = """You are a senior sales-ops analyst reviewing the transcript of a sales call. Read it carefully and pull out structured intel.

Identify all SPEAKERS in the conversation. One of them is Dylan Beers (the seller). The others are people from the target company.

For each NON-DYLAN speaker, output:
  name:               Their name if stated, or "(unknown)" if never said
  inferredName:       Best guess at name from context (e.g. "the assistant," "the gatekeeper")
  role:               Their job title if mentioned, or "(unknown)"
  email:              Email address if mentioned, or null
  phone:              Phone number if mentioned, or null
  relationship:       One of: "gatekeeper" | "champion" | "decision_maker" | "blocker" | "informational"
  voiceProfile:       1 sentence describing how they talked (warm? hostile? formal? distracted?)

Also extract from the call:
  commitments:        Array of explicit commitments. Each: { who: "Dylan" or "Them", what: string, by_when: "Thursday" / null }
  newContacts:        Array of names mentioned but not on the call (e.g. "talk to Rajeev, our architect"). Each: { name, role, why }
  dealSignal:         One of: "cold" | "interest" | "warm" | "meeting_booked" | "proposal_requested" | "rejected"
  dealStageChangeReason: 1 sentence explaining the stage signal
  nextAction:         1 sentence: what Dylan should do next
  nextActionDate:     ISO date (YYYY-MM-DD) if specified, else null
  meetingTime:        ISO datetime if a meeting was scheduled, else null
  meetingAttendees:   Array of names if a meeting was scheduled, else []
  redFlags:           Array of concerning signals (objections, escalations, dismissive language)
  greenFlags:         Array of positive signals (engagement, follow-up agreement, specific interest)
  summary:            2-3 sentence neutral summary of what happened

Be conservative. Use null or "(unknown)" rather than hallucinating.

TRANSCRIPT:
---
{transcript}
---"""


def _slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s or "unknown")[:max_len]


def transcribe(audio_path: Path) -> str:
    """Run whisper-cli, return the transcript text."""
    model = _whisper_model()
    if not model.exists():
        raise RuntimeError(f"whisper model not found at {model}")
    out_base = str(audio_path)[:-4]  # strip extension
    r = subprocess.run(
        ["whisper-cli", "-m", str(model), str(audio_path),
         "-nt", "-otxt", "-of", out_base, "-l", "en", "-t", "4"],
        capture_output=True, timeout=600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"whisper failed: {r.stderr.decode(errors='ignore')[:400]}")
    txt = Path(out_base + ".txt")
    if not txt.exists():
        raise RuntimeError("whisper produced no .txt output")
    return txt.read_text().strip()


def debrief_call(org_slug: str, call_id: str) -> dict:
    """Run the full debrief pipeline on a single call directory."""
    org_dir = ORGS / org_slug
    if not org_dir.exists():
        raise RuntimeError(f"org not found: {org_dir}")
    call_dir = org_dir / "calls" / call_id
    if not call_dir.exists():
        raise RuntimeError(f"call not found: {call_dir}")

    # Find the audio file
    audio = None
    for cand in ("recording.wav", "recording.m4a", "recording.mp3"):
        if (call_dir / cand).exists():
            audio = call_dir / cand
            break
    transcript_path = call_dir / "transcript.txt"
    if audio:
        # If we have audio but no transcript yet, transcribe.
        if not transcript_path.exists() or transcript_path.stat().st_size == 0:
            print(f"  ▸ transcribing {audio.name}…")
            transcript = transcribe(audio)
            transcript_path.write_text(transcript + "\n")
        else:
            transcript = transcript_path.read_text()
    elif transcript_path.exists():
        # No audio but a hand-typed transcript is fine
        transcript = transcript_path.read_text()
        print(f"  ▸ using existing transcript ({len(transcript)} chars)")
    else:
        raise RuntimeError(f"no recording.wav or transcript.txt in {call_dir}")

    if len(transcript) < 80:
        raise RuntimeError(f"transcript too short ({len(transcript)} chars) — was the audio empty?")

    print(f"  ▸ running Gemma extraction (~30s)…")
    extracted = _ollama_extract(EXTRACTION_PROMPT.format(transcript=transcript[:18000]))

    extracted_path = call_dir / "extracted.json"
    extracted_path.write_text(json.dumps(extracted, indent=2) + "\n")

    # ── Auto-create new people ──
    speakers = extracted.get("speakers", []) or []
    new_contacts = extracted.get("newContacts", []) or []
    created_people = []
    for entry in speakers + new_contacts:
        name = entry.get("name") or entry.get("inferredName")
        if not name or name == "(unknown)":
            continue
        # Skip Dylan (the caller)
        if name.lower().startswith("dylan") or "beers" in name.lower():
            continue
        slug = _slugify(name)
        pdir = org_dir / "people" / slug
        if pdir.exists():
            continue  # already known
        pdir.mkdir(parents=True, exist_ok=True)
        person = {
            "slug": slug,
            "personName": name,
            "role": entry.get("role") or "(unknown)",
            "relationship": entry.get("relationship") or "informational",
            "email": entry.get("email"),
            "phone": entry.get("phone"),
            "discovered_from": f"call:{call_id}",
            "discovered_at": datetime.date.today().isoformat(),
        }
        (pdir / "person.json").write_text(json.dumps(person, indent=2) + "\n")
        if entry.get("voiceProfile"):
            (pdir / "speech_profile.md").write_text(entry["voiceProfile"] + "\n")
        created_people.append(slug)

    # ── Auto-update deal ──
    deal_signal = extracted.get("dealSignal") or "cold"
    if deal_signal in ("interest", "warm", "meeting_booked", "proposal_requested", "rejected"):
        deal_stage = {
            "interest": "connected",
            "warm": "qualified",
            "meeting_booked": "discovery",
            "proposal_requested": "proposal",
            "rejected": "disqualified",
        }[deal_signal]
        deal_slug = f"deal-{datetime.date.today().isoformat()}"
        ddir = org_dir / "deals" / deal_slug
        ddir.mkdir(parents=True, exist_ok=True)
        deal_path = ddir / "deal.json"
        if deal_path.exists():
            deal = json.loads(deal_path.read_text())
        else:
            deal = {"slug": deal_slug, "name": "Auto-created from call",
                    "created": datetime.date.today().isoformat(), "history": []}
        previous_stage = deal.get("stage", "cold")
        deal["stage"] = deal_stage
        deal["next_action"] = extracted.get("nextAction")
        deal["next_action_date"] = extracted.get("nextActionDate")
        deal["history"].append({
            "date": datetime.date.today().isoformat(),
            "stage_from": previous_stage,
            "stage_to": deal_stage,
            "trigger": f"call:{call_id}",
            "reason": extracted.get("dealStageChangeReason"),
        })
        deal_path.write_text(json.dumps(deal, indent=2) + "\n")

    # ── Write the human-readable summary.md ──
    summary_lines = [
        f"# Call summary · {call_id}",
        "",
        f"**Date:** {datetime.date.today().isoformat()}",
        f"**Org:** {org_slug}",
        f"**Signal:** {deal_signal}",
        "",
        "## Summary",
        "",
        extracted.get("summary", "(no summary extracted)"),
        "",
    ]
    if extracted.get("greenFlags"):
        summary_lines += ["## ✓ Green flags", ""]
        summary_lines += [f"- {g}" for g in extracted["greenFlags"]]
        summary_lines.append("")
    if extracted.get("redFlags"):
        summary_lines += ["## ✗ Red flags", ""]
        summary_lines += [f"- {r}" for r in extracted["redFlags"]]
        summary_lines.append("")
    if extracted.get("commitments"):
        summary_lines += ["## Commitments", ""]
        for c in extracted["commitments"]:
            who, what, by = c.get("who"), c.get("what"), c.get("by_when")
            summary_lines.append(f"- **{who}**: {what}" + (f" · _by {by}_" if by else ""))
        summary_lines.append("")
    if created_people:
        summary_lines += ["## New contacts created", ""]
        summary_lines += [f"- people/{p}/" for p in created_people]
        summary_lines.append("")
    if extracted.get("nextAction"):
        summary_lines += ["## Next action", ""]
        summary_lines.append(extracted["nextAction"])
        date = extracted.get("nextActionDate")
        if date:
            summary_lines.append(f"_By {date}_")
        summary_lines.append("")

    (call_dir / "summary.md").write_text("\n".join(summary_lines))

    # ── Append to timeline ──
    timeline_path = org_dir / "timeline.md"
    existing = timeline_path.read_text() if timeline_path.exists() else "# Timeline\n\n"
    new_line = (
        f"- **{datetime.date.today().isoformat()}** · call:{call_id} · {deal_signal}"
        + (f" · {len(created_people)} new contact(s)" if created_people else "")
        + (f" · next: {extracted['nextAction']}" if extracted.get("nextAction") else "")
        + "\n"
    )
    timeline_path.write_text(existing + new_line)

    # ── Metadata stub ──
    rep_file = call_dir / "rep.txt"
    rep = rep_file.read_text().strip() if rep_file.exists() else "self"
    meta = {
        "call_id": call_id,
        "org": org_slug,
        "date": datetime.date.today().isoformat(),
        "rep": rep,
        "transcript_chars": len(transcript),
        "speaker_count": len(speakers),
        "deal_signal": deal_signal,
        "created_people": created_people,
    }
    (call_dir / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")

    try:
        from metrics import compute_text_metrics
        speech_metrics = compute_text_metrics(transcript)
        (call_dir / "metrics.json").write_text(json.dumps(speech_metrics, indent=2) + "\n")
    except Exception as e:
        print(f"  ⚠ metrics computation failed: {e}")
        speech_metrics = {}

    print(f"✓ debrief complete · {len(created_people)} new contact(s) · signal={deal_signal}")
    return {
        "extracted": extracted,
        "created_people": created_people,
        "deal_signal": deal_signal,
        "metrics": speech_metrics,
    }


def main():
    ap = argparse.ArgumentParser(description="Debrief a recorded call.")
    ap.add_argument("path", help="Either '<org-slug>/<call-id>' or a full path to the call dir")
    args = ap.parse_args()
    if "/" in args.path and not args.path.startswith("/"):
        org_slug, call_id = args.path.split("/", 1)
    else:
        p = Path(args.path).resolve()
        if not p.exists():
            sys.exit(f"× path not found: {p}")
        org_slug = p.parent.parent.name
        call_id = p.name
    debrief_call(org_slug, call_id)


if __name__ == "__main__":
    main()
