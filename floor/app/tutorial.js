/**
 * First-session tutorial overlay — drops in on closer-facing pages.
 *
 * Walks new closers through the loop they'll actually live in:
 *   1. The Office — where the bullpen lives
 *   2. The Studio — where the dossier lives
 *   3. The Drill — where they prove they can hold a call
 *   4. The Gate — what unlocks real-prospect dialing
 *
 * Triggers automatically the first time a rep (other than operator)
 * hits any of the wired pages. Dismissible. Remembered per-rep via
 * localStorage so it never nags twice.
 *
 * Usage in HTML:
 *   <script src="/app/tutorial.js" defer></script>
 *
 * Detects identity from ?rep= or localStorage. Operator-reserved
 * names (self, operator, founder, host, beers) skip the tutorial
 * since they already know how the system works.
 */
(function(){
  const URLP = new URL(window.location.href);
  const REP = URLP.searchParams.get('rep') || (() => {
    try { return localStorage.getItem('bullpen-rep'); } catch(e) { return null; }
  })();
  const BULLPEN = URLP.searchParams.get('b') || localStorage.getItem('bullpen-slug') || '';

  if (!REP) return;
  const operatorNames = new Set(['self', 'operator', 'founder', 'host', 'beers']);
  if (operatorNames.has((REP || '').toLowerCase())) return;

  const STORAGE_KEY = `bp-tutorial-done-${REP}`;
  try {
    if (localStorage.getItem(STORAGE_KEY) === '1') return;
  } catch(e){}

  // Style injection — single time
  if (!document.getElementById('bp-tutorial-style')) {
    const style = document.createElement('style');
    style.id = 'bp-tutorial-style';
    style.textContent = `
      .bp-tut-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.78);backdrop-filter:blur(8px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:24px;font-family:"Switzer",-apple-system,sans-serif;animation:bp-tut-fade-in 0.3s ease-out}
      @keyframes bp-tut-fade-in { from {opacity:0} to {opacity:1} }
      .bp-tut-card{max-width:520px;width:100%;background:linear-gradient(180deg,rgba(42,29,16,0.97),rgba(26,18,8,0.97));border:1px solid rgba(251,191,36,0.45);border-radius:16px;padding:32px;box-shadow:0 16px 50px rgba(0,0,0,0.6),0 0 24px rgba(251,191,36,0.18)}
      .bp-tut-step-pill{display:inline-block;padding:4px 11px;background:rgba(251,191,36,0.10);color:#fbbf24;border:1px solid rgba(251,191,36,0.40);border-radius:14px;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;font-weight:700;margin-bottom:12px}
      .bp-tut-title{font-family:"Tanker",serif;font-size:28px;letter-spacing:-.01em;text-transform:uppercase;color:#f5e8d8;margin:0 0 10px;line-height:1.1}
      .bp-tut-body{font-family:"Bespoke Serif",Georgia,serif;font-size:15.5px;line-height:1.6;color:#f5e8d8;margin:0 0 18px}
      .bp-tut-body em{font-style:normal;color:#fbbf24}
      .bp-tut-body strong{color:#6ee7b7;font-weight:600}
      .bp-tut-dots{display:flex;gap:6px;margin:14px 0 18px}
      .bp-tut-dot{width:8px;height:8px;border-radius:50%;background:rgba(245,232,216,0.18)}
      .bp-tut-dot.active{background:#fbbf24;box-shadow:0 0 8px #fbbf24}
      .bp-tut-actions{display:flex;justify-content:space-between;gap:12px;margin-top:18px;padding-top:18px;border-top:1px solid rgba(245,232,216,0.10)}
      .bp-tut-btn{padding:10px 22px;border-radius:7px;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;cursor:pointer;border:none;text-decoration:none;text-align:center;display:inline-block;transition:transform .12s}
      .bp-tut-btn:hover{transform:translateY(-1px)}
      .bp-tut-btn-primary{background:#34d399;color:#0a1a14}
      .bp-tut-btn-gold{background:#fbbf24;color:#0a1a14}
      .bp-tut-btn-ghost{background:transparent;color:#a89a87;border:1px solid rgba(245,232,216,0.18)}
      .bp-tut-btn-ghost:hover{color:#f5e8d8;border-color:#f5e8d8}
      .bp-tut-skip{margin-top:14px;text-align:center;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#806a4f;cursor:pointer}
      .bp-tut-skip:hover{color:#f5e8d8}
    `;
    document.head.appendChild(style);
  }

  const Q = `?b=${encodeURIComponent(BULLPEN)}&rep=${encodeURIComponent(REP)}`;
  const STEPS = [
    {
      pill: 'WELCOME · 1 of 4',
      title: 'You’re in the practice bullpen.',
      body: 'Nobody’s dialing real customers yet. The first phase is <strong>drilling</strong> — against AI buyers, against your teammates, against your own bad habits.<br><br>Beers built this for friends learning to sell together. <em>Real commission later. Real reps now.</em>',
      cta: 'Show me the floor',
      ctaHref: `/app/office.html${Q}`,
      ctaSecondary: null,
    },
    {
      pill: 'THE OFFICE · 2 of 4',
      title: 'This is the bullpen floor.',
      body: 'Click around. You’ll see <strong>teammates</strong> at workstations, <strong>AI buyers</strong> at the desks on the right, the <em>duo ring</em> where 1v1s happen, and the <em>kanban pipeline</em> across the bottom.<br><br>You appear as a gold pawn. Your teammates have their own colors.',
      cta: 'Next — the dossier',
      ctaHref: `/app/studio.html${Q}`,
      ctaSecondary: { label: 'Skip to the office', href: `/app/office.html${Q}` },
    },
    {
      pill: 'THE STUDIO · 3 of 4',
      title: 'Drop sources — the AI buyer gets smarter.',
      body: 'The Studio is where you build the <strong>dossier</strong> for each AI buyer. Drop a PDF, a URL, paste a transcript — the AI buyer’s roleplay grounds in <em>real material</em>, not just made-up persona.<br><br>You also get flashcards, a pop quiz, a pre-call briefing, and an account map — all auto-generated from whatever you dropped in.',
      cta: 'Last bit — the gate',
      ctaHref: `/app/onboard/${Q}`,
      ctaSecondary: { label: 'Open Studio', href: `/app/studio.html${Q}` },
    },
    {
      pill: 'THE GATE · 4 of 4',
      title: 'Sign the paper. Pass a Tier-3 drill. Then real customers.',
      body: 'You can’t dial a real prospect until: <strong>disclosure read</strong>, <strong>closer agreement signed</strong>, <strong>W-9 submitted</strong>, <strong>DNC acknowledgement signed</strong>, and a <strong>Tier-3 Gauntlet drill passed</strong>.<br><br>That’s the gate. Until then: drill, duel, study. <em>That’s the practice phase.</em>',
      cta: 'Got it — let’s go',
      ctaHref: `/app/onboard/${Q}`,
      ctaSecondary: { label: 'Skip to drilling', href: `/app/spotcheck.html${Q}&tcs=cold-open-bfsi` },
    },
  ];

  let stepIdx = 0;
  function show(){
    document.querySelectorAll('.bp-tut-overlay').forEach(n => n.remove());
    const step = STEPS[stepIdx];
    const overlay = document.createElement('div');
    overlay.className = 'bp-tut-overlay';
    const card = document.createElement('div');
    card.className = 'bp-tut-card';
    overlay.appendChild(card);

    const pill = document.createElement('div');
    pill.className = 'bp-tut-step-pill';
    pill.textContent = step.pill;
    card.appendChild(pill);

    const title = document.createElement('div');
    title.className = 'bp-tut-title';
    title.textContent = step.title;
    card.appendChild(title);

    const body = document.createElement('div');
    body.className = 'bp-tut-body';
    // Parse our limited markup: <strong>, <em>, <br><br>
    appendRichText(body, step.body);
    card.appendChild(body);

    const dots = document.createElement('div');
    dots.className = 'bp-tut-dots';
    STEPS.forEach((_, i) => {
      const d = document.createElement('div');
      d.className = 'bp-tut-dot' + (i === stepIdx ? ' active' : '');
      dots.appendChild(d);
    });
    card.appendChild(dots);

    const actions = document.createElement('div');
    actions.className = 'bp-tut-actions';

    if (stepIdx > 0){
      const back = document.createElement('button');
      back.className = 'bp-tut-btn bp-tut-btn-ghost';
      back.textContent = '← Back';
      back.addEventListener('click', () => { stepIdx--; show(); });
      actions.appendChild(back);
    } else {
      // First step — left side is empty, use a placeholder
      const spacer = document.createElement('span'); spacer.style.flex = '1';
      actions.appendChild(spacer);
    }

    const right = document.createElement('div');
    right.style.display = 'flex'; right.style.gap = '8px';
    if (step.ctaSecondary){
      const second = document.createElement('a');
      second.className = 'bp-tut-btn bp-tut-btn-ghost';
      second.href = step.ctaSecondary.href;
      second.textContent = step.ctaSecondary.label;
      second.addEventListener('click', complete);
      right.appendChild(second);
    }
    if (stepIdx < STEPS.length - 1){
      const next = document.createElement('button');
      next.className = 'bp-tut-btn bp-tut-btn-gold';
      next.textContent = step.cta;
      next.addEventListener('click', () => { stepIdx++; show(); });
      right.appendChild(next);
    } else {
      const done = document.createElement('a');
      done.className = 'bp-tut-btn bp-tut-btn-primary';
      done.href = step.ctaHref;
      done.textContent = step.cta;
      done.addEventListener('click', complete);
      right.appendChild(done);
    }
    actions.appendChild(right);
    card.appendChild(actions);

    const skip = document.createElement('div');
    skip.className = 'bp-tut-skip';
    skip.textContent = 'or skip the tutorial';
    skip.addEventListener('click', complete);
    card.appendChild(skip);

    document.body.appendChild(overlay);
  }

  function appendRichText(parent, raw){
    // Splits on a tiny set of tags: <strong>, <em>, <br>, <br><br>.
    // Safe DOM construction — no innerHTML.
    const parts = raw.split(/(<\/?strong>|<\/?em>|<br><br>|<br>)/);
    let strong = false, em = false;
    for (const p of parts){
      if (p === '<strong>'){ strong = true; continue; }
      if (p === '</strong>'){ strong = false; continue; }
      if (p === '<em>'){ em = true; continue; }
      if (p === '</em>'){ em = false; continue; }
      if (p === '<br><br>'){ parent.appendChild(document.createElement('br')); parent.appendChild(document.createElement('br')); continue; }
      if (p === '<br>'){ parent.appendChild(document.createElement('br')); continue; }
      if (!p) continue;
      let node;
      if (strong){ node = document.createElement('strong'); node.textContent = p; }
      else if (em){ node = document.createElement('em'); node.textContent = p; }
      else { node = document.createTextNode(p); }
      parent.appendChild(node);
    }
  }

  function complete(){
    try { localStorage.setItem(STORAGE_KEY, '1'); } catch(e){}
    document.querySelectorAll('.bp-tut-overlay').forEach(n => n.remove());
  }

  // Show on DOMContentLoaded so the rest of the page renders behind
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', show);
  } else {
    setTimeout(show, 200);
  }
})();
