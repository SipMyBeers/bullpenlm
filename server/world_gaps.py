"""World-state gap analyzer — the Minecraft pattern.

The product moment we're enabling: a friend lands on the bullpen for
the first time, sees the world as it is right now — empty pipeline,
no dossiers, no calls logged, no posts published — and immediately
knows what to do without anyone telling them.

The gaps ARE the instructions. Each gap maps to a quest with:
  - id           : stable key (so we can dedupe + claim across sessions)
  - kind         : 'pipeline' | 'dossier' | 'drill' | 'cadence' |
                   'marketing' | 'call' | 'study'
  - title        : 6-word imperative ("Claim a lead", "Drill Marcus")
  - subtitle     : 1-sentence why-it-matters
  - count        : how many of this thing are open (or 0 if just "do
                   the next one")
  - impact       : 'low' | 'mid' | 'high' — what kind of XP it earns
  - xp_estimate  : approximate XP yield (money+clout combined)
  - href         : where the friend should click to do this
  - cta          : button label

The page that consumes this surfaces 6-10 of these at any time,
ranked by impact × scarcity × freshness. Quests can be "claimed" by a
rep (loosely — multiple reps can work the same gap; claim is for
visual ownership only, not exclusion).
"""
from __future__ import annotations
import datetime
import json
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"
ORGS_ROOT = REPO / "organizations"


# ── World-state probes ────────────────────────────────────────────────────

def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _days_ago(iso: str) -> int:
    if not iso:
        return 9999
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", ""))
    except Exception:
        return 9999
    return max(0, (_now() - dt).days)


