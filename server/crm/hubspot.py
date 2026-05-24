"""HubSpot OAuth + sync — pulls contacts/companies/deals into the BullpenLM org graph.

Setup (one-time, you do this):
  1. Sign in at developers.hubspot.com → Apps → Create app
  2. Auth tab → set redirect URL to http://localhost:7878/api/crm/hubspot/callback
  3. Add scopes: crm.objects.contacts.read, crm.objects.companies.read,
     crm.objects.deals.read (plus the corresponding .write scopes if you want
     BullpenLM to push call-notes back into HubSpot later)
  4. Copy the Client ID and Client Secret into ~/.bullpenlm/hubspot.json:
     {"client_id": "...", "client_secret": "...",
      "redirect_uri": "http://localhost:7878/api/crm/hubspot/callback"}
  5. Restart the BullpenLM server
  6. Visit http://localhost:7878/api/crm/hubspot/connect — you'll be sent to
     HubSpot, approve, redirected back. Tokens land in ~/.bullpenlm/hubspot-tokens.json

Then /api/crm/hubspot/sync pulls your CRM in. Re-run anytime; idempotent.
"""
from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".bullpenlm"
CONFIG_FILE = CONFIG_DIR / "hubspot.json"
TOKENS_FILE = CONFIG_DIR / "hubspot-tokens.json"
SCOPES = "crm.objects.contacts.read crm.objects.companies.read crm.objects.deals.read"
AUTH_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"


def _load_config() -> dict | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return None


def _save_tokens(tokens: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tokens["fetched_at"] = int(time.time())
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2) + "\n")
    TOKENS_FILE.chmod(0o600)


def _load_tokens() -> dict | None:
    if not TOKENS_FILE.exists():
        return None
    try:
        return json.loads(TOKENS_FILE.read_text())
    except Exception:
        return None


def build_authorize_url() -> tuple[str, str | None]:
    """Returns (redirect_url, error). Caller redirects the browser to redirect_url
    or surfaces error if config is missing."""
    cfg = _load_config()
    if not cfg:
        return ("", f"Missing HubSpot config at {CONFIG_FILE}. See server/crm/hubspot.py docstring.")
    params = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": SCOPES,
    })
    return (f"{AUTH_URL}?{params}", None)


def exchange_code(code: str) -> dict:
    """Trade an OAuth code for an access+refresh token pair. Persists to disk."""
    cfg = _load_config()
    if not cfg:
        raise RuntimeError(f"Missing HubSpot config at {CONFIG_FILE}")
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "redirect_uri": cfg["redirect_uri"],
        "code": code,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        tokens = json.loads(r.read())
    _save_tokens(tokens)
    return tokens


def _refresh_if_needed() -> str:
    """Returns a valid access token, refreshing if it's within 60s of expiry.
    Raises RuntimeError if no tokens have been fetched yet."""
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("No HubSpot tokens — visit /api/crm/hubspot/connect first")
    expires_at = tokens.get("fetched_at", 0) + tokens.get("expires_in", 0)
    if time.time() < expires_at - 60:
        return tokens["access_token"]
    cfg = _load_config()
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": tokens["refresh_token"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        fresh = json.loads(r.read())
    _save_tokens(fresh)
    return fresh["access_token"]


def _api_get(path: str, params: dict | None = None) -> dict:
    token = _refresh_if_needed()
    url = f"https://api.hubapi.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def sync_to_org_graph() -> dict:
    """Pull all companies + their contacts + deals from HubSpot, write each as
    an org in organizations/. Returns {created, updated, errors}."""
    from adapters._common import slugify, write_org

    created, updated, errors = [], [], []

    # Page through companies
    after = None
    company_count = 0
    while True:
        params = {"limit": 100,
                  "properties": "name,domain,industry,numberofemployees,city,state,phone,description,website"}
        if after:
            params["after"] = after
        try:
            data = _api_get("/crm/v3/objects/companies", params)
        except Exception as e:
            errors.append(f"company-page fetch: {e}")
            break

        for co in data.get("results", []):
            props = co.get("properties", {})
            name = props.get("name") or props.get("domain")
            if not name:
                continue
            slug = slugify(name)
            org = {
                "slug": slug,
                "company": name,
                "hq": ", ".join(filter(None, [props.get("city"), props.get("state")])) or "(unknown)",
                "size": props.get("numberofemployees") or "(unknown)",
                "phone": props.get("phone") or "(unknown)",
                "web": props.get("domain") or "(unknown)",
                "industry": props.get("industry") or "",
                "what": (props.get("description") or "")[:280] or f"{props.get('industry', '')} company",
                "zone": "end",
                "source": "hubspot",
                "hubspot_id": co.get("id"),
            }
            try:
                d = write_org(slug, org, digital=[f"hubspot company id: {co.get('id')}"])
                (created if not (d / "people").iterdir() else updated).append(slug)
                company_count += 1
            except Exception as e:
                errors.append(f"{slug}: {e}")

        paging = data.get("paging", {}).get("next", {}).get("after")
        if not paging:
            break
        after = paging

    return {
        "synced_companies": company_count,
        "created": list(set(created)),
        "updated": list(set(updated)),
        "errors": errors,
    }


def status() -> dict:
    """Inspect connection state without making an API call."""
    cfg = _load_config()
    tokens = _load_tokens()
    return {
        "configured": cfg is not None,
        "config_path": str(CONFIG_FILE),
        "connected": tokens is not None,
        "tokens_path": str(TOKENS_FILE) if tokens else None,
        "expires_at": (tokens.get("fetched_at", 0) + tokens.get("expires_in", 0)) if tokens else None,
        "scopes_requested": SCOPES.split(),
    }
