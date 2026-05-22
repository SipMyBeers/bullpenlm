"""
Data adapters — pluggable bridges from any external source into the
organizations/ + personas/ file structure.

Each adapter is a self-contained Python module that exports a small set of
functions. The CLI in personas/manage.py routes commands to the right one.

Active adapters:
    website       — single URL → one org
    google_places — location + category → many orgs (needs API key)

Conventions:
    - Adapters write to organizations/<slug>/ — never directly into the
      personas/ store. Calls + people get accumulated under their org over
      time as you actually engage with them.
    - Adapters return a dict with at least { slug, company } so the caller
      can chain operations.
    - Adapters should print human-readable progress to stdout. The CLI
      surfaces this to the user.
"""