def _safe(fn, *args, **kwargs):
    """Call a module function, returning [] / 0 on any failure so the
    gap analyzer never crashes the spawn page."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


# ── Gap analyzers ─────────────────────────────────────────────────────────

def _pipeline_gaps(bullpen: str) -> list[dict]:
    """Untouched leads, stale deals, deals stuck in a stage too long."""
    out = []
    try:
        from deals import list_all as deals_list
        deals = deals_list(bullpen) or []
    except Exception:
        return out

    # Untouched: lead-stage deals with no stage_history beyond the initial entry
    untouched = [d for d in deals
                  if d.get("stage") == "lead"
                  and len(d.get("stage_history") or []) <= 1]
    if untouched:
        out.append({
            "id": "claim-untouched-lead",
            "kind": "pipeline",
            "title": "Claim a lead",
            "subtitle": f"{len(untouched)} untouched prospects in the lead stage. First-touch is the highest-leverage action you can take right now.",
            "count": len(untouched),
            "impact": "high",
            "xp_estimate": 50,
            "href": f"/app/deals.html?b={bullpen}&stage=lead",
            "cta": "Pick a lead →",
        })

    # Stale: deals that haven't moved in 14+ days, not closed
    stale_threshold = 14
    stale = []
    for d in deals:
        if d.get("closed_at"): continue
        history = d.get("stage_history") or []
        if not history: continue
        last_move = history[-1].get("at", "")
        if _days_ago(last_move) >= stale_threshold:
            stale.append(d)
    if stale:
        out.append({
            "id": "advance-stale-deals",
            "kind": "pipeline",
            "title": "Advance a stale deal",
            "subtitle": f"{len(stale)} deals haven't moved in 14+ days. They'll die in nurture unless someone touches them.",
            "count": len(stale),
            "impact": "high",
            "xp_estimate": 30,
            "href": f"/app/deals.html?b={bullpen}&filter=stale",
            "cta": "Wake one up →",
        })

    # Pipeline coverage: count by stage and flag empty stages
    by_stage = {}
    for d in deals:
        by_stage[d.get("stage", "lead")] = by_stage.get(d.get("stage", "lead"), 0) + 1
    if not deals:
        out.append({
            "id": "seed-pipeline",
            "kind": "pipeline",
            "title": "Seed the pipeline",
            "subtitle": "Empty bullpen — drop a CSV of prospects to give everyone something to work. HubSpot / Salesforce / Notion exports all work.",
            "count": 0,
            "impact": "high",
            "xp_estimate": 10,
            "href": f"/app/import.html?b={bullpen}",
            "cta": "Import a CSV →",
        })

    return out


def _dossier_gaps(bullpen: str) -> list[dict]:
    """Buyer cards without RAG corpus, or with shallow corpus."""
    out = []
    try:
        from rag import list_buyers
        ragged = list_buyers(bullpen) or []
    except Exception:
        ragged = []

    # Buyer cards on disk
    cards_dir = BULLPENS_ROOT / bullpen / "buyer_cards"
    card_slugs = []
    if cards_dir.exists():
        for f in cards_dir.glob("*.json"):
            card_slugs.append(f.stem)

    rag_map = {b["buyer_slug"]: b["chunks"] for b in ragged}

    # Buyers with zero or very few chunks
    empty_buyers = []
    shallow_buyers = []
    for slug in card_slugs:
        chunks = rag_map.get(slug, 0)
        if chunks == 0:
            empty_buyers.append(slug)
        elif chunks < 5:
            shallow_buyers.append(slug)

    if empty_buyers:
        first = empty_buyers[0]
        out.append({
            "id": f"populate-dossier-{first}",
            "kind": "dossier",
            "title": f"Build the {first} dossier",
            "subtitle": f"AI buyer for {first} has zero source material — its roleplay is generic. Drop a 10-K, LinkedIn export, or news article and it sharpens instantly.",
            "count": len(empty_buyers),
            "impact": "high",
            "xp_estimate": 25,
            "href": f"/app/studio.html?b={bullpen}&buyer={first}",
            "cta": "Drop sources →",
        })

    if shallow_buyers:
        first = shallow_buyers[0]
        out.append({
            "id": f"deepen-dossier-{first}",
            "kind": "dossier",
            "title": f"Deepen the {first} dossier",
            "subtitle": f"Only a handful of chunks on this buyer. Add a transcript, recent press, or peer-firm news — flashcards + briefing get sharper.",
            "count": len(shallow_buyers),
            "impact": "mid",
            "xp_estimate": 15,
            "href": f"/app/studio.html?b={bullpen}&buyer={first}",
            "cta": "Add more sources →",
        })

    return out


def _drill_gaps(bullpen: str, rep: str) -> list[dict]:
    """Buyers no one has drilled against; this rep's cert progress."""
    out = []
    try:
        from audit import iter_all
    except Exception:
        return out

    # Find all drill_passed events
    drill_by_buyer = {}
    rep_drill_attempts = 0
    rep_cert_passes = 0
    for ev in iter_all(bullpen) or []:
        k = ev.get("kind")
        if k == "drill_attempt":
            if ev.get("actor") == rep:
                rep_drill_attempts += 1
        elif k == "drill_passed":
            tier = (ev.get("payload") or {}).get("phase_tier") or 0
            tcs = ev.get("target_id") or ""
            drill_by_buyer[tcs] = drill_by_buyer.get(tcs, 0) + 1
            if ev.get("actor") == rep and tier >= 3:
                rep_cert_passes += 1

    if rep_drill_attempts == 0:
        out.append({
            "id": "first-drill",
            "kind": "drill",
            "title": "Your first drill",
            "subtitle": "You haven't drilled yet. Tier-1 cold open against Marcus Chen — 90 seconds, no risk. The whole game opens up after this.",
            "count": 0,
            "impact": "high",
            "xp_estimate": 10,
            "href": f"/app/spotcheck.html?b={bullpen}&rep={rep}&tcs=cold-open-bfsi",
            "cta": "Start Tier-1 →",
        })
    elif rep_cert_passes == 0:
        out.append({
            "id": "first-cert",
            "kind": "drill",
            "title": "Pass a Tier-3 drill",
            "subtitle": "Cert-tier passes unlock real-prospect dialing. The gatekeeper drill is the canonical one — once you nail it you can claim live work.",
            "count": 0,
            "impact": "high",
            "xp_estimate": 100,
            "href": f"/app/spotcheck.html?b={bullpen}&rep={rep}&tcs=earn-the-room",
            "cta": "Try the cert →",
        })

    # Voice drill — has anyone done one yet?
    voice_dir = BULLPENS_ROOT / bullpen / "voice"
    if not voice_dir.exists() or not any(voice_dir.iterdir()):
        out.append({
            "id": "first-voice-drill",
            "kind": "drill",
            "title": "Try voice mode",
            "subtitle": "Nobody's used the press-to-talk voice drill yet. Cold calling is voice — the AI buyer talks back in their persona's voice.",
            "count": 0,
            "impact": "mid",
            "xp_estimate": 8,
            "href": f"/app/voice.html?b={bullpen}&rep={rep}",
            "cta": "Pick up the phone →",
        })

    return out


