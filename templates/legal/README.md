# Legal Templates — Phase 0.5 Skeleton

These templates back the Phase 0.5 firewall. They render with operator
+ closer substitutions from `server/entity.py` and the signing flow in
`server/legal.py` / `server/disclosures.py`.

| Template | Who reads / signs | Purpose |
|---|---|---|
| `closer-agreement.md` | Operator + Closer | The 1099 independent-contractor agreement. The actual contract between operator and closer. BullpenLM is not a party. |
| `closer-disclosure.md` | Closer (click-through before signing the Closer Agreement) | "BullpenLM is software, not your employer. Remedy for non-payment runs to the operator, not the platform." Required before live work. |
| `operator-tos.md` | Operator (click-through during onboarding) | "You are the counterparty, you carry the legal/tax/compliance burden, the platform refuses to mediate." Required before inviting closers. |
| `code-of-conduct.md` | Closer (Exhibit A of the Closer Agreement) | Behavioral expectations. Attached to and incorporated into every Closer Agreement. |
| `mutual-nda.md` | Operator + Closer | Mutual confidentiality. Standard 3-year term. |
| `dnc-acknowledgement.md` | Closer (signed once before first real call) | TCPA / DNC / hours-of-day / two-party-consent compliance. Personal liability acknowledgement. |

## Status

**ALL TEMPLATES ARE WORKING DRAFTS — AWAITING COUNSEL REVIEW.**

The platform's `gates.can_claim_live_prospect()` will refuse to grant
live-work eligibility for any closer until `docs/legal/COUNSEL_REVIEW.md`
exists in the repo, indicating that an attorney has reviewed:

1. The Closer Agreement template
2. The Operator TOS
3. The Closer Disclosure
4. The DNC Acknowledgement
5. The platform's XP mechanics (`server/xp.py`)
6. The allocation firewall (`server/gates.py`)
7. The classification coach (`server/classification.py`)

Counsel sign-off lands as `docs/legal/COUNSEL_REVIEW.md` with date,
attorney name, bar #, jurisdictions reviewed, and any caveats.

## Substitution variables

Templates use `{{double-brace}}` substitution. Standard vars resolved by
`entity.template_vars(bullpen)`:

- `{{operator_entity}}` — operator's legal name
- `{{operator_entity_kind}}` — "limited liability company" / "sole proprietorship" / "individual"
- `{{operator_address}}` — full address
- `{{operator_state}}` — 2-letter state code
- `{{operator_jurisdiction}}` — US-XX (governing law)
- `{{operator_email}}`, `{{operator_phone}}`

Per-closer / per-signing vars resolved by the rendering call site:

- `{{closer_legal_name}}`
- `{{closer_address}}`
- `{{closer_first_name}}`
- `{{signed_date}}`
- `{{commission_pct}}`
- `{{payment_days}}`
- `{{payment_rail}}`
- `{{notice_days}}`
- `{{posttermination_window}}`
- `{{chargeback_window}}`
- `{{nonsolicit_months}}`
- `{{services_scope}}`
- `{{operator_signer_name}}`, `{{operator_signer_title}}`
- `{{document_sha256}}` — set by the renderer right before output
- `{{disclosure_version}}` / `{{tos_version}}`

## What this skeleton is NOT

- Not a substitute for legal advice. Templates are starting points.
- Not customized per jurisdiction yet. Counsel review will surface
  state-specific changes.
- Not internationalized. US-only in Phase 0.5.
- Not e-signature integrated with DocuSign / HelloSign. The platform's
  internal signing flow (typed name + HMAC of doc SHA) is sufficient
  for now; integrating with a major e-sign service is Phase 1 work if
  operators want it.
