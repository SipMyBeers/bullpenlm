# BullpenLM — Compensation, Counterparty & Legal Model

> **One-line summary:** Beers Labs LLC ships the *tooling*. The operator
> running a bullpen is the contracting party. The closer is the
> operator's 1099 independent contractor. **BullpenLM is on zero
> contracts between them.** The platform helps operators paper, gate,
> and track everything — without becoming a party to anything.

This doc is the canonical model. It exists so counsel has one artifact
to review, so engineers have one source of truth for what the platform
will and will not do, and so an outside reader (regulator, payment
processor, journalist, prospective operator) can read it and understand
the structure in 15 minutes.

If anything in code contradicts this doc, **the doc is wrong or the
code is wrong** — flag it and fix one of them. Both can't be true.

---

## 1. The shape of the business

Two products in one binary:

| Product | What it is | Where it lives | Money flow |
|---|---|---|---|
| **The Sim** | Gamified training: AI buyers, drills, ranks, leaderboards, achievements, PvP duels, cosmetics | Steam (Phase 2+) and the self-hosted Tauri app | Steam sells the game ($19.99 EA → $29.99 1.0). DLC. That's it. |
| **The Floor** | Real CRM, real cold calls, real customers, real commissions paid by real operators to real closers | Self-hosted on the operator's machine, never on Steam | Operator pays closer directly via Stripe/Wise/Zelle/USDC. BullpenLM custodies nothing. |

**The sim is the wedge. The floor is the business.** Both are real to
what they are. They share a binary and a UI shell; they do not share
money flow, contracts, or legal posture.

---

## 2. The three roles

```
┌──────────────────────────┐
│      BEERS LABS LLC      │  ← Platform vendor. Ships the tooling.
│   (BullpenLM platform)   │     On zero closer agreements.
└────────────┬─────────────┘     Operator agrees to BullpenLM TOS.
             │
             │  (Operator TOS — platform vendor relationship)
             │
   ┌─────────▼──────────┐
   │  THE OPERATOR      │  ← Founder of a bullpen.
   │  (e.g. KillSesh =  │     Their LLC / sole prop / individual self.
   │   Beers Labs LLC)  │     Counterparty to every closer in their bullpen.
   └─────────┬──────────┘     Pays commissions directly.
             │
             │  (Closer Agreement — 1099 contractor relationship)
             │
       ┌─────▼──────┐
       │  CLOSER    │  ← 1099 contractor of the operator.
       │  (rep)     │     Earns commission per closed deal.
       └────────────┘     Has remedy against operator (not platform) for non-payment.
```

### Beers Labs LLC (the platform)
- **Ships:** the software. Templates. Audit chain. Classification coach.
  DNC tools. Disclosure flow. Settlement *bookkeeping*.
- **Sells:** the Steam sim ($19.99 EA → $29.99 1.0). Possibly subscription
  tiers later (power features), but never the right to earn.
- **Is on:** the Operator TOS (between platform and operator).
- **Is NOT on:** the Closer Agreement. The W-9. Any payment instrument
  between operator and closer.
- **Holds:** no closer funds, ever. Custodies no commission.

### The Operator
- Could be a real LLC (`Ranger Beers LLC`, `KillSesh Industries LLC`),
  a sole proprietorship, or an individual person.
- **Is on:** the Operator TOS (with platform) AND every Closer Agreement
  in their bullpen (with each of their closers).
- **Pays:** closers directly. Picks the rail (Stripe, Wise, Zelle, USDC,
  paper check — their call). Files 1099-NECs at year end. Carries the
  worker-classification compliance risk in their jurisdiction.
- **Owns:** the customer data, the deals, the CRM. They are the data
  controller for GDPR/CCPA purposes.

### The Closer
- A 1099 independent contractor of the operator's entity.
- **Signs:** the Closer Agreement (with the operator), W-9 (provided to
  the operator), DNC Acknowledgement, Closer Disclosure (acknowledging
  BullpenLM is not their employer).
- **Earns:** commission per the Closer Agreement, paid by the operator
  on the agreed schedule.
- **Remedy:** against the *operator* for non-payment, in the operator's
  jurisdiction. **Not against BullpenLM.** This is disclosed before
  signing.

---

## 3. What the platform DOES

Concrete operational responsibilities of Beers Labs / BullpenLM:

1. **Per-operator entity profile** (`server/entity.py`). Captured during
   bullpen setup. Every legal doc renders with the operator's entity,
   never with "Beers Labs LLC" (unless Beers personally is the
   operator of *that* bullpen).
