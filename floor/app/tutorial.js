/**
 * First-session WALKTHROUGH — an interactive spotlight tour of the real floor.
 *
 * Not a slideshow. It dims the page, cuts a glowing hole around an ACTUAL
 * element (the Gauntlet, your rank, the goal, your first-drill rung), points
 * at it, and ends by having you click your real first drill. Anchored to the
 * live DOM, driven by your actions.
 *
 * Runs only where the Gauntlet ladder exists (the spawn floor home). Skips
 * operator-reserved names and remembers completion per-rep. No emojis.
 *   <script src="/app/tutorial.js" defer></script>
 */
(function () {
  const URLP = new URL(window.location.href);
  const REP = URLP.searchParams.get('rep') ||
    (() => { try { return localStorage.getItem('bullpen-rep'); } catch (e) { return null; } })();
  if (!REP) return;
  if (new Set(['self', 'operator', 'founder', 'host', 'beers']).has(REP.toLowerCase())) return;
  const KEY = `bp-tutorial-done-${REP}`;
  try { if (localStorage.getItem(KEY) === '1') return; } catch (e) {}

  // ── styles ────────────────────────────────────────────────────────────
  const st = document.createElement('style');
  st.id = 'bp-tour-style';
  st.textContent = `
    .bp-tour-hole{position:fixed;z-index:10000;border-radius:14px;pointer-events:none;
      box-shadow:0 0 0 9999px rgba(6,4,2,0.84), 0 0 0 2px var(--gold,#fbbf24), 0 0 26px 4px rgba(251,191,36,0.45);
      transition:all .28s cubic-bezier(.4,1.1,.4,1);}
    .bp-tour-tip{position:fixed;z-index:10001;width:min(330px,90vw);background:linear-gradient(180deg,#23190e,#160f08);
      border:1px solid rgba(251,191,36,0.5);border-radius:13px;padding:18px 18px 14px;
      box-shadow:0 16px 44px rgba(0,0,0,.6);font-family:"Switzer",-apple-system,sans-serif;
      transition:all .28s cubic-bezier(.4,1.1,.4,1);opacity:0;transform:translateY(6px);}
    .bp-tour-tip.in{opacity:1;transform:none;}
    .bp-tour-tip .pill{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:9.5px;letter-spacing:.22em;
      text-transform:uppercase;color:#fbbf24;margin-bottom:7px;}
    .bp-tour-tip h4{font-family:"Tanker",serif;font-size:21px;line-height:1.05;letter-spacing:-.01em;
      text-transform:uppercase;color:#f5e8d8;margin:0 0 7px;}
    .bp-tour-tip p{font-family:"Bespoke Serif",Georgia,serif;font-size:13.5px;line-height:1.5;color:#d8c9b4;margin:0;}
    .bp-tour-tip p b{color:#6ee7b7;font-weight:600;}
    .bp-tour-tip p .g{color:#fbbf24;}
    .bp-tour-row{display:flex;align-items:center;justify-content:space-between;margin-top:14px;gap:10px;}
    .bp-tour-dots{display:flex;gap:5px;}
    .bp-tour-dots i{width:6px;height:6px;border-radius:50%;background:rgba(245,232,216,.2);}
    .bp-tour-dots i.on{background:#fbbf24;box-shadow:0 0 6px #fbbf24;}
    .bp-tour-btns{display:flex;gap:7px;}
    .bp-tour-b{padding:8px 15px;border-radius:6px;border:none;cursor:pointer;font-family:"JetBrains Mono",monospace;
      font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;transition:transform .1s;}
    .bp-tour-b:hover{transform:translateY(-1px);}
    .bp-tour-b.go{background:#34d399;color:#0a1a14;}
    .bp-tour-b.nx{background:#fbbf24;color:#0a1a14;}
    .bp-tour-b.gh{background:transparent;color:#a89a87;border:1px solid rgba(245,232,216,.18);}
    .bp-tour-skip{margin-top:9px;text-align:center;font-family:"JetBrains Mono",monospace;font-size:9px;
      letter-spacing:.14em;text-transform:uppercase;color:#6b5a42;cursor:pointer;}
    .bp-tour-skip:hover{color:#d8c9b4;}
    .bp-tour-pulse{animation:bp-tour-pulse 1.3s ease-in-out infinite;}
    @keyframes bp-tour-pulse{0%,100%{box-shadow:0 0 0 9999px rgba(6,4,2,0.84),0 0 0 2px #fbbf24,0 0 18px 2px rgba(251,191,36,.4)}
      50%{box-shadow:0 0 0 9999px rgba(6,4,2,0.84),0 0 0 2px #6ee7b7,0 0 30px 7px rgba(110,231,183,.6)}}
  `;
  document.head.appendChild(st);

  // ── tour steps — each resolves a LIVE element at show time ─────────────
  const STEPS = [
    { sel: '#ladder',
      pill: 'The Gauntlet',
      title: 'This is your climb.',
      html: 'Seven tiers, seven buyers. Beat the boss at each one to <b>unlock the next</b>. Right now only Tier 1 is open.' },
    { sel: '#rank-badge,#rank-row',
      pill: 'Your rank',
      title: 'Every drill ranks you up.',
      html: 'You start a <span class="g">Rookie</span>. Score well and you climb — <b>Walk-On, Starter, Closer, All-Star, Legend</b> — past everyone else on the floor.' },
    { sel: '#goal-banner',
      pill: 'The goal',
      title: 'Clear Tier 3 to go live.',
      html: 'Hit <span class="g">Tier 3</span> and you unlock dialing <b>real prospects</b>. Until then: drill, duel, climb.' },
    { sel: '#ladder a.rung, #ladder .rung.current, #ladder .rung',
      pill: 'Your first fight',
      title: 'Take your first drill.',
      html: 'Step up to Tier 1. <b>Click the rung</b> and open the call — the buyer picks up, you deliver your cold open, you get scored on the spot.',
      action: 'Take the drill' },
  ];

  let i = 0, hole, tip, target;

  function place() {
    if (!target) return;
    const r = target.getBoundingClientRect();
    const pad = 8;
    hole.style.left = (r.left - pad) + 'px';
    hole.style.top = (r.top - pad) + 'px';
    hole.style.width = (r.width + pad * 2) + 'px';
    hole.style.height = (r.height + pad * 2) + 'px';
    // tip: prefer right of the target, else below, else above
    const tw = tip.offsetWidth || 330, th = tip.offsetHeight || 180;
    let left = r.right + 16, top = r.top;
    if (left + tw > window.innerWidth - 12) {            // no room right
      left = Math.min(r.left, window.innerWidth - tw - 12);
      top = (r.bottom + th + 16 < window.innerHeight) ? r.bottom + 14 : r.top - th - 14;
    }
    tip.style.left = Math.max(12, left) + 'px';
    tip.style.top = Math.max(12, Math.min(top, window.innerHeight - th - 12)) + 'px';
  }

  function resolve(sel) {
    for (const s of sel.split(',')) { const e = document.querySelector(s.trim()); if (e) return e; }
    return null;
  }

  function render() {
    const step = STEPS[i];
    target = resolve(step.sel);
    if (!target) { return next(); }                      // skip a missing element gracefully
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    hole.className = 'bp-tour-hole' + (step.action ? ' bp-tour-pulse' : '');
    tip.innerHTML = '';
    const pill = document.createElement('div'); pill.className = 'pill'; pill.textContent = step.pill;
    const h = document.createElement('h4'); h.textContent = step.title;
    const p = document.createElement('p'); p.innerHTML = step.html;   // trusted static copy
    const row = document.createElement('div'); row.className = 'bp-tour-row';
    const dots = document.createElement('div'); dots.className = 'bp-tour-dots';
    STEPS.forEach((_, k) => { const d = document.createElement('i'); if (k === i) d.className = 'on'; dots.appendChild(d); });
    const btns = document.createElement('div'); btns.className = 'bp-tour-btns';
    if (i > 0) { const b = document.createElement('button'); b.className = 'bp-tour-b gh'; b.textContent = 'Back'; b.onclick = prev; btns.appendChild(b); }
    const nb = document.createElement('button');
    if (step.action) { nb.className = 'bp-tour-b go'; nb.textContent = step.action; nb.onclick = doAction; }
    else { nb.className = 'bp-tour-b nx'; nb.textContent = 'Next'; nb.onclick = next; }
    btns.appendChild(nb);
    row.appendChild(dots); row.appendChild(btns);
    const skip = document.createElement('div'); skip.className = 'bp-tour-skip'; skip.textContent = 'skip the walkthrough'; skip.onclick = done;
    tip.appendChild(pill); tip.appendChild(h); tip.appendChild(p); tip.appendChild(row); tip.appendChild(skip);
    setTimeout(() => { place(); tip.classList.add('in'); }, 60);
  }

  function next() { if (i < STEPS.length - 1) { i++; render(); } else { done(); } }
  function prev() { if (i > 0) { i--; render(); } }
  function doAction() {
    // The payoff: actually start the drill. Mark done so it never re-nags.
    try { localStorage.setItem(KEY, '1'); } catch (e) {}
    if (target) {
      const href = target.getAttribute && target.getAttribute('href');
      teardown();
      if (href) { window.location.href = href; return; }
      target.click();
      return;
    }
    done();
  }
  function done() { try { localStorage.setItem(KEY, '1'); } catch (e) {} teardown(); }
  function teardown() {
    window.removeEventListener('resize', place);
    window.removeEventListener('scroll', place, true);
    if (hole) hole.remove(); if (tip) tip.remove();
  }

  function start() {
    hole = document.createElement('div'); hole.className = 'bp-tour-hole';
    tip = document.createElement('div'); tip.className = 'bp-tour-tip';
    document.body.appendChild(hole); document.body.appendChild(tip);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    render();
  }

  // Wait for the ladder to render (it hydrates async after data loads).
  // If it never appears (non-spawn page), do nothing — no nag.
  let tries = 0;
  (function waitForLadder() {
    if (document.querySelector('#ladder a.rung, #ladder .rung')) { start(); return; }
    if (tries++ > 40) return;                            // ~8s then give up silently
    setTimeout(waitForLadder, 200);
  })();
})();
