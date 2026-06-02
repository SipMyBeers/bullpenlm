"""Bullpen — the top-level tenant. Every other primitive (claims, deals,
members, quests, legal docs, signatures) scopes to one bullpen.

A bullpen IS a folder on disk: `bullpens/<slug>/`. The codebase only ever
operates on "the active bullpen for this request" — resolved by the
middleware before handlers run.

CLI:
  python3 server/bullpens.py create --slug killsesh --founder beers --product KillSesh
  python3 server/bullpens.py list
  python3 server/bullpens.py get killsesh
"""
from __future__ import annotations
import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Optional

from paths import DATA_DIR as REPO
BULLPENS_ROOT = REPO / "bullpens"
SALES_TEMPLATE = REPO / "sales"

BULLPENS_ROOT.mkdir(exist_ok=True)


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,38}[a-z0-9]$")


def _bullpen_dir(slug: str) -> Path:
    return BULLPENS_ROOT / slug


def _bullpen_json(slug: str) -> Path:
    return _bullpen_dir(slug) / "bullpen.json"


def list_bullpens() -> list[dict]:
    """Return the manifest of every bullpen on this host."""
    out = []
    if not BULLPENS_ROOT.exists():
        return out
    for d in sorted(BULLPENS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        manifest = d / "bullpen.json"
        if manifest.exists():
            try:
                out.append(json.loads(manifest.read_text()))
            except Exception:
                continue
    return out


def get_bullpen(slug: str) -> Optional[dict]:
    p = _bullpen_json(slug)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def exists(slug: str) -> bool:
    return _bullpen_json(slug).exists()


def create_bullpen(slug: str, founder_rep: str, product: str = "",
                   name: Optional[str] = None,
                   seed_legal: bool = True) -> dict:
    """Scaffold a new bullpen on disk + return its manifest."""
    slug = slug.strip().lower()
    founder_rep = founder_rep.strip()
    if not SLUG_RE.match(slug):
        raise ValueError(f"slug must be 3-40 chars, [a-z0-9-], got: {slug!r}")
    if not founder_rep:
        raise ValueError("founder_rep required")
    if exists(slug):
        raise ValueError(f"bullpen '{slug}' already exists")

    d = _bullpen_dir(slug)
    for sub in ("claims", "invites", "invites/used", "members", "pipelines",
                "deals", "quests", "quests/progress", "achievements",
                "commissions", "legal", "signatures", "trophies"):
        (d / sub).mkdir(parents=True, exist_ok=True)

    # Seed legal docs from the master template at sales/.
    # As of v0.2 these are *rendered* through the same {{var}} engine as
    # the email templates so the resulting agreement reflects this bullpen's
    # brand_name / commission_rate / founder. Founders still need to fill
    # in `[FILL IN: …]` markers for jurisdiction/entity-specific info.
    template_version = "0"
    if seed_legal and SALES_TEMPLATE.exists():
        try:
            from email_templates import _sub as _render_vars  # type: ignore
        except Exception:
            _render_vars = None
        # Variables passed into the legal-template renderer below. Pulled
        # again from the manifest we're about to write so the very first
        # render reflects the just-constructed manifest.
        render_vars = {
            "brand_name": name or slug,
            "product": product,
            "founder_display_name": "",  # populated by set_bullpen_config later
            "commission_rate": "",
            "commission_tiers_section": "",
            "commission_window_months": "24",
            "company_entity": "",
            "company_entity_type": "",
            "founder_title": "Operator",
            "jurisdiction_state": "",
            "jurisdiction_county": "",
        }
        for md in SALES_TEMPLATE.glob("*.md"):
            raw = md.read_text()
            if _render_vars:
                rendered = _render_vars(raw, render_vars)
            else:
                rendered = raw
            (d / "legal" / md.name).write_text(rendered)
        sha = __import__("hashlib").sha256()
        for md in sorted(SALES_TEMPLATE.glob("*.md")):
            sha.update(md.read_bytes())
        template_version = sha.hexdigest()[:12]

    manifest = {
        "slug": slug,
        "name": name or slug.replace("-", " ").title(),
        "founder_rep": founder_rep,
        "product": product,
        "public_url": "",
        "brand": {"logo": "", "color": ""},
        "feature_flags": {
            "transparency_commissions": "members",  # members | founder-only
            "transparency_legal": "members",
            "transparency_audit": "members",
            "public_roster": False,
        },
        "template_version": template_version,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    _bullpen_json(slug).write_text(json.dumps(manifest, indent=2) + "\n")

    # Genesis audit entry — establishes the chain head for this bullpen.
    from audit import append as audit_append
    audit_append(slug, founder_rep, "bullpen_created",
                 target_type="bullpen", target_id=slug,
                 payload={"product": product, "name": manifest["name"]})

    # Bootstrap the founder as a member
    write_member(slug, founder_rep, role="founder")

    return manifest


def render_legal_docs(slug: str) -> int:
    """Re-render every legal .md in bullpens/<slug>/legal/ from the master
    template at sales/, substituting variables from the current bullpen
    config. Called after set_bullpen_config so the rendered agreement
    reflects the operator's final commission/brand/founder details.
    Returns the number of files rendered.
    """
    if not SALES_TEMPLATE.exists():
        return 0
    cfg = get_bullpen(slug) or {}
    try:
        from email_templates import _sub as _render_vars
    except Exception:
        return 0

    # Build commission_tiers_section block from the tier rules string if present
    tier_rules = (cfg.get("commission_tiers") or "").strip()
    tiers_section = ""
    if tier_rules:
        tiers_section = ("\n**Tiered commission structure**\n\n"
                          + tier_rules.replace("\n", "\n\n")
                          + "\n\nThe Rep advances through tiers automatically as the"
                            " Rep's recorded XP and closes on the Company's CRM hit"
                            " each tier threshold. The Company's CRM record is the"
                            " source of truth for tier eligibility.\n")

    founder_name = (cfg.get("founder_display_name")
                    or cfg.get("founder_rep") or "").strip()
    company_entity = (cfg.get("company_entity") or "").strip()
    # company_display: legal-entity name if set, else "Founder Name (sole proprietor)"
    if company_entity:
        company_display = company_entity
    elif founder_name:
        company_display = f"{founder_name} (sole proprietor)"
    else:
        company_display = "YOU"

    # Human-readable payout list for the legal doc. Stored as a comma-
    # separated string of short codes; expand into proper labels here.
    payout_codes = (cfg.get("payout_methods") or "").split(",")
    payout_label_map = {
        "stripe":   "Stripe", "paypal": "PayPal", "wise": "Wise",
        "ach":      "ACH / bank transfer", "venmo": "Venmo",
        "cashapp":  "Cash App", "usdc": "USDC", "btc": "BTC",
        "eth":      "ETH", "check": "paper check",
    }
    payout_labels = [payout_label_map.get(c.strip(), c.strip())
                     for c in payout_codes if c.strip()]
    payout_methods_display = ", ".join(payout_labels) if payout_labels else ""
    vars_d = {
        "brand_name": cfg.get("name") or slug,
        "product": cfg.get("product") or "",
        "founder_display_name": founder_name,
        "founder_title": "Operator",
        "commission_rate": cfg.get("commission_rate") or "",
        "commission_tiers_section": tiers_section,
        "commission_window_months": str(cfg.get("commission_window_months") or "24"),
        "company_entity": company_entity,
        "company_display": company_display,
        "company_entity_type": cfg.get("company_entity_type") or "",
        "jurisdiction_state": cfg.get("jurisdiction_state") or "",
        "jurisdiction_county": cfg.get("jurisdiction_county") or "",
        "payout_methods_display": payout_methods_display,
    }
    legal_dir = _bullpen_dir(slug) / "legal"
    legal_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for md in SALES_TEMPLATE.glob("*.md"):
        rendered = _render_vars(md.read_text(), vars_d)
        (legal_dir / md.name).write_text(rendered)
        n += 1
    return n


def write_member(bullpen: str, rep: str, role: str = "rep") -> dict:
    """Idempotently create/update a member record for a rep in a bullpen."""
    m_path = _bullpen_dir(bullpen) / "members" / f"{rep}.json"
    if m_path.exists():
        try:
            data = json.loads(m_path.read_text())
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("rep", rep)
    data.setdefault("joined_at", datetime.datetime.now().isoformat(timespec="seconds"))
    data["role"] = data.get("role") or role
    data.setdefault("class", None)
    data.setdefault("level", 1)
    data.setdefault("xp", 0)
    data.setdefault("signed_docs", [])
    data.setdefault("status", "active")
    m_path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def set_bullpen_config(bullpen: str, updates: dict) -> Optional[dict]:
    """Patch the bullpen.json with founder-controlled settings.
    Only allow-listed fields are writable."""
    ALLOWED = {"name", "product", "public_url", "discord_invite",
               "access_mode", "price_usd", "tagline", "brand",
               "commission_rate", "seats_open", "founder_display_name",
               "github_repo", "brand_domain", "brand_sending_email",
               "brand_reply_to", "brand_logo_url",
               "commission_tiers", "company_entity", "company_entity_type",
               "jurisdiction_state", "jurisdiction_county",
               "host_location", "payout_methods",
               "profile",  # {mode: solo|team, industry: software|services|local|...}
               "webhooks"}  # {discord_wins_url, ...}
    VALID_ACCESS = {"public", "invite_only", "paid"}
    p = _bullpen_json(bullpen)
    if not p.exists():
        return None
    try: cfg = json.loads(p.read_text())
    except Exception: return None
    for k, v in (updates or {}).items():
        if k not in ALLOWED:
            continue
        if k == "access_mode" and v not in VALID_ACCESS:
            continue
        if k == "price_usd":
            try: v = float(v)
            except Exception: continue
        cfg[k] = v
    cfg["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def set_profile(bullpen: str, rep: str, display_name: Optional[str] = None,
                avatar: Optional[str] = None, title: Optional[str] = None) -> Optional[dict]:
    """Update the public-facing profile fields on a member record."""
    m_path = _bullpen_dir(bullpen) / "members" / f"{rep}.json"
    if not m_path.exists():
        return None
    try:
        data = json.loads(m_path.read_text())
    except Exception:
        return None
    if display_name is not None:
        data["display_name"] = display_name.strip()[:48]
    if avatar is not None:
        # Cap to one grapheme-ish — emoji can be 1-4 chars; we just trim hard.
        data["avatar"] = avatar.strip()[:8]
    if title is not None:
        data["title"] = title.strip()[:48]
    data["profile_updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    m_path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def get_member(bullpen: str, rep: str) -> Optional[dict]:
    p = _bullpen_dir(bullpen) / "members" / f"{rep}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_members(bullpen: str) -> list[dict]:
    d = _bullpen_dir(bullpen) / "members"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            continue
    return out


def is_member(bullpen: str, rep: str) -> bool:
    return get_member(bullpen, rep) is not None


def resolve_active_bullpen(url_path: str, cookie_bullpen: Optional[str],
                            memberships: list[str]) -> Optional[str]:
    """Pick the active bullpen for the current request:
      1. URL prefix /b/<slug>/...  (preferred, explicit)
      2. cookie 'bullpen-active=<slug>'
      3. If user has exactly 1 membership, use it
      4. Else None (caller renders a switcher)
    """
    m = re.match(r"^/b/([a-z0-9][a-z0-9\-]{1,38}[a-z0-9])(/|$)", url_path)
    if m and exists(m.group(1)):
        return m.group(1)
    if cookie_bullpen and exists(cookie_bullpen):
        return cookie_bullpen
    if len(memberships) == 1 and exists(memberships[0]):
        return memberships[0]
    return None


def memberships_for_rep(rep: str) -> list[str]:
    """Every bullpen this rep is a member of."""
    out = []
    for b in list_bullpens():
        if is_member(b["slug"], rep):
            out.append(b["slug"])
    return out


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a new bullpen")
    p_create.add_argument("--slug", required=True)
    p_create.add_argument("--founder", required=True, help="Rep name of the founder")
    p_create.add_argument("--product", default="", help="What this bullpen sells")
    p_create.add_argument("--name", default=None, help="Display name (default: title-case of slug)")
    p_create.add_argument("--no-seed-legal", action="store_true")

    sub.add_parser("list", help="List bullpens on this host")

    p_get = sub.add_parser("get", help="Show one bullpen's manifest")
    p_get.add_argument("slug")

    p_member = sub.add_parser("add-member", help="Add a member to a bullpen")
    p_member.add_argument("bullpen")
    p_member.add_argument("rep")
    p_member.add_argument("--role", default="rep")

    args = ap.parse_args()

    if args.cmd == "create":
        try:
            m = create_bullpen(args.slug, args.founder, args.product,
                                args.name, seed_legal=not args.no_seed_legal)
            print(f"✓ Created bullpen '{m['slug']}' founded by {m['founder_rep']}")
            print(f"  Folder: bullpens/{m['slug']}/")
            print(f"  Legal template version: {m['template_version']}")
        except ValueError as e:
            print(f"× {e}"); sys.exit(1)
    elif args.cmd == "list":
        bs = list_bullpens()
        if not bs:
            print("No bullpens. Create one with: bullpens.py create --slug X --founder Y")
            sys.exit(0)
        for b in bs:
            members = len(list_members(b["slug"]))
            print(f"  {b['slug']:24}  founder={b['founder_rep']:12}  members={members}  {b.get('product','')}")
    elif args.cmd == "get":
        m = get_bullpen(args.slug)
        if not m:
            print(f"× no bullpen '{args.slug}'"); sys.exit(1)
        print(json.dumps(m, indent=2))
    elif args.cmd == "add-member":
        m = write_member(args.bullpen, args.rep, role=args.role)
        print(f"✓ {args.rep} added to {args.bullpen} as {m['role']}")