def _cadence_gaps(bullpen: str, rep: str) -> list[dict]:
    """Overdue cadence steps assigned to this rep."""
    out = []
    try:
        from cadence import due_steps
        due = due_steps(bullpen, rep=rep, within_hours=72) or []
    except Exception:
        return out
    # Past-due steps
    overdue = []
    for item in due:
        try:
            due_at = datetime.datetime.fromisoformat(item["step"]["due_at"])
            if due_at < _now():
                overdue.append(item)
        except Exception:
            pass
    if overdue:
        first = overdue[0]
        out.append({
            "id": "execute-overdue-cadence",
            "kind": "cadence",
            "title": "Execute an overdue step",
            "subtitle": f"{len(overdue)} cadence steps past due. The deal goes cold every day you skip a touch — clear one now.",
            "count": len(overdue),
            "impact": "mid",
            "xp_estimate": 8,
            "href": f"/app/cadences.html?b={bullpen}&rep={rep}",
            "cta": "See due now →",
        })
    elif due:
        out.append({
            "id": "execute-due-cadence",
            "kind": "cadence",
            "title": "Run a cadence step",
            "subtitle": f"{len(due)} touches due in the next 72h. ✉ Compose drafts the email for you with the dossier baked in.",
            "count": len(due),
            "impact": "low",
            "xp_estimate": 6,
            "href": f"/app/cadences.html?b={bullpen}&rep={rep}",
            "cta": "Get cracking →",
        })
    return out


def _marketing_gaps(bullpen: str, rep: str) -> list[dict]:
    """No posts this week / no marketing clicks logged."""
    out = []
    try:
        from marketing import list_posts, aggregate_stats
        posts = list_posts(bullpen) or []
        stats = aggregate_stats(bullpen) or {}
    except Exception:
        return out

    # Posts this week?
    week_ago = (_now() - datetime.timedelta(days=7)).isoformat()
    fresh_posts = [p for p in posts if (p.get("created_at") or "") >= week_ago]
    fresh_by_rep = [p for p in fresh_posts if p.get("rep") == rep]

    if not posts:
        out.append({
            "id": "first-marketing-post",
            "kind": "marketing",
            "title": "Publish a marketing post",
            "subtitle": "Zero posts tracked yet. One tweet pointing at the product → tracked clicks → if anyone signs up you earn money-XP via attribution.",
            "count": 0,
            "impact": "mid",
            "xp_estimate": 10,
            "href": f"/app/marketing.html?b={bullpen}&rep={rep}",
            "cta": "Mint a tracked link →",
        })
    elif not fresh_by_rep:
        out.append({
            "id": "weekly-marketing-post",
            "kind": "marketing",
            "title": "Post this week",
            "subtitle": "You haven't published anything trackable this week. One post = tiny effort, real outcome-attribution if it converts.",
            "count": 0,
            "impact": "low",
            "xp_estimate": 10,
            "href": f"/app/marketing.html?b={bullpen}&rep={rep}",
            "cta": "Drop a post →",
        })

    return out


def _call_gaps(bullpen: str, rep: str) -> list[dict]:
    """No real calls logged today / this week."""
    out = []
    try:
        from audit import iter_all
    except Exception:
        return out
    today_iso = datetime.date.today().isoformat()
    calls_today = 0
    last_call_iso = ""
    for ev in iter_all(bullpen) or []:
        if ev.get("kind") != "call": continue
        payload = ev.get("payload") or {}
        if (payload.get("call_kind") or "") != "real": continue
        ts = ev.get("ts", "")
        if ts.startswith(today_iso):
            calls_today += 1
        if ts > last_call_iso:
            last_call_iso = ts
    if calls_today == 0:
        days_since = _days_ago(last_call_iso) if last_call_iso else None
        if days_since is None:
            sub = "No real cold calls logged on this bullpen yet. Every recorded call ingests into the dossier and sharpens the next drill."
        elif days_since == 0:
            return out
        elif days_since < 7:
            sub = f"Last real call was {days_since}d ago. Bullpen goes quiet fast — one dial today changes the energy."
        else:
            sub = f"Bullpen hasn't logged a real call in {days_since} days. The whole point of the dossier is to feed back into the next call."
        out.append({
            "id": "log-real-call",
            "kind": "call",
            "title": "Log a real cold call",
            "subtitle": sub,
            "count": 0,
            "impact": "high",
            "xp_estimate": 25,
            "href": f"/app/contact.html?b={bullpen}&rep={rep}",
            "cta": "Open a contact →",
        })
    return out


def _gate_gaps(bullpen: str, rep: str) -> list[dict]:
    """If THIS rep isn't gate-cleared yet, that's their #1 quest."""
    out = []
    try:
        from gates import can_claim_live_prospect
        check = can_claim_live_prospect(bullpen, rep)
    except Exception:
        return out
    if not check.ok and check.missing:
        # Skip operator-side blockers (the operator fixes those, not the closer)
        closer_missing = [m for m in check.missing if m not in (
            "operator_entity_not_set_up", "entity_check_failed",
            "jurisdiction_check_failed", "jurisdiction_check_unavailable",
            "dnc_check_unavailable", "dnc_scrub_failed",
        )]
        if closer_missing:
            out.append({
                "id": "clear-the-gate",
                "kind": "gate",
                "title": "Clear the gate",
                "subtitle": f"{len(closer_missing)} items keep you from real-prospect work: {', '.join(m.replace('_', ' ') for m in closer_missing[:2])}. Onboarding wizard finishes this in 5 min.",
                "count": len(closer_missing),
                "impact": "high",
                "xp_estimate": 0,
                "href": f"/app/onboard/?b={bullpen}&rep={rep}",
                "cta": "Finish onboarding →",
            })
    return out


