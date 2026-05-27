# BullpenLM Operator Terms of Service

> **PLACEHOLDER — awaiting counsel review.** Working draft for the
> Phase 0.5 firewall.

These Terms of Service (the "Terms") apply between Beers Labs LLC,
the maker of the BullpenLM platform ("Beers Labs," "we," "us") and
**{{operator_entity}}** ("Operator," "you"), the operator of a
self-hosted BullpenLM bullpen.

By accepting these Terms, Operator is permitted to run a bullpen,
invite closers, render legal templates, and use the BullpenLM
compliance tools. **Beers Labs is not a party to any agreement
between Operator and Operator's closers.**

---

## 1. Counterparty Relationship

1.1. **You are the counterparty to your closers.** Every Closer
Agreement, every commission payment, every dispute with a closer runs
between you and that closer — not between the closer and BullpenLM.

1.2. **BullpenLM provides tooling.** Templates, audit chain,
classification coach, DNC tools, settlement bookkeeping. We do not
sign your closer agreements. We do not custody commission funds. We
do not adjudicate disputes between you and your closers.

1.3. **You acknowledge that BullpenLM is open-source MIT-licensed
software.** You may run it on your own hardware indefinitely without
ongoing payment to Beers Labs. The Steam-distributed version is a
purchase; the self-hosted server you actually run your bullpen on is
free.

## 2. Your Obligations

You agree, as a condition of running a bullpen:

2.1. **You will pay your closers directly**, on the rail and schedule
specified in each Closer Agreement. BullpenLM does not custody, route,
or guarantee any payment.

2.2. **You will file 1099-NECs** at year-end for any closer you paid
$600 or more during the calendar year. BullpenLM provides a CSV export
of payments; you file the returns.

2.3. **You will obtain your own legal counsel** before scaling beyond
a small friend group (recommended threshold: 5 closers, or
$50,000/year in aggregate commission). The BullpenLM templates are
starting points, not warranties.

2.4. **You will comply with worker-classification law** in your
jurisdiction. BullpenLM's classification coach catches obvious
employee patterns; you are still responsible for the call.

2.5. **You will comply with TCPA, the FTC Telemarketing Sales Rule,
state DNC laws, and recording-consent laws** in every jurisdiction
your closers dial. BullpenLM provides DNC scrub + hours-of-day +
two-party-consent tooling; you certify your use of it.

2.6. **You will comply with applicable privacy law** (CCPA, GDPR,
state laws) regarding the prospect data your bullpen processes. You
are the data controller. We are not.

2.7. **You will not use the platform for**:
- Unregistered securities offerings
- Multi-level marketing schemes
- Pyramid schemes (FTC Koscot/Omnitrition definition)
- Unregistered money-transmission
- Sale of regulated products without applicable license
- Sale of products that are themselves illegal in the closer's or
  customer's jurisdiction

2.8. **You will not modify the platform** to bypass the two-ledger XP
firewall, the no-XP-for-recruitment rule, the allocation firewall
preventing clout-XP from influencing prospect routing, or the
live-work gate (signed agreement + W-9 + drill cert + jurisdiction
check + DNC scrub). If you fork the platform and remove these
guardrails, you do so under the MIT license, but you may not
represent the resulting fork as "BullpenLM" or use the BullpenLM
brand.

## 3. Indemnification

3.1. Operator indemnifies Beers Labs LLC for any third-party claim,
loss, or expense arising from:
- Operator's operation of Operator's bullpen
- Operator's relationship with Operator's closers
- Operator's compliance failures (TCPA, classification, privacy,
  consumer protection)
- Operator's product or services sold via the bullpen
- Operator's use of the platform in violation of §2.7 or §2.8

3.2. This indemnification survives termination of these Terms.

## 4. Disclaimer of Warranties

4.1. **BullpenLM is provided "AS IS."** Beers Labs makes no warranty
that the platform, the legal templates, the classification coach, the
DNC tooling, or any other feature is legally sufficient for your
specific situation.

4.2. **Templates are starting points.** The Closer Agreement, W-9
collection, Mutual NDA, and other templates are drafted to be
reasonable defaults. They require review by counsel licensed in your
jurisdiction before reliance.

4.3. **The classification coach is not legal advice.** It catches
obvious patterns. It is not a substitute for counsel.

4.4. **The audit chain is reliable but not unbreakable.** We use
hash-chained logs to provide tamper evidence. The chain shows
integrity violations after the fact; it does not prevent them at
write time. Operators should maintain off-host backups.

## 5. Limitation of Liability

5.1. To the maximum extent permitted by law, Beers Labs LLC's total
liability for any claim arising from these Terms or the platform is
limited to **the greater of**:
(a) $100, or
(b) the amount Operator has paid Beers Labs for the platform in the
    12 months preceding the claim (which, for self-hosted operators,
    is typically $0).

5.2. Beers Labs is not liable for:
- Loss of profits, revenue, or commission opportunity
- Operator's tax liability
- Operator's disputes with closers
- Operator's disputes with customers
- Any consequential, incidental, or punitive damages

## 6. Term and Termination

6.1. These Terms are effective when Operator accepts them in the
BullpenLM application.

6.2. Either Party may terminate these Terms at any time. Operator may
terminate by ceasing to run a bullpen. Beers Labs may terminate by
publishing a revised version of these Terms or by issuing written
notice to Operator's contact email.

6.3. **Beers Labs reserves the right to refuse, throttle, or sever
service** to any operator we have a good-faith basis to believe is
operating in violation of §2.7 (prohibited uses) or §2.8 (firewall
bypass). For self-hosted operators this means removing the operator
from BullpenLM-hosted directories (Discord, marketing, the
bullpenlm.com landing page), not deactivating the operator's running
binary — we don't have a kill switch in the open-source code, and we
don't intend to add one.

## 7. Open-Source License

7.1. The BullpenLM platform source is released under the MIT License,
available at `https://github.com/SipMyBeers/bullpenlm`. These Terms
apply to your participation in the Beers Labs-hosted ecosystem
(Discord, branding, support channels, the Steam-distributed sim), not
to your right to use the open-source code itself.

## 8. Governing Law

8.1. These Terms are governed by the laws of the State of Oregon,
without regard to conflict-of-law principles.

8.2. Venue for any dispute is the state or federal courts located in
Multnomah County, Oregon.

## 9. Counsel-Consultation Acknowledgement

9.1. By accepting these Terms, you certify ONE of the following:

- **(a)** You have consulted with an attorney regarding the
  obligations and risks under these Terms and your Closer Agreement
  template, **OR**

- **(b)** You expressly waive consultation with counsel and
  acknowledge that you are accepting these obligations and risks
  without legal review.

The platform records which of (a) or (b) you selected in the audit
chain.

## 10. Amendments

10.1. We may revise these Terms. Material revisions require Operator
to re-accept the revised Terms before continuing to operate.

10.2. Material revisions trigger a "current Terms SHA" change. If the
SHA in your audit log does not match the current Terms SHA, the
platform prompts you to re-accept on next launch.

---

## Acceptance

By typing my operator legal name below and clicking "I accept,"
I confirm that:

- I have read these Terms of Service in full
- I am authorized to bind {{operator_entity}} to these Terms
- I will obtain my own legal counsel as appropriate (per §9)
- I acknowledge BullpenLM is not a party to my closer agreements
- I will comply with applicable law in my jurisdiction(s)

---

*TOS SHA-256 (printed at render time): {{document_sha256}}*

*TOS version: {{tos_version}}*
