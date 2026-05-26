"""Email template engine for branded outreach.

Templates are Markdown-ish files with YAML frontmatter. Variable substitution
uses `{{var}}` or `{{var|default}}` syntax. Three lookup tiers:

  1. bullpens/<slug>/email-templates/<name>.md   (per-bullpen override)
  2. templates/email/<name>.md                    (shipped defaults)

When a new bullpen is created the wizard copies the shipped defaults into
the per-bullpen override directory so the founder can edit them inline
without changing the canonical templates.

  render(name, vars, bullpen=None) → {subject, html, text, frontmatter}

  list_available(bullpen=None) → [{name, subject, source}]

The renderer auto-injects bullpen brand variables (brand_name, brand_domain,
founder_display_name, etc.) on top of the user-supplied vars, so a template
can use `{{brand_name}}` without the caller having to thread it through.
"""
from __future__ import annotations
import datetime
import json
import re
import shutil
from html import escape
from pathlib import Path
from typing import Optional

REPO = Path(__file__).parent.parent
BULLPENS_ROOT = REPO / "bullpens"
DEFAULTS_DIR = REPO / "templates" / "email"

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*\|\s*([^}]*?))?\s*\}\}")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _bullpen_dir(slug: str) -> Path:
    return BULLPENS_ROOT / slug / "email-templates"


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Frontmatter is YAML between --- lines."""
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    try:
        import yaml  # type: ignore
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        # Fall back to k:v line parsing if PyYAML missing
        fm = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def _sub(s: str, vars: dict) -> str:
    """Replace `{{name}}` and `{{name|default}}` with vars[name]."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        default = m.group(2) or ""
        val = vars.get(key)
        if val is None or val == "":
            return default
        return str(val)
    return VAR_RE.sub(repl, s)


def _text_to_html(text: str) -> str:
    """Plain text → minimal HTML. Newlines → <br>, blank line → </p><p>.
    Escapes HTML special chars first so users can't smuggle markup."""
    escaped = escape(text)
    # Bold support — **word** → <strong>word</strong>
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    paragraphs = re.split(r"\n\n+", escaped.strip())
    out = []
    for p in paragraphs:
        p = p.replace("\n", "<br>\n")
        out.append(f"<p>{p}</p>")
    return "\n".join(out)


def _find_template(name: str, bullpen: Optional[str]) -> Optional[Path]:
    name = name.replace("..", "").replace("/", "")
    if not name.endswith(".md"):
        name += ".md"
    if bullpen:
        p = _bullpen_dir(bullpen) / name
        if p.exists():
            return p
    p = DEFAULTS_DIR / name
    return p if p.exists() else None


def _bullpen_brand_vars(bullpen: str) -> dict:
    """Pull standard brand vars from the bullpen's config so templates can
    reference {{brand_name}}, {{brand_domain}}, etc. without the caller
    having to thread them."""
    cfg_path = BULLPENS_ROOT / bullpen / "bullpen.json"
    if not cfg_path.exists():
        return {}
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception:
        return {}
    return {
        "brand_name": cfg.get("name") or bullpen,
        "brand_domain": cfg.get("brand_domain") or "",
        "brand_logo_url": cfg.get("brand_logo_url") or "",
        "brand_reply_to": cfg.get("brand_reply_to") or "",
        "brand_sending_email": cfg.get("brand_sending_email") or "",
        "product": cfg.get("product") or "",
        "tagline": cfg.get("tagline") or "",
        "founder_display_name": cfg.get("founder_display_name") or cfg.get("founder_rep") or "",
        "founder_rep": cfg.get("founder_rep") or "",
        "founder_title": cfg.get("founder_title") or "Operator",
        "public_url": cfg.get("public_url") or "",
        "github_repo": cfg.get("github_repo") or "",
        "today": datetime.date.today().isoformat(),
    }


def render(name: str, vars: Optional[dict] = None,
            bullpen: Optional[str] = None) -> dict:
    """Render the named template with vars. Bullpen brand vars are injected
    first; caller's vars win on conflict."""
    path = _find_template(name, bullpen)
    if not path:
        raise FileNotFoundError(f"template '{name}' not found (looked in "
                                 f"{_bullpen_dir(bullpen) if bullpen else '—'} "
                                 f"and {DEFAULTS_DIR})")
    raw = path.read_text()
    fm, body = _split_frontmatter(raw)
    full_vars = {}
    if bullpen:
        full_vars.update(_bullpen_brand_vars(bullpen))
    if vars:
        full_vars.update({k: ("" if v is None else v) for k, v in vars.items()})
    subject = _sub(str(fm.get("subject", "")), full_vars)
    text = _sub(body.strip(), full_vars)
    html = _text_to_html(text)
    return {
        "subject": subject,
        "text": text,
        "html": html,
        "frontmatter": fm,
        "source": str(path.relative_to(REPO)),
    }


def list_available(bullpen: Optional[str] = None) -> list[dict]:
    """List every template available to this bullpen (shipped + overrides)."""
    out: dict[str, dict] = {}
    if DEFAULTS_DIR.exists():
        for p in sorted(DEFAULTS_DIR.glob("*.md")):
            fm, _ = _split_frontmatter(p.read_text())
            out[p.stem] = {
                "name": p.stem,
                "subject": fm.get("subject", ""),
                "summary": fm.get("summary", ""),
                "source": "default",
            }
    if bullpen and _bullpen_dir(bullpen).exists():
        for p in sorted(_bullpen_dir(bullpen).glob("*.md")):
            fm, _ = _split_frontmatter(p.read_text())
            out[p.stem] = {
                "name": p.stem,
                "subject": fm.get("subject", ""),
                "summary": fm.get("summary", ""),
                "source": "override",
            }
    return list(out.values())


def seed_bullpen_templates(slug: str, overwrite: bool = False) -> int:
    """Copy the shipped defaults into bullpens/<slug>/email-templates/
    so the founder can edit them per-bullpen. Returns # copied."""
    dst = _bullpen_dir(slug)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    if not DEFAULTS_DIR.exists():
        return 0
    for p in DEFAULTS_DIR.glob("*.md"):
        target = dst / p.name
        if target.exists() and not overwrite:
            continue
        shutil.copy2(p, target)
        n += 1
    return n


def save_template(slug: str, name: str, body: str) -> Path:
    """Founder edits a template — write it to the per-bullpen override dir."""
    if "/" in name or ".." in name:
        raise ValueError("invalid template name")
    if not name.endswith(".md"):
        name += ".md"
    dst = _bullpen_dir(slug) / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return dst