# ── Aggregator ────────────────────────────────────────────────────────────

IMPACT_WEIGHT = {"high": 3, "mid": 2, "low": 1}


def derive_quests(bullpen: str, rep: str = "self", *, limit: int = 8) -> list[dict]:
    """Run every analyzer + return a ranked list of gap quests."""
    all_quests = []
    for fn in (_gate_gaps, _pipeline_gaps, _dossier_gaps, _drill_gaps,
               _cadence_gaps, _marketing_gaps, _call_gaps):
        try:
            if fn in (_pipeline_gaps, _dossier_gaps):
                all_quests.extend(fn(bullpen))
            else:
                all_quests.extend(fn(bullpen, rep))
        except Exception:
            pass
    # Rank: gate first (always), then impact desc, then by count desc
    def _key(q):
        gate_priority = 0 if q["kind"] == "gate" else 1
        impact_rank = -IMPACT_WEIGHT.get(q.get("impact", "low"), 1)
        count_rank = -int(q.get("count") or 0)
        return (gate_priority, impact_rank, count_rank)
    all_quests.sort(key=_key)
    return all_quests[:limit]


def world_state(bullpen: str, rep: str = "self") -> dict:
    """Full spawn-view: numeric world stats + ranked quests + active reps."""
    stats = {}
    # Deal counts by stage
    try:
        from deals import list_all as deals_list
        deals = deals_list(bullpen) or []
        stats["deals_total"] = len(deals)
        stats["deals_by_stage"] = {}
        for d in deals:
            s = d.get("stage", "lead")
            stats["deals_by_stage"][s] = stats["deals_by_stage"].get(s, 0) + 1
        stats["deals_closed_won"] = sum(1 for d in deals if d.get("stage") == "won")
    except Exception:
        stats["deals_total"] = 0
        stats["deals_by_stage"] = {}
        stats["deals_closed_won"] = 0

    # Real calls
    try:
        from audit import iter_all
        all_events = list(iter_all(bullpen) or [])
        real_calls = [e for e in all_events if e.get("kind") == "call"
                       and (e.get("payload") or {}).get("call_kind") == "real"]
        today_iso = datetime.date.today().isoformat()
        stats["calls_total"] = len(real_calls)
        stats["calls_today"] = sum(1 for c in real_calls if (c.get("ts") or "").startswith(today_iso))
        stats["drills_total"] = sum(1 for e in all_events if e.get("kind") in ("drill_attempt", "drill_passed"))
    except Exception:
        stats["calls_total"] = 0
        stats["calls_today"] = 0
        stats["drills_total"] = 0

    # Marketing
    try:
        from marketing import aggregate_stats
        mk = aggregate_stats(bullpen) or {}
        stats["posts_total"] = mk.get("total", {}).get("posts", 0)
        stats["clicks_total"] = mk.get("total", {}).get("clicks", 0)
        stats["leads_attributed"] = mk.get("total", {}).get("leads", 0)
    except Exception:
        stats["posts_total"] = 0
        stats["clicks_total"] = 0
        stats["leads_attributed"] = 0

    # RAG
    try:
        from rag import list_buyers
        ragged = list_buyers(bullpen) or []
        stats["buyers_with_dossier"] = sum(1 for b in ragged if b["chunks"] > 0)
        stats["chunks_total"] = sum(b["chunks"] for b in ragged)
    except Exception:
        stats["buyers_with_dossier"] = 0
        stats["chunks_total"] = 0

    # Active reps right now
    try:
        from pathlib import Path as _P
        pp = _P(__file__).parent.parent / "bullpens" / bullpen / "presence.json"
        online_reps = []
        if pp.exists():
            data = json.loads(pp.read_text())
            online_reps = [p.get("rep") for p in data.get("online", []) if p.get("rep")]
        stats["online_count"] = len(online_reps)
        stats["online_reps"] = online_reps
    except Exception:
        stats["online_count"] = 0
        stats["online_reps"] = []

    # Recently joined (rep names from member records over last 7 days)
    try:
        from bullpens import get_members
        members = get_members(bullpen) or []
        stats["members_total"] = len(members)
    except Exception:
        stats["members_total"] = 0

    quests = derive_quests(bullpen, rep)
    return {
        "bullpen": bullpen,
        "rep": rep,
        "stats": stats,
        "quests": quests,
        "checked_at": _now().isoformat(timespec="seconds"),
    }
