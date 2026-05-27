"""Cadence email composer — RAG-grounded draft generation.

When a cadence step is `channel: email`, this drafts the body using:
  - The cadence step's note (closer's intent for this touch)
  - The buyer's RAG dossier (real account context)
  - The operator entity (signs the email as the right party)

Returns {subject, body, to_suggested}. Caller (UI) reviews + can send
via email_send.send_raw(). Composition is operator-gated; we don't
auto-send.
"""
from __future__ import annotations
import json
import re
from typing import Optional


COMPOSE_SYSTEM = (
    "You are a sales closer drafting a follow-up email. You write short, "
    "specific, no-fluff messages that reference real account context. "
    "Never use 'I hope this email finds you well' or other filler. "
    "Always include one specific detail from the dossier and one explicit ask."
)


def _strip_json(s: str) -> Optional[dict]:
    """Best-effort JSON extraction from LLM output."""
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.M)
    s = re.sub(r"```\s*$", "", s)
    idx = s.find("{")
    if idx < 0:
        return None
    depth = 0
    for j in range(idx, len(s)):
        if s[j] == "{": depth += 1
        elif s[j] == "}": depth -= 1
        if depth == 0:
            try:
                return json.loads(s[idx:j+1])
            except Exception:
                return None
    return None


def _suggest_recipient(bullpen: str, buyer_slug: str) -> Optional[str]:
    """Best-guess email from the buyer's contacts list."""
    try:
        from contacts import list_for_org
        for c in list_for_org(buyer_slug) or []:
            email = (c.get("email") or "").strip()
            if email and "@" in email:
                return email
    except Exception:
        pass
    # Fall back: search the RAG dossier for "@" patterns (best-effort)
    try:
        from rag import search as rag_search
        hits = rag_search(bullpen, buyer_slug, "email contact reach", k=4)
        for h in hits:
            m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                           h.get("text", ""))
            if m:
                return m.group(0)
    except Exception:
        pass
    return None


def compose_email(
    bullpen: str, *,
    buyer_slug: str,
    step_note: str,
    step_day: int = 0,
    step_template: Optional[str] = None,
) -> dict:
    """Draft a cadence email. Returns {subject, body, to_suggested,
    grounded, operator_entity}.
    """
    # Build context from RAG + step intent
    try:
        from rag import context as rag_context
    except Exception:
        rag_context = lambda *a, **kw: ""

    # Query crafted from the step note — pulls the dossier chunks most
    # relevant to whatever this touch is trying to accomplish.
    query = step_note or f"day {step_day} {step_template or 'follow-up'}"
    ctx = rag_context(bullpen, buyer_slug, query, max_chars=2400) or ""

    # Operator entity (for sign-off)
    try:
        from entity import template_vars as ent_vars
        entity_vars = ent_vars(bullpen) or {}
    except Exception:
        entity_vars = {}
    operator_entity = entity_vars.get("operator_entity", "Your Company LLC")
    operator_signer = entity_vars.get("operator_signer_name") or "Operator"

    user_prompt = f"""Draft the email for this cadence step. Output ONLY a JSON object:
{{
  "subject":   "(7 words or fewer)",
  "body":      "(60-160 words, markdown OK, no emojis)",
  "to_suggested": "(best guess at the contact email if visible in dossier)"
}}

Step intent (day {step_day}, channel: email):
  {step_note}

Template hint: {step_template or '(none)'}

Operator (signs the email):
  {operator_signer} at {operator_entity}

Buyer dossier:
{ctx if ctx else '(no RAG sources yet — keep it generic but specific to the step intent)'}

Constraints:
  - One concrete reference to a real detail from the dossier (if present)
  - One explicit ask at the end (next call / meeting / response)
  - Sign off: '{operator_signer}' from '{operator_entity}'
  - No greetings like 'I hope this finds you well'
  - No closing pleasantries beyond a single 'Thanks' or 'Best'
"""

    try:
        from server import ollama_chat  # type: ignore
        raw = ollama_chat(
            [{"role": "system", "content": COMPOSE_SYSTEM},
             {"role": "user", "content": user_prompt}],
            temperature=0.55,
        )
    except Exception as e:
        raise RuntimeError(f"ollama_chat failed: {e}")

    parsed = _strip_json(raw) or {}
    subject = (parsed.get("subject") or "").strip() or f"Following up · day {step_day}"
    body = (parsed.get("body") or "").strip()
    if not body:
        body = (
            f"{step_note}\n\n"
            f"What's a good time this week to talk?\n\n"
            f"— {operator_signer}\n  {operator_entity}"
        )
    to_suggested = (parsed.get("to_suggested") or "").strip()
    if not to_suggested:
        to_suggested = _suggest_recipient(bullpen, buyer_slug) or ""

    return {
        "subject": subject,
        "body": body,
        "to_suggested": to_suggested,
        "grounded": bool(ctx),
        "operator_entity": operator_entity,
    }
