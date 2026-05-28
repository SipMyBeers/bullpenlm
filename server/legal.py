"""Legal docs — render markdown docs under bullpens/<slug>/legal/ with a
sha256 fingerprint, parse a rate table out of the referral agreement, and
manage signatures.

A signature binds to (rep, doc, doc_sha256, signed_at). When the doc text
changes, sha256 changes, the rep's signature is no longer "current" — the
UI should surface a "your signed version is out of date" banner.

Storage layout (per bullpen):
  bullpens/<slug>/legal/<doc>.md                  — source doc
  bullpens/<slug>/legal/<doc>.meta.json           — cached version/sha
  bullpens/<slug>/signatures/<rep>/<doc>-v<n>.json — one per signing
  bullpens/<slug>/members/<rep>.json:signed_docs  — running pointer list
"""
from __future__ import annotations
import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from audit import append as audit_append

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"


def _legal_dir(bullpen: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "legal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sig_dir(bullpen: str, rep: str) -> Path:
    d = BULLPENS_ROOT / bullpen / "signatures" / rep
    d.mkdir(parents=True, exist_ok=True)
    return d


def _members_dir(bullpen: str) -> Path:
    return BULLPENS_ROOT / bullpen / "members"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9\-]", "-", name.lower().strip()).strip("-")


def _doc_path(bullpen: str, doc: str) -> Path:
    """Resolve doc name to .md file; accepts 'referral-agreement' or 'referral-agreement.md'."""
    if not doc.endswith(".md"):
        doc = doc + ".md"
    return _legal_dir(bullpen) / doc


# ── Listing + reading ────────────────────────────────────────────────────

def list_docs(bullpen: str) -> list[dict]:
    """Return one entry per .md doc in the bullpen's legal folder."""
    out = []
    for f in sorted(_legal_dir(bullpen).glob("*.md")):
        text = f.read_text(encoding="utf-8")
        sha = _sha256(text)
        meta = {
            "id": f.stem,
            "filename": f.name,
            "title": _extract_title(text),
            "sha256": sha,
            "size": len(text),
            "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
        }
        out.append(meta)
    return out


def get_doc(bullpen: str, doc: str) -> Optional[dict]:
    f = _doc_path(bullpen, doc)
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    sha = _sha256(text)
    return {
        "id": f.stem,
        "filename": f.name,
        "title": _extract_title(text),
        "sha256": sha,
        "size": len(text),
        "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
        "body_md": text,
        "rates": parse_rate_table(text),
    }


def _extract_title(md: str) -> str:
    for line in md.splitlines()[:10]:
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


# ── Rate-table parser (for commissions) ──────────────────────────────────
#
# Looks for markdown tables shaped like:
#   | Revenue type ... | Commission rate |
#   |------------------|-----------------|
#   | Pilot revenue    | **25 %**        |
#
# Returns a list of {label, percent} dicts. Tolerates header variation.

_RATE_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_rate_table(md: str) -> list[dict]:
    rates: list[dict] = []
    in_table = False
    saw_header = False
    for raw in md.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            in_table = False
            saw_header = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not saw_header:
            joined = " ".join(cells).lower()
            if "commission" in joined and "%" in raw or "commission rate" in joined or "rate" in joined and "revenue" in joined:
                saw_header = True
                in_table = True
            continue
        # Skip the |---|---| separator row
        if all(set(c) <= set("-: ") for c in cells if c):
            continue
        if in_table and len(cells) >= 2:
            label = cells[0]
            pct_match = _RATE_PCT.search(cells[1])
            if pct_match:
                rates.append({"label": label, "percent": float(pct_match.group(1))})
    return rates


# ── Signing ──────────────────────────────────────────────────────────────

def get_signatures(bullpen: str, rep: str) -> list[dict]:
    out = []
    d = _sig_dir(bullpen, rep)
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            continue
    return out


def is_current_signature(bullpen: str, rep: str, doc: str) -> Optional[dict]:
    """Returns the latest signature on `doc` IF its doc_sha256 matches the
    live doc content. Otherwise returns None."""
    live = get_doc(bullpen, doc)
    if not live:
        return None
    sigs = [s for s in get_signatures(bullpen, rep) if s.get("doc") == live["id"]]
    if not sigs:
        return None
    latest = sorted(sigs, key=lambda s: s.get("signed_at", ""))[-1]
    if latest.get("doc_sha256") == live["sha256"]:
        return latest
    return None


