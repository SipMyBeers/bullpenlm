"""Shared helpers across adapters."""
from __future__ import annotations
import json
import re
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ORGS_ROOT = Path(__file__).parent.parent / "organizations"

# macOS Python ships without a cert bundle by default — try certifi, then
# fall back to the system trust store. Avoids common "CERTIFICATE_VERIFY_FAILED".
def _ssl_ctx():
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    try:
        # macOS has a usable system cert store at this canonical path
        import os.path
        for p in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl@3/cert.pem",
                  "/opt/homebrew/etc/openssl@3/cert.pem"):
            if os.path.exists(p):
                return ssl.create_default_context(cafile=p)
    except Exception:
        pass
    return ssl.create_default_context()

_SSL = _ssl_ctx()


def slugify(text: str, max_len: int = 48) -> str:
    """URL- and filesystem-safe slug. Drops anything non-alphanum, dedupes hyphens."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "untitled"


def domain_from_url(url: str) -> str:
    """Pull a clean host like 'acme-finance.com' from any URL form."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    return p.netloc.lower().lstrip("www.")


class _TextExtractor(HTMLParser):
    """Strips a page to readable text, dropping script/style/nav/footer noise."""
    SKIP = {"script", "style", "noscript", "svg", "head", "header", "footer", "nav", "form"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth == 0:
            t = data.strip()
            if t:
                self.parts.append(t)

    def text(self) -> str:
        # Collapse whitespace, keep paragraph breaks
        joined = " ".join(self.parts)
        joined = re.sub(r"\s+", " ", joined)
        return joined.strip()


def fetch_page(url: str, timeout: int = 15) -> str:
    """Plain HTTP GET, returns extracted text. Tries https://<host> then
    https://www.<host> automatically since enterprise sites split content
    between bare and www subdomains (Citigroup, Centene, etc. all 404 on bare)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {
        # Enterprise sites (Allstate, big banks) often serve blank shells to
        # obvious bot UAs. Use a realistic Chrome string so we get actual HTML.
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Try the requested URL first; if it returns less than 200 chars of
    # extracted text (anti-bot shell or 404 page), retry with the www variant.
    candidates = [url]
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.hostname and not parsed.hostname.startswith("www."):
        with_www = url.replace(parsed.hostname, "www." + parsed.hostname, 1)
        candidates.append(with_www)

    last_err = None
    for candidate in candidates:
        try:
            req = urllib.request.Request(candidate, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
                raw = r.read().decode("utf-8", errors="ignore")
            ex = _TextExtractor()
            ex.feed(raw)
            text = ex.text()
            if len(text) >= 200:
                return text
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return ""


def ollama_extract(prompt: str, schema_hint: str = "", model: str = "gemma2:9b") -> dict:
    """Send a prompt to local Ollama, parse JSON from the response.

    schema_hint is the JSON shape we want — appended to the user prompt so
    Gemma understands the expected structure. We do best-effort JSON parsing:
    strip code fences, find the first {...} block.
    """
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You output ONLY valid JSON. No prose, no markdown, no explanations. Just the JSON object."},
            {"role": "user", "content": prompt + ("\n\nSchema:\n" + schema_hint if schema_hint else "")},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except Exception as e:
        raise RuntimeError(f"Ollama call failed — is `ollama serve` running? ({e})")

    content = data.get("message", {}).get("content", "").strip()
    # Strip code fences if present
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```\s*$", "", content)
    # Find first {...} block
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise RuntimeError(f"Ollama returned no JSON: {content[:200]}")
    return json.loads(m.group(0))


def write_org(slug: str, base: dict, digital: list[str] = None, force: bool = False) -> Path:
    """Write organizations/<slug>/{org.json, digital.md, README}. Idempotent unless force=True."""
    d = ORGS_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    org_path = d / "org.json"
    if org_path.exists() and not force:
        existing = json.loads(org_path.read_text())
        existing.update({k: v for k, v in base.items() if v})
        org_path.write_text(json.dumps(existing, indent=2) + "\n")
    else:
        org_path.write_text(json.dumps(base, indent=2) + "\n")

    if digital:
        digital_path = d / "digital.md"
        # Merge: keep existing lines, dedupe, prepend new
        existing_lines = set()
        if digital_path.exists():
            existing_lines = {ln.strip().lstrip("- ").strip() for ln in digital_path.read_text().splitlines() if ln.strip()}
        new_lines = [ln for ln in digital if ln.strip() and ln.strip() not in existing_lines]
        combined = ["# Digital footprint", ""] + ["- " + ln for ln in (new_lines + sorted(existing_lines))]
        digital_path.write_text("\n".join(combined) + "\n")

    # Per-org subdirs
    for sub in ("people", "calls", "deals"):
        (d / sub).mkdir(exist_ok=True)
    return d