2. **Document templates + e-sign flow.** Closer Agreement, W-9, Mutual
   NDA, Code of Conduct, DNC Acknowledgement, Closer Disclosure,
   Operator TOS. `{{operator_entity}}` substitution. Renders to PDF,
   SHA-256 hashed, both parties click-sign, signatures hash-chained
   into the audit log. Platform is not a witness, escrow, or notary.
3. **Classification coach** (`server/classification.py`). Asks the
   operator IRS 20-factor + state-aware (CA AB5, NJ 75-IIIA, NY/IL/LA
   Freelance Isn't Free) questions when they set up commission terms.
   If the answers describe an employee, refuses to render a 1099
   agreement and shows them why.
4. **Live-work gate** (`server/gates.py`). A closer cannot claim a real
   prospect until:
   - Signed Closer Agreement on file with both-party hash
   - W-9 on file
   - Drill certification cleared (sim-side proof of competence)
   - Jurisdiction compliance check passed (operator + closer locations
     compatible with the agreement)
   - DNC scrub completed for the target number
5. **DNC + TCPA tooling** (`server/dnc.py`). Scrub against
   donotcall.gov + state DNC lists before claim. Two-party-consent
   recording prompts wired by closer + prospect jurisdiction.
   Hours-of-day enforcement.
6. **Settlement bookkeeping** (`server/commissions.py`, existing).
   Closer logs "deal closed, my cut is $X per agreement." Operator
   confirms or disputes. Both sides hash-chain-logged. When operator
   pays out (on whatever rail), they mark it "paid" with the rail +
   reference. Platform never touches the money. At year-end the audit
   chain *is* the 1099-NEC prep CSV.
7. **Disclosures.** Closer + operator each click through required
   acceptance screens before any live work. Acceptances hash-chained
   into the audit log.
8. **Two-ledger XP firewall** (`server/xp.py`). Money-XP and clout-XP
   are separate buckets. Money-XP is only awarded on closed deals +
   outcome-tagged drill certifications. Clout-XP is awarded for social
   activity, attendance, drill volume. Recruiting another closer
   awards **zero of either**. Leaderboards can show clout-XP for
   vanity; leaderboards cannot route prospects.
9. **Allocation firewall** (`server/team.py`, `server/gates.py`). The
   prospect-claim priority function takes only `money_xp`,
   `drill_certification_score`, and historical `close_rate`. The
   function signature does not accept clout-XP. This is type-system
   enforced.

---

## 4. What the platform DOES NOT do

The platform's refusals are as load-bearing as its responsibilities:

- **Does not custody funds.** Never holds commission money in transit.
- **Does not act as escrow.** If operator and closer dispute a deal,
  the audit chain provides evidence; the platform does not adjudicate.
- **Does not act as the closer's employer.** Closers have no employment
  relationship with BullpenLM. The disclosure says this verbatim and
  the closer clicks through it before signing.
- **Does not mediate disputes.** Closer-vs-operator remedy is between
  them, in the operator's jurisdiction.
- **Does not certify the operator's worker classification.** The
  classification coach refuses obvious-employee patterns; everything
  else is the operator's call, made with their counsel.
- **Does not pay XP for recruiting closers.** Inviting a closer is a
  button. The button does not award money-XP, clout-XP, or anything
  else. Attribution is visible in the audit log for social purposes
  only; it is never an input to commission, allocation, or rank.
- **Does not route prospects by clout.** Clout-XP cannot influence
  prospect claim priority, account assignment, hot-lead routing, or
  any other earning-opportunity allocation. Enforced at the function
  signature level.
- **Does not host the floor on Steam.** Valve will reject real-money
  commission + recruitment commerce. The Steam build is the sim;
  the floor runs on the operator's self-hosted Tauri app, off-Steam.
- **Does not promise specific earnings.** Marketing copy says "real
  commission paid by your operator on the rail they choose," not "earn
  $X/mo." No earnings claims without aggregated audit-chain evidence,
  and even then with full FTC-compliant disclosures.

---

## 5. The XP firewall, in detail

The Koscot/Omnitrition pyramid test is *not* "do you have a multi-level
structure?" It's: **do earnings trace to product sold to real external
customers, or to recruitment + promotion of the opportunity itself?**

BullpenLM's earnings trace exclusively to closed deals with real
external customers. The XP system reinforces this at three layers:

### Layer 1 — the ledger split

Every XP rule entry in `server/xp.py` has a `bucket` field:

| bucket | what earns it | what it does |
|---|---|---|
| `money` | Closed deals (deal_closed_won), drill certifications tagged to real outcomes | Increments commission tier eligibility, claim priority |
| `clout` | Posts, attendance streaks, drill volume, social activity, achievement unlocks | Increments rank, leaderboard position, cosmetics |
| `none` | Inviting a closer, recruiting an operator | Records the action in audit log for attribution. Awards nothing. |

### Layer 2 — the allocation firewall

The prospect-claim priority function in `server/team.py` has this
signature:

```python
def priority(rep: str, candidates: list[str]) -> list[str]:
    """Order claim candidates by earning-relevant factors only.

    Inputs that ARE allowed:  money_xp, drill_cert_score, close_rate
    Inputs that are NOT:      clout_xp, invite_count, post_count, rank
    """
```

The function literally cannot accept clout-XP — there is no parameter
for it. A future contributor cannot accidentally introduce the leak
without changing the signature, and a code review will catch that.

### Layer 3 — no pay for recruitment

Inviting a closer is a button. It calls `invites.create_invite(...)`.
That function does not call `xp.award(...)`. It logs to the audit chain
for attribution, but it does not credit the inviter's money-XP or
clout-XP. Period.

Operators recruiting other operators is also worth zero XP of any kind.
Same rule.

---

## 6. Worker classification — what the coach does

The classification coach (`server/classification.py`) is not a
substitute for legal advice. It exists to catch the obvious-employee
pattern before an operator papers a 1099 they shouldn't.

It asks the IRS 20-factor questions in plain English plus state-specific
overlays:

- **CA — AB5 / ABC test.** Strictest. A worker is presumed employee
  unless (A) free from control, (B) work is outside usual business,
  (C) independently established. If the operator's bullpen sells widgets
  and the closer dials for widgets, (B) is *unmet* by default — the
  coach warns hard.
- **NJ — 75-IIIA ABC test.** Similar to CA, slightly different bar.
- **NY/IL/LA — Freelance Isn't Free Act.** Requires written contract
  for >$800 of work in 120 days; sets payment-timeline rules; private
  right of action for non-payment. Coach makes sure the closer agreement
  meets the threshold and the payment timeline is specified.

If the operator's answers describe control over hours, exclusive
relationship, training-as-onboarding, fixed weekly meetings, or any
other classic employee marker, the coach **refuses to render the 1099
template** and shows them which factors flipped. They can then either
adjust the working relationship (recommended), get counsel and override
(possible, audit-logged), or W-2 the closer outside the platform
(legal but outside our tooling).

---

## 7. Operator TOS — what operators agree to

The Operator TOS (`templates/legal/operator-tos.md`) makes the platform-
vs-counterparty split explicit. Operator agrees to:

1. They are the contracting party on every Closer Agreement in their
   bullpen. BullpenLM is not.
2. They will pay closers directly per the agreed rail. BullpenLM does
   not custody, route, or guarantee funds.
3. They will file 1099-NECs at year-end. Platform provides the CSV;
   operator files.
4. They are responsible for worker-classification compliance in their
   jurisdiction.
5. They are responsible for TCPA / telemarketing / DNC compliance.
   Platform provides the tools; operator certifies compliance.
6. They are responsible for prospect data handling (GDPR / CCPA / state
   privacy laws).
7. They will not use the platform to operate anything resembling an
   unregistered security, MLM, pyramid scheme, or unregistered
   money-transmission service. Platform reserves the right to shut
   their bullpen down for cause.
8. They will obtain their own legal counsel before scaling beyond a
   small friend group (recommended threshold: 5 closers).
9. They indemnify Beers Labs LLC for claims arising from their
   operation of their bullpen.
10. They acknowledge BullpenLM is provided AS IS with no warranty as
    to legal sufficiency of the templates — counsel review is their
    responsibility.

---

## 8. Closer Disclosure — what closers acknowledge before signing

Required click-through before a closer can sign the Closer Agreement
(`templates/legal/closer-disclosure.md`):

> You are about to sign an independent-contractor agreement with
> **{{operator_entity}}**. Read carefully.
>
> 1. **Your contracting party is {{operator_entity}}.** Not BullpenLM.
>    Not Beers Labs LLC. Not the BullpenLM platform.
> 2. **BullpenLM is software.** It is not your employer. It does not
>    pay you. It does not control your hours or work.
> 3. **All commission is paid by {{operator_entity}}** on the rail
>    specified in your agreement. If they do not pay you, your remedy
>    is against {{operator_entity}} in {{operator_jurisdiction}}, not
>    against BullpenLM.
> 4. **You are an independent contractor for tax purposes.** You will
>    receive a 1099-NEC at year-end from {{operator_entity}}. You are
>    responsible for your own income tax, self-employment tax, and any
>    business expenses you incur.
> 5. **Earnings depend on performance.** No specific income is
>    promised. Past performance of other closers does not predict yours.
> 6. **No earnings come from recruiting other closers.** If you bring
>    another closer onto a bullpen, you earn nothing for the referral.
>    Earnings come only from deals you close with real customers.
> 7. **BullpenLM does not warrant the legal sufficiency** of the
>    agreement template. You may wish to have an attorney review it
>    before signing.
> 8. **You may decline to sign** and walk away. No penalty.
>
> By clicking "I understand," you confirm you have read this disclosure.

The click logs a hash-chained entry with closer's identity, timestamp,
disclosure version SHA, and a one-way pointer to it in the closer's
file. The Closer Agreement signing flow refuses to proceed without this.

---

## 9. Counsel review — what we need before Phase 1

Before Phase 1 opens (i.e., before non-friend operators are onboarded
via signed binaries), an MLM/securities + worker-classification attorney
needs to review:

- [ ] **Platform XP mechanics** — the two-ledger split, the allocation
      firewall, the no-pay-for-recruitment rule. Does the structure
      hold under FTC pyramid analysis?
- [ ] **Closer Agreement template** (`templates/legal/closer-agreement.md`)
      — does the 1099 framing hold? Are commission terms enforceable?
      Is the dispute / termination language sound?
- [ ] **Operator TOS** (`templates/legal/operator-tos.md`) — does the
      counterparty-disclaimer hold? Does the indemnification clause
      hold? Are we leaving any platform-as-employer ambiguity?
- [ ] **Closer Disclosure** (`templates/legal/closer-disclosure.md`)
      — is the language sufficient to defeat a future "I thought
      BullpenLM employed me" claim?
- [ ] **Worker classification jurisdictions** — minimum: CA, NJ, NY,
      IL, LA. Validate the coach's warnings; flag jurisdictions where
      the 1099 model is fundamentally incompatible.
- [ ] **TCPA / DNC posture** — operator-certifies vs platform-enforces
      split. Is the operator-certifies model defensible?
- [ ] **Stripe / payment processor exposure** — even though we don't
      custody funds, do we have any Stripe Connect / acquirer exposure
      from operators using Stripe Direct?
- [ ] **Securities posture** — is the closer commission anything other
      than wages-for-work-performed (i.e., is there any way to read it
      as an investment contract)? The answer should be no, but
      confirm.

Counsel sign-off lands as `docs/legal/COUNSEL_REVIEW.md` in the repo,
dated, with attorney name, bar #, jurisdictions reviewed, and any
caveats. This file is a Phase 1 exit-criterion artifact.

---

## 10. What's *not* in this doc

- **Tax mechanics for the operator.** They file 1099-NECs at year-end.
  Their accountant handles it. We provide the CSV.
- **State-by-state legal nuance.** The classification coach handles the
  obvious cases. Operators with closers in multiple states should
  consult counsel.
- **International closers.** Out of scope for Phase 0.5. Add to Phase 1
  build queue: passport-country detection, treaty rate matrix, W-8BEN
  collection. Until then, US-only closers per operator TOS.
- **Securities for the operator's underlying customers.** If
  KillSesh-the-product is selling something that's itself a securities
  instrument (it isn't; KillSesh sells data conversion tooling), that's
  on the operator. Operator TOS prohibits unregistered-securities sales
  via the platform.
- **Anti-money-laundering / KYC.** Out of scope while we don't custody
  funds. Operators picking Stripe/Wise/USDC inherit their providers'
  KYC.

---

## Pointers

- ROADMAP — `ROADMAP.md` (Phase 0.5 ties to this doc)
- XP code — `server/xp.py`
- Allocation code — `server/team.py`, `server/gates.py`
- Entity profile — `server/entity.py`
- Classification coach — `server/classification.py`
- DNC tools — `server/dnc.py`
- Disclosures — `server/disclosures.py`
- Templates — `templates/legal/`
- Counsel sign-off — `docs/legal/COUNSEL_REVIEW.md` (does not exist yet
  — created when counsel signs)