def sign(bullpen: str, rep: str, doc: str, typed_name: str) -> dict:
    """Rep types their name → record signature. Binds to the current doc sha256."""
    live = get_doc(bullpen, doc)
    if not live:
        raise ValueError("doc_not_found")
    if not typed_name or not typed_name.strip():
        raise ValueError("missing_typed_name")

    prior = [s for s in get_signatures(bullpen, rep) if s.get("doc") == live["id"]]
    version = len(prior) + 1
    sig = {
        "rep": rep,
        "doc": live["id"],
        "doc_filename": live["filename"],
        "doc_title": live["title"],
        "doc_sha256": live["sha256"],
        "version": version,
        "typed_name": typed_name.strip(),
        "signed_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    sig_path = _sig_dir(bullpen, rep) / f"{live['id']}-v{version}.json"
    sig_path.write_text(json.dumps(sig, indent=2) + "\n")

    # Update member.signed_docs pointer (deduped on doc id)
    mpath = _members_dir(bullpen) / f"{rep}.json"
    if mpath.exists():
        try:
            member = json.loads(mpath.read_text())
        except Exception:
            member = {}
        sd = member.get("signed_docs") or []
        sd = [s for s in sd if (s.get("doc") if isinstance(s, dict) else s) != live["id"]]
        sd.append({"doc": live["id"], "doc_title": live["title"],
                   "version": version, "signed_at": sig["signed_at"],
                   "doc_sha256": live["sha256"]})
        member["signed_docs"] = sd
        mpath.write_text(json.dumps(member, indent=2) + "\n")

    audit_append(bullpen, rep, "doc_signed",
                 target_type="legal_doc", target_id=live["id"],
                 payload={"doc_title": live["title"], "doc_sha256": live["sha256"],
                          "version": version, "typed_name": typed_name.strip()})
    return sig


# ── Template rendering (Phase 0.5) ───────────────────────────────────────
#
# Pull a template from templates/legal/, substitute {{vars}} from
# entity.template_vars(bullpen) + a caller-supplied per-render vars dict,
# write the rendered Markdown to bullpens/<slug>/legal/<id>.md, and
# return the {id, sha256, body_md, ...} record so the renderer can chain
# into the signing flow.
#
# Substitution is Mustache-style {{var}} or {{var|default}}.
# Unresolved {{var}} stays literal so failures are visible in the
# rendered doc (better than silently dropping the var).

_VAR_RX = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)(?:\s*\|\s*([^}]*?))?\s*\}\}")

TEMPLATE_DIR = REPO / "templates" / "legal"


