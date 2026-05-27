"""Founder quickstart — one command to set up a bullpen ready for friends.

Walks you through entity → classification → TOS in under 60 seconds with
smart defaults. Idempotent: re-running skips steps that are already done.

Usage:
    python3 server/bullpen_quickstart.py [bullpen-slug]

If no slug is provided, defaults to 'default' (matches the dev bullpen).
For a named bullpen like KillSesh, pass 'killsesh' to bind everything
under bullpens/killsesh/.

What it does:
    1. Asks for operator entity info (LLC name, address, EIN, jurisdiction)
       — or skips if entity.json already exists.
    2. Pre-fills the classification questionnaire with the
       contractor-leaning answer for every question (operators using
       this CLI have decided their closers are 1099 — the coach is for
       the UI flow, this is the fast path).
    3. Accepts the operator TOS on your behalf with counsel_consulted=
       false (you can re-accept via the UI after consulting counsel).
    4. Renders all the legal templates so they're ready for closers
       to read.
    5. Prints the magic-link command for inviting friends.

This is intentionally MUCH faster than the UI wizard. The UI exists for
operators onboarding to the platform; this CLI exists for Beers (and
similar bootstrap founders) who already understand the model.
"""
from __future__ import annotations
import getpass
import sys
from pathlib import Path

# Make `server/` importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent))

import entity
import classification
import disclosures
import legal


# ── Tiny terminal helpers ────────────────────────────────────────────────

