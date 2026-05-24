"""Classes — pick one at Lvl 5. Each class is a bundle of perks that modify
XP rules + game mechanics. Stored on the member record (`members/<rep>.json`).

Perks are pure functions over the audit event payload, so adding a new class
or tweaking balance doesn't touch xp.py.
"""
from __future__ import annotations
from typing import Optional

CLASSES = {
    "hunter": {
        "id": "hunter",
        "name": "Hunter",
        "tagline": "Cold-call specialist. New logos. First contact.",
        "perks": [
            {"effect": "claim_ttl_days",       "value": 21,
             "label": "Claims hold 21 days (vs 14 default)"},
            {"effect": "xp_multiplier",        "kind": "claim",  "value": 1.20,
             "label": "+20% XP on prospect claims"},
            {"effect": "xp_multiplier",        "kind": "call",   "match": {"call_kind": "real"}, "value": 1.15,
             "label": "+15% XP on real cold calls"},
        ],
        "min_level": 5,
        "color": "#f87171",   # red — the hunter
    },
    "closer": {
        "id": "closer",
        "name": "Closer",
        "tagline": "Moves deals through the late stages. Wins the room.",
        "perks": [
            {"effect": "claim_ttl_days",       "value": 28,
             "label": "Claims hold 28 days"},
            {"effect": "xp_multiplier",        "kind": "deal_stage_moved", "value": 1.15,
             "label": "+15% XP on stage advances"},
            {"effect": "xp_multiplier",        "kind": "deal_closed_won",  "value": 1.20,
             "label": "+20% XP on closed-won deals"},
        ],
        "min_level": 5,
        "color": "#34d399",   # mint — the brand-aligned closer
    },
    "strategist": {
        "id": "strategist",
        "name": "Strategist",
        "tagline": "Sees the whole board. Authors raids. Moves the team.",
        "perks": [
            {"effect": "can_see_bullpen_forecast", "value": True,
             "label": "See bullpen-wide weighted forecast"},
            {"effect": "can_author_quests",        "value": True,
             "label": "Author weekly + raid quests"},
            {"effect": "xp_multiplier",        "kind": "quest_completed", "value": 1.10,
             "label": "+10% XP on quest rewards"},
        ],
        "min_level": 5,
        "color": "#fbbf24",   # gold — the strategist
    },
    "mentor": {
        "id": "mentor",
        "name": "Mentor",
        "tagline": "Onboards new reps. Co-signs deals. Builds the bench.",
        "perks": [
            {"effect": "xp_multiplier",        "kind": "mentor_flag", "value": 1.50,
             "label": "+50% XP for mentoring teammates"},
            {"effect": "co_sign_kickback",     "value": 0.05,
             "label": "5% kickback when a co-signed deal closes"},
            {"effect": "can_recruit",          "value": True,
             "label": "Can generate invites for new reps"},
        ],
        "min_level": 5,
        "color": "#a78bfa",   # purple — the mentor
    },
}


def list_classes() -> list[dict]:
    return list(CLASSES.values())


def get(class_id: str) -> Optional[dict]:
    return CLASSES.get(class_id)


def can_pick(member: dict, class_id: str) -> tuple[bool, str]:
    """Check if a member is eligible to pick a class. Returns (ok, reason)."""
    if class_id not in CLASSES:
        return (False, "unknown_class")
    cls = CLASSES[class_id]
    if (member.get("level") or 1) < cls["min_level"]:
        return (False, f"requires_level_{cls['min_level']}")
    return (True, "ok")


def apply_xp_multiplier(rep_class: Optional[str], event: dict, base_xp: int) -> int:
    """Apply a class-based multiplier to a single XP hit."""
    if not rep_class or rep_class not in CLASSES:
        return base_xp
    multiplier = 1.0
    for perk in CLASSES[rep_class].get("perks", []):
        if perk.get("effect") != "xp_multiplier":
            continue
        if perk.get("kind") and event.get("kind") != perk["kind"]:
            continue
        match = perk.get("match") or {}
        payload = event.get("payload") or {}
        if any(payload.get(k) != v for k, v in match.items()):
            continue
        multiplier *= float(perk.get("value", 1.0))
    return int(round(base_xp * multiplier))


def claim_ttl_days(rep_class: Optional[str]) -> int:
    if not rep_class or rep_class not in CLASSES:
        return 14
    for perk in CLASSES[rep_class].get("perks", []):
        if perk.get("effect") == "claim_ttl_days":
            return int(perk.get("value", 14))
    return 14


def has_perk(rep_class: Optional[str], effect: str) -> bool:
    if not rep_class or rep_class not in CLASSES:
        return False
    for perk in CLASSES[rep_class].get("perks", []):
        if perk.get("effect") == effect and perk.get("value"):
            return True
    return False
