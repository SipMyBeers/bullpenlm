# BullpenLM Platform — Counsel Review

> **Status:** TEMPLATE. Counsel fills this out, saves as
> `docs/legal/COUNSEL_REVIEW.md` (without `.template`), and commits to
> the repo. The Phase 0.5 → Phase 1 gate checks for the non-template
> file's existence.

This is the platform-level counsel review for the BullpenLM software,
not for any individual operator's bullpen. Individual operators with
their own counsel should record their own reviews in their entity
profile (`server/entity.py:record_counsel_review`).

## Reviewing attorney

- **Name:** _________________________________
- **Bar #:** ________________________________
- **State(s) admitted:** _____________________
- **Firm / affiliation:** ____________________
- **Date of review:** ________________________
- **Hours invested:** ________________________

## Scope of review

This review covers the BullpenLM platform's Phase 0.5 mechanics, not
operator-specific implementations.

### Items reviewed

- [ ] **Compensation & legal model doc** — `docs/COMP_AND_LEGAL.md`
- [ ] **Closer Agreement template** — `templates/legal/closer-agreement.md`
- [ ] **Closer Disclosure** — `templates/legal/closer-disclosure.md`
- [ ] **Operator TOS** — `templates/legal/operator-tos.md`
- [ ] **Code of Conduct** — `templates/legal/code-of-conduct.md`
- [ ] **Mutual NDA** — `templates/legal/mutual-nda.md`
- [ ] **DNC Acknowledgement** — `templates/legal/dnc-acknowledgement.md`
- [ ] **Two-ledger XP firewall** — `server/xp.py` (RULES + bucket validator)
- [ ] **Allocation firewall** — `server/gates.py` (EarningInputs)
- [ ] **Classification coach** — `server/classification.py` (IRS 20-factor + state overlays)
- [ ] **Live-work gate** — `server/gates.py:can_claim_live_prospect`
- [ ] **Disclosure & TOS acceptance flow** — `server/disclosures.py`
- [ ] **DNC scrub + TCPA + hours-of-day** — `server/dnc.py`

## Findings

### 1. FTC Koscot / pyramid analysis

Does the platform's compensation mechanic trace earnings exclusively to
product sold to real external customers, or does any path lead to
earnings tied to recruitment / promotion of the opportunity?

**Counsel finding:**

> [Counsel writes finding here. Specifically address: (a) money-XP vs
> clout-XP separation; (b) whether clout-XP can influence prospect
> allocation; (c) whether invite/recruit events award any XP; (d)
> whether commissions tier off recruitment activity. Flag any leak
> paths discovered.]

### 2. Worker classification (1099 vs employee)

Does the Closer Agreement framing hold under federal IRS 20-factor
analysis and the strictest state ABC tests (CA AB5, NJ 75-IIIA)?

**Counsel finding:**

> [Counsel writes finding. Specifically address: (a) the AB5 (B)
> "outside usual business" prong for sales closers dialing for the
> operator's own product; (b) whether the platform's classification
> coach catches the right patterns; (c) any state where the 1099 model
> is fundamentally incompatible.]

### 3. Stripe / payment-processor exposure

Does BullpenLM custody funds at any point, even briefly? Does the
"operator pays closer directly" architecture expose Beers Labs to
money-transmission licensing requirements?

**Counsel finding:**

> [Counsel writes finding.]

### 4. TCPA / Telemarketing Sales Rule posture

Does the operator-certifies-compliance / platform-makes-it-trivial split
hold? Are there scenarios where Beers Labs could be co-liable for an
operator's TCPA violation?

**Counsel finding:**

> [Counsel writes finding.]

### 5. Securities & investment-contract analysis

Is the closer commission anything other than wages-for-work-performed?
Could it be construed as an investment contract (Howey test)? Could the
operator-pays-closer-direct flow be construed as an unregistered
broker-dealer arrangement?

**Counsel finding:**

> [Counsel writes finding.]

### 6. Indemnification, limitation of liability, dispute resolution

Are the operator TOS indemnification, LOL, and dispute clauses
enforceable in operators' likely jurisdictions? Any modifications
needed?

**Counsel finding:**

> [Counsel writes finding.]

### 7. Jurisdictions cleared for use

Of the US states, which can operators safely use BullpenLM in under the
current Phase 0.5 design? Which require additional disclosures or
fundamental adjustments?

**Counsel cleared:** _____________________________________________

**Counsel flagged for caution:** _________________________________

**Counsel cleared with disclaimers:** ____________________________

## Required changes before Phase 1

[Counsel lists any required template or code changes the platform must
make before Phase 1 (signed-binary distribution to non-friends) opens.
Each item gets a checkbox and a rationale.]

- [ ] Required change #1: __________________________________________
  - Why: __________________________________________________________

- [ ] Required change #2: __________________________________________
  - Why: __________________________________________________________

## Recommendations for operators

[Counsel's recommended practices for individual operators using the
platform. Not blocking; advisory.]

- [ ] Recommendation #1: ___________________________________________
- [ ] Recommendation #2: ___________________________________________

## Sign-off

By signing below, I confirm I have reviewed the Phase 0.5 mechanics of
the BullpenLM platform and the above findings reflect my professional
opinion. I am licensed to practice law in the jurisdictions listed
above. This sign-off is not a guarantee of legal sufficiency for any
particular operator's use case; operators should engage their own
counsel for jurisdiction-specific advice.

**Signed:** ______________________________________________________

**Date:** _________________________________________________________

---

*To activate Phase 1 distribution, save this completed file as*
*`docs/legal/COUNSEL_REVIEW.md` and commit to the repo. The platform's*
*pre-flight check looks for that path.*