def _color(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s

def info(msg: str): print(_color(msg, "36"))           # cyan
def ok(msg: str):   print(_color(f"  ✓ {msg}", "32"))  # green
def warn(msg: str): print(_color(f"  ⚠ {msg}", "33"))  # yellow
def err(msg: str):  print(_color(f"  ✗ {msg}", "31"))  # red

def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default

def ask_secret(prompt: str) -> str:
    return getpass.getpass(f"  {prompt}: ").strip()


# ── Steps ────────────────────────────────────────────────────────────────

def step_entity(bullpen: str) -> dict:
    info(f"\n[1/4] Operator entity for {bullpen!r}")
    existing = entity.get_entity(bullpen)
    if existing and entity.is_setup(bullpen):
        ok(f"already set up: {existing['legal_name']} ({existing['jurisdiction']})")
        return existing

    print("  Quick entity setup. EIN is hashed locally — never stored raw.")
    kind = ask("Entity kind (llc/sole_prop/individual)", "llc")
    legal_name = ask("Legal name (e.g. 'KillSesh Industries LLC')")
    if not legal_name:
        err("legal_name required — aborting")
        sys.exit(1)
    street = ask("Street address")
    city = ask("City")
    state = ask("State (2 letters)").upper()[:2]
    postal_code = ask("ZIP")
    contact_email = ask("Contact email")
    if not (street and city and state and postal_code and contact_email):
        err("address + contact email required — aborting")
        sys.exit(1)
    ein = ask_secret("EIN or SSN (hashed locally; press Enter to skip)")

    e = entity.set_entity(
        bullpen,
        kind=kind,
        legal_name=legal_name,
        raw_ein_or_ssn=ein or None,
        address={"street": street, "city": city, "state": state,
                 "postal_code": postal_code, "country": "US"},
        jurisdiction=f"US-{state}",
        contact_email=contact_email,
    )
    ok(f"entity set: {e['legal_name']} ({e['jurisdiction']})")
    return e


def step_classification(bullpen: str, op_state: str) -> dict:
    info(f"\n[2/4] Worker classification (IRS 20-factor)")
    existing = classification.get_answers(bullpen, None)
    if existing and (existing.get("score") or {}).get("verdict") == "contractor":
        ok(f"already classified as Contractor ({existing['score']['total_score']} points)")
        return existing

    print("  Default: contractor-leaning answers (typical for commission-only closer agreements).")
    print("  If your real working relationship differs, re-run the UI questionnaire at")
    print("  /app/setup/?b=" + bullpen + " to answer truthfully — the platform will refuse to")
    print("  render a 1099 template if your real answers describe an employee.")
    confirm = ask("Use contractor-leaning defaults? (y/n)", "y").lower()
    if not confirm.startswith("y"):
        info("  Run /app/setup/ in the browser instead, then re-run quickstart.")
        sys.exit(0)

    answers = {q["id"]: (q["score_yes"] == 1) for q in classification.QUESTIONS}
    rec = classification.save_answers(bullpen, answers=answers, operator_state=op_state)
    if rec["score"]["verdict"] != "contractor":
        err(f"classification rejected: {rec['score']['verdict']}")
        warn("This shouldn't happen with contractor-leaning defaults — check state veto rules.")
        sys.exit(1)
    if op_state == "CA":
        warn("CA AB5 (B) veto fires when closers dial for your usual business — verify your real situation in the UI.")
    ok(f"classified as Contractor (score: {rec['score']['total_score']})")
    return rec


def step_tos(bullpen: str, op_legal_name: str) -> dict:
    info(f"\n[3/4] Operator Terms of Service")
    if disclosures.has_accepted_operator_tos(bullpen):
        ok("already accepted (current SHA)")
        return {"already": True}

    # Render the TOS so it exists for preview
    try:
        legal.render_from_template(bullpen, template="operator-tos")
    except Exception as e:
        warn(f"TOS template render failed: {e}")

    print(f"  By accepting, {op_legal_name} agrees to:")
    print("    - Be the counterparty on every Closer Agreement")
    print("    - Pay closers directly via the rail in each Agreement")
    print("    - File 1099-NECs at year-end")
    print("    - Carry worker-classification + TCPA compliance")
    print("    - BullpenLM is on zero contracts between you and your closers")
    print("    - Full text: templates/legal/operator-tos.md")

    counsel = ask("Have you consulted counsel? (y/n)", "n").lower().startswith("y")
    if not counsel:
        warn("Accepting WITHOUT counsel. See docs/legal/COUNSEL_OUTREACH.md")
        warn("before scaling beyond ~5 closers.")
    sig = ask(f"Type {op_legal_name!r} to accept")
    if sig.strip().lower() != op_legal_name.strip().lower():
        err("typed signature must match operator legal name exactly — aborting")
        sys.exit(1)

    rec = disclosures.accept_operator_tos(
        bullpen,
        "operator",
        operator_legal_name=op_legal_name,
        typed_signature=sig,
        counsel_consulted=counsel,
    )
    ok(f"TOS accepted (SHA {rec['tos_sha256'][:12]}, counsel_consulted={counsel})")
    return rec


def step_render_templates(bullpen: str) -> None:
    info(f"\n[4/4] Pre-rendering legal templates for closers to read")
    for tpl in ("closer-disclosure", "operator-tos", "code-of-conduct",
                "mutual-nda", "dnc-acknowledgement"):
        try:
            legal.render_from_template(bullpen, template=tpl)
            ok(f"rendered {tpl}.md")
        except Exception as e:
            warn(f"{tpl} skipped: {e}")
    print("  closer-agreement.md is rendered per-closer at signing time")
    print("  (extra_vars: closer_legal_name, commission_pct, etc).")


# ── Final invite hint ────────────────────────────────────────────────────

def final_hint(bullpen: str) -> None:
    info(f"\n══════════════════════════════════════════════════════════════")
    info(f"  BULLPEN {bullpen!r} IS READY FOR FRIENDS")
    info(f"══════════════════════════════════════════════════════════════")
    print()
    print("  Next 3 steps:")
    print()
    print("    1. Start the server (if not already running):")
    print("         python3 server/server.py")
    print()
    print("    2. Get your public tunnel URL:")
    print("         tail -f ~/.bullpenlm/cloudflared.log")
    print("       OR check the Host control panel: http://127.0.0.1:7878/app/host.html")
    print()
    print("    3. Generate a magic-link invite for each friend:")
    print(f"         python3 server/invites.py magic-link <friend-name> --bullpen {bullpen}")
    print()
    print("       This prints a SINGLE URL ready to drop in a Discord DM.")
    print("       Friend clicks → onboarding wizard → first drill in 5 minutes.")
    print()
    info("  ────────────────────────────────────────────────────────────")
    info("  Phase 0.5 firewall is active. Closers cannot claim real")
    info("  prospects until they clear: agreement + W-9 + disclosure +")
    info("  cert-tier drill. The platform refuses gracefully — they see")
    info("  exactly what's left.")
    info("  ────────────────────────────────────────────────────────────")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    bullpen = sys.argv[1] if len(sys.argv) > 1 else "default"
    info(f"\nBullpenLM founder quickstart — bullpen={bullpen!r}")
    info(f"This is the fast path. The UI wizard at /app/setup/?b={bullpen}")
    info(f"is the same flow with more handholding.")

    ent = step_entity(bullpen)
    step_classification(bullpen, ent["address"]["state"])
    step_tos(bullpen, ent["legal_name"])
    step_render_templates(bullpen)
    final_hint(bullpen)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        info("aborted — re-run anytime; completed steps stay completed.")
        sys.exit(130)
