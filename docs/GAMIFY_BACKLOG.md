# BullpenLM Gamification + Tracking Backlog

Source: 10-agent audit+research fleet (2026-06-05). Ranked by impact/effort, frontend-first.
FE=frontend-only (ship live, no rebuild). Backend items batch behind a binary rebuild / run-from-source.

## Themes

- The full reward loop is built server-side but invisible on the floor: streak/class XP multipliers are computed and displayed but never actually applied (server/xp.py only folds in squad bonus), and the office.html SSE handler celebrates only 4 event kinds (plus a typo'd 'rag_source_ingested' that is never emitted). The single highest-leverage theme is making every already-logged reward MOMENT (level-up, achievement, trophy, quest-ready, streak) LOUD on the daily-driver surface — almost entirely frontend, zero binary rebuild.
- Training is the core fun (AI-buyer drills) but the loop leaks at the most important point: the practice sim grades, computes metrics, and saves a transcript yet emits NO drill_attempt/drill_passed audit event, so solo practice earns zero XP, advances no streak, feeds no quest/leaderboard. Closing the tracking gaps (drill events, call-outcome funnel, loss-reason, deal velocity) unlocks an entire class of gamification that is currently impossible because the data is one event away.
- Onboarding front-loads the least-fun part (5-step legal gate, W-9, DNC) before the rep ever drills, and the highest-friction steps grant the least reward (disclosure + W-9 match no XP rule). Defer all legal to the FLOOR gate, route invited friends straight into a 90-second scored AI-buyer drill with an instant XP/scorecard payoff, and turn the gate itself into a celebrated 'level'.
- Closing has strong close-won juice but the most ceremonial action is buried in a kanban drag with no close button on the deal page, the variable-reward trophy drop is invisible at the moment of the close, and there is no finish line (quota/pace), no rotting-pipeline pressure, and no closing rivalry frame. Bring the close action, the loot reveal, the goal line, and the leaderboard onto the surfaces where reps actually work deals.
- Multiplayer/social retention is under-built for the 5-15 friend alpha: no recurring weekly league with relegation (loss aversion), streaks are purely individual, leaderboards have no catch-up mechanic, duels are 100% manual (and the accept link is BROKEN), and three of seven leaderboard lanes match event kinds nothing emits. Tighten the named-peer competition loop that is uniquely powerful at this cohort size.
- Feedback latency and 'compounding receipt' visibility: Duolingo's moat is that one action visibly moves many bars at once. BullpenLM computes all those projections from one audit log but never shows the rep that a single drill advanced XP + streak + quest + achievement + league together. Surface the compounding receipt and add sound/haptics so rewards are felt within the same second.

## Backlog

### [1] Fix the broken duel-accept deep link
`stage=cross` · impact=high · effort=S · **FRONTEND**

floor/app/challenge-notif.js line 139 builds the accept URL with `&duo_id=${duo.id}` but floor/app/duo.html line 139 reads `params.get('id')` (confirmed). Fix: in challenge-notif.js change the param to `&id=`, OR in duo.html change to `params.get('id') || params.get('duo_id')`. Prefer the duo.html change so both forms work. This is a dead-on-arrival funnel: every accepted 1v1 challenge currently lands on 'Missing duo id'. One-line fix, restores the entire duel funnel.

### [2] Juice every XP-firing event in the office (data-driven SSE)
`stage=gamification` · impact=high · effort=S · **FRONTEND**

floor/app/office.html subscribeSSE() (confirmed ~line 2143) hardcodes ['deal_stage_moved','deal_created','quest_completed','drill_passed','rag_source_ingested'] — the last kind is NEVER emitted (correct kind is 'source_ingested'). Replace with a set of all positive-XP kinds: add 'source_ingested','call','followup_done','spotcheck_responded','duo_accepted','duel_accepted','flashcard_passed','quiz_completed'. Color the toast by ledger (gold=money, mint=clout) using a small kind->bucket map mirrored from xp.py RULES. fireXpToast already exists (~line 2106). No server change.

### [3] Live level-up + title-promotion celebration on the floor
`stage=gamification` · impact=high · effort=S · **FRONTEND**

office.html already refetches /api/b/<b>/xp/<rep> after XP events and has d.level + the title ladder (titleFor). Cache prior level in a module var + localStorage('bp-last-level-<rep>'); in the .then() compare d.level to cached. On increase, fire a new fireLevelUp(level) that clones the existing .ff-card/.fanfare CSS with 'LEVEL UP · LVL N' and, if titleFor changed, a 'NEW RANK: GHOST' line. Fires once per real transition. Reuses existing fanfare styling; no backend.

### [4] Live trophy + achievement unlock fanfare on the floor
`stage=gamification` · impact=high · effort=S · **FRONTEND**

achievement_unlocked and trophy_awarded already fan out over SSE (audit.append publishes; confirmed events.publish path). In office.html subscribeSSE() add branches for both kinds: read payload.rarity (common/rare/epic/legendary) and payload.name/icon, render a rarity-tinted banner (reuse fanfare for legendary at escalating scale, lighter toast for common). No server call needed — names/rarity are in the payload. Biggest variable-reward moments are currently only visible later on profile.html.

### [5] Reward sound + haptics layer (Web Audio, no assets)
`stage=gamification` · impact=high · effort=S · **FRONTEND**

office.html's ringBell() is silent while wallboard.html/arena.html synthesize a WebAudio bell (confirmed bellSound oscillator pattern in wallboard.html). New floor/app/sfx.js: AudioContext synth — bright bell-overtone stack for close-won, rising 3-note arpeggio for level-up, coin-blip for quest-claim/+XP, rarity-pitched chime for trophies; call navigator.vibrate() where supported. Gate behind localStorage 'bp-sfx' (default on) + a mute button in office.html header. Wire into ringBell/fireFanfare/fireXpToast and the new level-up/trophy handlers (ranks 3-4). Zero server change.

### [6] Ring-the-bell close button on the deal page
`stage=closing` · impact=high · effort=S · **FRONTEND**

deal.html paintHeader() builds an .actions row with Log call/email/meeting/note but NO close action (confirmed ~line 202). Add a gold '🔔 Close WON' and a danger '✕ Mark lost' button that POST to /api/b/<BULLPEN>/deals/<DEAL_ID>/stage with {stage:'won'|'lost', rep:REP} — the exact endpoint deals.html already uses (confirmed deals.html line 272). On success show a local toast + reload(); the server's deal_closed_won SSE drives the office/wallboard fanfare. No server change. (Mark-lost should open the loss-reason modal, rank 11.)

### [7] Floor streak flame + 'streak at risk' nudge
`stage=gamification` · impact=high · effort=M · **FRONTEND**

GET /api/b/<slug>/streaks/<rep> exists (confirmed server.py ~line 2295) and returns streak count + multiplier + freeze tokens. On office.html load, render a flame pill near the LVL pill with day count + tier label + multiplier. If streak>0 and the rep has no XP-earning event today (derive from the /xp ledger ts the page already fetches), show a pulsing 'KEEP YOUR N-DAY STREAK — make one dial' banner with a midnight countdown; if a freeze token is owned, offer one-tap freeze. Read-only over existing endpoints.

### [8] Show the trophy drop inside the close-won fanfare
`stage=gamification` · impact=high · effort=M · **FRONTEND**

In office.html fireFanfare() and wallboard.html ringBell(): after the close event, fetch the rep's trophies (profile.html already reads this; confirm path /api/b/<b>/trophies/<rep>) and find the one with id 'trophy-<deal_id>' (trophies.py is deterministic per deal_id+amount). Render its icon+name+rarity in the fanfare card with a rarity-colored glow (gold for legendary). Surfaces the variable-reward reveal trophies.py already computes but no surface shows at close time.

### [9] Quest-ready live pop + one-tap claim on the floor
`stage=gamification` · impact=medium · effort=S · **FRONTEND**

office.html renders the quest board and already has a claim handler (confirmed claim.addEventListener ~line 782). On deal_stage_moved/call/drill_passed SSE events, re-fetch quest progress (existing endpoint) and diff against prior render; if any quest flips to completed && !claimed, pulse the board and pop a 'QUEST READY · CLAIM +NN XP' toast whose button POSTs the existing claim endpoint then fires fireXpToast. Converts pull-based claim into a push celebration. Existing endpoints only.

### [10] Stale-deal heat on the kanban + forecast cards
`stage=tracking` · impact=high · effort=S · **FRONTEND**

deals.html buildDealCard(): compute days-in-current-stage from deal.stage_history (last entry .at) and days-since-opened (both already returned by the deals API). Add a colored left border / age chip: green <3d, amber 7-14d, red >14d in a non-terminal stage, plus a '⚠ stuck Nd' label. Mirror the age badge into forecast.html's top-deals table. Pure client computation; no server change.

### [11] Loss-reason capture modal
`stage=tracking` · impact=high · effort=M · **FRONTEND**

When the new 'Mark lost' button (deal.html, rank 6) or a drop into the Lost column (deals.html) fires, first open a small modal: select of [price, timing, no_decision, competitor, no_budget, bad_fit, ghosted, other] + optional note. Frontend-only path: persist via the existing /activity endpoint as kind:'note' summary 'Lost: <reason>' (deal.html openLogModal already POSTs activity) so it lands in the timeline + audit chain. A later backend pass (rank 18) reads it for analytics. No server change for the capture itself.

### [12] Quota line + pace-to-goal on forecast & commissions
`stage=closing` · impact=high · effort=M · **FRONTEND**

forecast.html: add a goal in localStorage (keys goal-<BULLPEN>-<REP> and goal-<BULLPEN>-all), editable via an inline input on the 'Won this period' card. Render a progress bar of wonAmount/goal plus a pace verdict from day-of-month: 'On pace' / 'Behind by $X' / 'Goal hit 🔔'. All math client-side from the deals array already fetched. Mirror the bar onto commissions.html hero. No server change.

### [13] Practice scorecard with grade, metric dials, personal-best
`stage=tracking` · impact=high · effort=M · **FRONTEND**

The practice sim grade UI is the lone .score-grade span in server.py embedded HTML (confirmed ~line 933/1182). Replace with a scorecard: big letter grade + dials for talk_ratio (~43% target per Gong), filler_count, wpm, question_count — all already in the /api/score metrics response. Cache the prior attempt in localStorage keyed by buyer slug and show +/- delta arrows vs last attempt. Editing the embedded HTML in server.py is frontend (HTML/JS) but lives in the .py string; if a separate floor/app/practice-score.html is preferred, even cleaner. No Python logic change.

### [14] Daily drill quota + streak-defense strip on training pages
`stage=gamification` · impact=high · effort=S · **FRONTEND**

Add a header strip to voice.html, spotcheck.html, training.html calling the existing /api/b/<slug>/streaks/<rep> endpoint plus client-side counting of today's drills from data the page already loads: 'Day streak 6 (+5% XP) · one more drill keeps it alive' and 'Reps today 1/3'. Define the daily unit as one scored ARENA drill OR one real FLOOR call. Read-only over existing endpoints.

### [15] First-session questline overlay on spawn
`stage=onboarding` · impact=high · effort=M · **FRONTEND**

floor/app/spawn.html: add a dismissible 'Your first session' card above the quest grid with a fixed 4-item checklist: (1) Finish the tour, (2) Drop one source in Studio, (3) Pass your first drill, (4) Open the legal gate. Compute done-state client-side: tutorial localStorage key (bp-tutorial-done-<rep>), /api/b/<bp>/profile/<rep> for source/drill counts, /api/b/<bp>/gate/<rep> missing[] for gate progress. Each item links to the relevant page preserving b=&rep=; checks when satisfied; collapse + persist when all four done. No new endpoints.

### [16] Value-before-paperwork: route invited friends straight into a scored drill
`stage=onboarding` · impact=high · effort=M · **FRONTEND**

Change the post-invite-redeem redirect (quickstart/index.html enterFloor / join.html) so first-time reps go to a stripped ARENA drill (e.g. spotcheck.html?...&tcs=cold-open with a guided tutorial.js overlay) instead of the legal-heavy welcome/onboard flow. Require only display name inline. Keep onboard/index.html's 5-step gate intact but trigger it ONLY when the rep first tries to claim a real prospect — the gate already enforces this via /gate/<rep>. Add one motivation chip question ('What do you want to crush first?' → picks the first TCS). Routing/UI only; the gate logic is unchanged.

### [17] Make AI-buyer practice actually earn XP (emit drill events)
`stage=tracking` · impact=high · effort=M · **BACKEND**

server.py /api/score (~line 5870-5908) currently only calls team.log_call(kind='practice') and emits NO audit event (confirmed). After score=ollama_chat, parse the SCORE A-F and the WOULD-THIS-BOOK line, then audit_append 'drill_attempt' (payload: grade, talk_ratio, filler_count, prospect) and on grade<=B or book=YES audit_append 'drill_passed' (payload: phase_tier from card or 1, filler_count, grade). Mirror in the /voice-chat handler (currently no scoring pass at all). xp.py already has rules for these kinds, so this lights up streaks, Top Pack, sprints, and filler achievements with zero new gamification code. Python change → needs binary rebuild.

### [18] Wire streak + class multipliers into actual XP
`stage=gamification` · impact=high · effort=M · **BACKEND**

server/xp.py _compute() applies ONLY squad_xp_bonus (confirmed line 386-430); streaks.multiplier() and classes.apply_xp_multiplier() are displayed but never folded into totals. Add: per-actor cache of streaks.multiplier(bullpen, actor) and classes.apply_xp_multiplier(rep_class, event, base) using the member's class record. Apply class outcome perks to money-XP; apply streak (engagement) to both ledgers per policy. Append the reason string ' (streak ×1.20)' / ' (class +20%)'. Guard against recursion during pvp xp_mode scoring. Makes the headline +20%/class bonuses honest. Python change → rebuild.

### [19] Per-step XP for the legal gate + gate-cleared celebration
`stage=onboarding` · impact=medium · effort=M · **BACKEND**

Two parts. Backend (xp.py RULES): add clout rules for kinds already emitted by disclosures.py/legal.py — closer_disclosure_accepted (~20 clout), w9_submitted (~20 clout), and a one-time gate-cleared/onboarding_complete bonus (~100 clout). These currently match NO rule = 0 XP. Keep clout-only to respect the money/clout firewall. Frontend (onboard/index.html): replace static step labels with 'Step N of 5 — X to dial real prospects', animate the stepper fill, and on gate-clear (r.data.ok already detected) trigger a confetti/bell burst + count-up '+XP unlocked' banner and a 'clearance carries to every bullpen on this host' note. The frontend half ships today; the XP rules need a rebuild.

### [20] Fix dead leaderboard lanes to match real event kinds
`stage=tracking` · impact=high · effort=S · **BACKEND**

server/leaderboard.py compute(): hunter/marketer/researcher lanes match event kinds nothing emits (buyer_card_created, prospect_seeded, tracked_link_minted, outbound_email_sent, rag_source_ingested, dossier_enriched, studio_asset_generated). Change researcher → 'source_ingested' (kind rag.py actually emits), marketer → ('marketing_post_published','marketing_post_clicked'), hunter → credit on 'claim' and 'deal_created'. Without this, three of seven lanes render blank forever, defeating the multi-lane 'everyone is #1 somewhere' retention design. Python change → rebuild.

### [21] Dial-outcome funnel + connect-rate panel
`stage=tracking` · impact=high · effort=M · **FRONTEND**

New floor/app/funnel.html that pulls the existing audit feed client-side, filters kind==='call', and buckets payload.outcome (booked/no_answer/voicemail/gatekeeper/not_interested/bad_number/callback — already persisted by activity.log). Render total dials, connect rate, conversation-to-meeting rate, and a horizontal funnel bar per stage with elite benchmarks overlaid (connect 8-12% avg / 22-30% elite; connect-to-meeting ~5% avg / 15% elite). Highlight the worst-relative stage with a one-click 'drill this' link into the matching ARENA scenario. me/all scope toggle. No server change.

### [22] Call-quality trend sparklines on profile
`stage=training` · impact=high · effort=M · **FRONTEND**

floor/app/profile.html: add a 'Call quality over time' section that fetches the existing /api/metrics/history endpoint (currently only consumed by legacy index.html) and draws inline SVG sparklines for talk_ratio, fillers_per_100_words, hedge_count, question_ratio across the rep's last N attempts, with metrics.py coaching thresholds (43% talk, <2 fillers/100w) as target lines. Add a 'Consistency Score' = 1 - stddev(talk_ratio over last 8 calls), since Gong's 2025 finding is that ratio STABILITY separates elite from average. Endpoint already exists; no server change.

### [23] Win-rate, sales-cycle & velocity mini-stats on forecast
`stage=tracking` · impact=medium · effort=M · **FRONTEND**

forecast.html: from the deals array (stage_history, opened_at, closed_at all returned) compute and render: Win rate = won/(won+lost), Avg cycle = mean(closed_at - opened_at) for won deals, a stage-conversion funnel (count entering vs advancing per stage), avg time-in-stage column, and Pipeline Velocity = (open deals × win rate × avg deal size) / median cycle days shown as $/day with a 7-day trend arrow. Flag deals aging past per-stage thresholds in red. All client-side; no server change.

### [24] Auto-suggested rivals + closer scoreboard on closing surfaces
`stage=gamification` · impact=medium · effort=M · **FRONTEND**

Two reuses of leaderboard.py output (closer lane already sorted by revenue). (1) Add a thin scoreboard strip to commissions.html and deal.html: 'You: #2 closer · $X · 3 wins — leader BEERS $Y' from the existing leaderboard endpoint. (2) On arena.html / spawn, compute 'Your natural rival this week' = the member with the smallest absolute trailing-7-day money-XP gap (client-side over the audit/leaderboard data) and add a one-tap 'Challenge [rival] to a dials duel' that pre-fills the create-duel form (and now works, per rank 1). Confirm the closer-lane API route is exposed; if so, frontend-only.

### [25] Cohort presence + 'rep #N' framing for the alpha
`stage=gamification` · impact=medium · effort=S · **FRONTEND**

spawn.html already fetches /api/b/<bp>/spawn returning stats.online_reps (renderOnline). Extend the hero to show 'You're closer #N in <bullpen>' + a roster count (fall back to online_reps.length). On the quickstart 'welcome back' notice add '+K others already on this floor'. After the first drill, show a 5-row leaderboard.py slice centered on the new rep ('You: #5 · Jake: #4 — 40 XP ahead'). Pure client rendering of data the endpoints already return.

### [26] Close-streak + first-close-of-day bonus juice
`stage=gamification` · impact=medium · effort=M · **FRONTEND**

office.html / wallboard.html SSE handler for deal_closed_won: track consecutive closes per rep in client session + a per-day localStorage flag. On the 1st close of the day show 'FIRST BLOOD 🔔'; on back-to-back closes within a window show 'ON FIRE x2/x3' escalating the fanfare burst intensity (and SFX from rank 5). Server already emits the event with actor+amount; purely client celebration state. (Durable close-streaks would need streaks.py work; the visual hot-streak layer is frontend-only.)

### [27] Resumable onboarding deep-link + unified readiness chip
`stage=onboarding` · impact=medium · effort=M · **FRONTEND**

(1) In spawn.html load(), after fetching /api/b/<bp>/gate/<rep>, if missing[] is non-empty and the rep isn't an operator, show a prominent 'Pick up where you left off → <next step>' banner linking to /app/onboard/?b=&rep= (auto-resumes via deriveStepFromGate). (2) Add a shared floor/app/readiness.js include that reads the gate endpoint as the single source of truth and renders one combined progress chip ('3/5 to live dialing') in the header of spawn.html, office.html, studio.html — reconciling the confusing welcome.html (3-step) vs onboard/ (5-step) split by always reflecting the gate. No new endpoints.

### [28] Onboarding + tutorial funnel beacons for the operator
`stage=tracking` · impact=medium · effort=M · **BACKEND**

Add POST /api/b/<bp>/onboarding/event (server.py route + onboarding.py helper that audit_appends kind 'onboarding_funnel' with payload {stage:'quickstart_started'|'spawned'|'tutorial_completed'|'tutorial_skipped'|'gate_opened'|'gate_cleared', rep}). Fire from quickstart enterFloor(), spawn.html load(), tutorial.js complete() (distinguish skip vs finish), and onboard at gate-clear. tutorial.js completion is currently localStorage-only with zero server visibility. closers.html then renders a dropoff funnel bar. Server route → rebuild; tutorial.js can stash events in localStorage as a stopgap meanwhile.

### [29] Weekly Leagues with relegation (core retention loop)
`stage=gamification` · impact=high · effort=L · **BACKEND**

New server/leagues.py as a pure projection over the audit log (same pattern as streaks.py). Mon 00:00→Sun 23:59 window, rank reps by money-XP earned that week (keep clout out to respect the firewall). With 5-15 reps, split into 2-3 named tiers; each Sunday promote top 1-2 of each lower tier, demote bottom 1-2 of each upper tier, emitting league_promoted/league_demoted audit events for wallboard + Discord announcements. Frontend: a live 'you are 40 XP from demotion' banner in office.html (that line is where loss aversion lives) + a podium on arena/wallboard. Backend module + new events → rebuild.

### [30] Co-op weekly bullpen raid boss with a shared progress bar
`stage=gamification` · impact=high · effort=L · **BACKEND**

Define one auto-spawning weekly 'raid boss' per bullpen — a collective target scaled to roster size (e.g. members × 50 real dials, or $X gross). Reuse parties.py raid_party_progress() math with party = all members. Put a big shared HP/progress bar on wallboard.html and the office home that ticks live off the SSE stream. On clear by Sunday, everyone gets a split bonus + a rare trophy roll (trophies.py); on miss, no penalty (co-op is additive). Escalate the target slightly each cleared week. Needs a server-side weekly target + a sprint_won/raid_cleared resolution event → rebuild.

### [31] Adaptive objection-resurfacing + per-drill rubric scorecard
`stage=training` · impact=high · effort=L · **BACKEND**

Two coupled backend pieces. (1) Tag each AI-buyer drill with the objection/persona it trains; have the local Ollama buyer emit a JSON 4-5 criterion rubric score (opener/discovery/objection/ask/tone, 0-3) at call end, written into the drill_passed payload (depends on rank 17 emitting the event). (2) Store a per-rep SM-2-lite schedule as a projection over drill_attempt/drill_passed: each objection's interval lengthens on pass, resets on fail; an arena 'Recommended drill' button serves the most-overdue weakest objection. Render the rubric radar on the practice scorecard (rank 13). Spaced repetition >2x retention. New scoring + scheduler logic → rebuild.

### [32] Upgrade spot-check grading to hybrid LLM coach on money-tier
`stage=training` · impact=medium · effort=M · **BACKEND**

tcs.auto_grade / spotcheck._apply_grade currently use pure keyword OR-match (gameable). For substantive responses on cert-tier drills (phase_tier>=3, the money-XP path), also run an Ollama rubric pass (reuse scoring_system_prompt scoped to the TCS) and require BOTH keyword hits AND a passing LLM verdict for a GO; keep keyword-only for low tiers. Closes the keyword-stuff exploit on the path that mints real money-XP. Python change → rebuild.

### [33] Capture call-outcome + objection events + loss-reason payload
`stage=tracking` · impact=medium · effort=L · **BACKEND**

Mint the missing outcome events so connect-rate/win-rate/objection streaks become possible: in calls.py/debrief.py emit 'connect' (leaderboard.cold_open references connect=true but nothing mints it), 'objection_handled', 'meeting_set'; in deals.py move_stage() add a reason arg so deal_closed_lost payload carries {reason, competitor} (consumes rank 11's frontend capture). Add clout XP RULES for connect/objection-handled and an Objection Patience metric (post-objection monologue word count, computed in metrics.py). Then leaderboard.py + funnel.html (rank 21) can compute real lanes. Foundational backend work → rebuild.

### [34] Clout-XP cosmetic store (vanity sink)
`stage=gamification` · impact=medium · effort=L · **BACKEND**

clout-XP accumulates with no sink. New server/cosmetics.py: catalog priced in clout-XP + per-rep owned/equipped store under bullpens/<slug>/cosmetics/<rep>.json + a 'cosmetic_purchased' audit event (clout sink only — never touches money-XP, preserving the firewall). Expose GET catalog + POST purchase/equip. Frontend: a Shop modal in office.html spending clout; apply equipped pawn color/title/name-color in the office render (closerPosition pawn + YOU label) and profile.html. Strictly cosmetic to stay clear of the pyramid firewall. New module → rebuild.

### [35] Personal activity heatmap + XP ledger drawer on the floor
`stage=tracking` · impact=low · effort=S · **FRONTEND**

(1) profile.html: render a 12-week GitHub-style calendar grid where each cell intensity = count of that rep's XP-firing audit events that day (filter actor===REP over the audit tail, mirror streaks.py ACTIVE_KINDS client-side). (2) office.html: a slide-out 'why did I earn this' drawer triggered by clicking the LVL pill that lists the existing /api/b/<slug>/xp/<rep> ledger array (last 50 entries with xp/bucket/reason/kind/ts) grouped money vs clout. Both pure consumption of existing endpoints.