def _substitute(text: str, vars_dict: dict) -> str:
    """{{var}} or {{var|default}} substitution. Unknown vars stay literal."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        default = m.group(2)
        if key in vars_dict and vars_dict[key] not in (None, ""):
            return str(vars_dict[key])
        if default is not None:
            return default.strip()
        return m.group(0)   # keep literal so missing vars are visible
    return _VAR_RX.sub(repl, text)


def render_from_template(
    bullpen: str,
    *,
    template: str,
    extra_vars: Optional[dict] = None,
    actor: str = "operator",
) -> dict:
    """Render templates/legal/<template>.md to bullpens/<slug>/legal/<template>.md
    with operator + caller-supplied substitutions applied.

    Raises if the operator entity isn't set up (no vars to substitute).
    Returns the same shape as get_doc().
    """
    from entity import template_vars as _entity_vars, is_setup as _entity_is_setup

    if not _entity_is_setup(bullpen):
        raise ValueError("operator_entity_not_set_up — set up entity before rendering legal docs")

    src = TEMPLATE_DIR / f"{template}.md"
    if not src.exists():
        raise FileNotFoundError(f"template not found: {template}.md")

    raw = src.read_text(encoding="utf-8")
    vars_dict = dict(_entity_vars(bullpen))
    if extra_vars:
        vars_dict.update(extra_vars)
    # The `{{document_sha256}}` placeholder is intentionally NOT
    # substituted at render time — the SHA of the rendered body is
    # what the signature record binds to, and the live SHA changes
    # every time we'd substitute the SHA back in. The placeholder
    # stays literal in the rendered doc; the signature record holds
    # the canonical SHA. This avoids the chicken-and-egg cycle.
    body = _substitute(raw, vars_dict)
    body_sha = _sha256(body)

    out = _doc_path(bullpen, template)
    out.write_text(body, encoding="utf-8")

    audit_append(bullpen, actor, "doc_rendered",
                 target_type="legal_doc", target_id=template,
                 payload={"template": template, "doc_sha256": body_sha})

    return get_doc(bullpen, template)


# ── Member-signature surface (Phase 0.5 gate hook) ───────────────────────

def get_member_signatures(bullpen: str, rep: str) -> dict[str, dict]:
    """Return {doc_id: {version, signed_at, doc_sha256, current}} for
    every doc the rep has ever signed. `current` is True iff doc_sha256
    still matches the live template — used by gates.can_claim_live_prospect.

    Defensive: returns {} if there's no signature dir or the dir is empty.
    """
    out: dict[str, dict] = {}
    d = _sig_dir(bullpen, rep)
    if not d.exists():
        return out

    for f in sorted(d.glob("*.json")):
        try:
            sig = json.loads(f.read_text())
        except Exception:
            continue
        doc_id = sig.get("doc")
        if not doc_id:
            continue
        # Keep the most recent version per doc_id.
        prior = out.get(doc_id)
        if prior and prior.get("version", 0) >= sig.get("version", 0):
            continue
        live = get_doc(bullpen, doc_id)
        current = bool(live and live.get("sha256") == sig.get("doc_sha256"))
        out[doc_id] = {
            "doc": doc_id,
            "version": sig.get("version"),
            "signed_at": sig.get("signed_at"),
            "doc_sha256": sig.get("doc_sha256"),
            "typed_name": sig.get("typed_name"),
            "current": current,
        }
    return out


# ── Dual-signing (operator + closer both sign) ───────────────────────────

def dual_sign(
    bullpen: str,
    *,
    doc: str,
    operator_signer: str,
    operator_typed_name: str,
    closer_rep: str,
    closer_typed_name: str,
    closer_legal_name: str,
) -> dict:
    """Both parties sign a doc that requires it (Closer Agreement, Mutual NDA).

    Records two signatures (one per party) bound to the SAME doc SHA, so
    the dual-signed state can be verified later. The audit chain captures
    both signings as separate events with cross-references.

    Returns {operator_sig, closer_sig, doc_sha256}.
    """
    live = get_doc(bullpen, doc)
    if not live:
        raise ValueError(f"doc_not_found: {doc}")

    # Operator side
    op_sig = sign(bullpen, operator_signer, doc, operator_typed_name)
    # Closer side — but with an extra verifier on the typed name
    if closer_typed_name.strip().lower() != closer_legal_name.strip().lower():
        raise ValueError("closer typed name does not match legal name")
    cl_sig = sign(bullpen, closer_rep, doc, closer_typed_name)

    audit_append(bullpen, "system", "dual_sign",
                 target_type="legal_doc", target_id=doc,
                 payload={
                     "doc_sha256": live["sha256"],
                     "operator_signer": operator_signer,
                     "closer": closer_rep,
                     "closer_legal_name": closer_legal_name,
                 })

    return {
        "doc_sha256": live["sha256"],
        "operator_sig": op_sig,
        "closer_sig": cl_sig,
    }


# ── CLI ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 server/legal.py <bullpen> [doc]")
        sys.exit(0)
    bullpen = sys.argv[1]
    if len(sys.argv) == 2:
        for d in list_docs(bullpen):
            print(f"  {d['id']:30}  {d['sha256'][:10]}  {d['title']}")
    else:
        d = get_doc(bullpen, sys.argv[2])
        if not d:
            print("not found")
            sys.exit(1)
        print(f"{d['title']} — {d['sha256']}")
        print(f"Rates: {d['rates']}")
