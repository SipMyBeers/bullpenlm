/**
 * Duo challenge notification overlay — drop-in for any closer-facing page.
 *
 * Subscribes to the bullpen audit SSE stream. When a `duo_challenged`
 * event lands where you are the opponent, pops a sticky toast bottom-
 * right with ACCEPT / DECLINE buttons. Click ACCEPT → navigates to the
 * duo page with duo_id preloaded; the duo's Accept button finishes the
 * handshake.
 *
 * Also surfaces pending challenges on page load (in case the user
 * arrives AFTER the SSE event already fired — polls /api/b/<slug>/duos
 * once at mount to catch anything stale).
 *
 * Self-dismisses 60s after appearing or on ACCEPT click. DECLINE marks
 * the duo as ended with reason=declined.
 *
 * Usage:
 *   <script src="/app/challenge-notif.js" defer></script>
 *
 * Identity discovery — same convention as gate-banner.js:
 *   ?b=<bullpen>&rep=<rep>  in window.location
 *   OR localStorage 'bullpen-rep' fallback
 *
 * Operator-reserved reps (self, beers, founder, host, operator) STILL
 * see incoming challenges — operators can be challenged too.
 */
(function(){
  const url = new URL(window.location.href);
  const BULLPEN = url.searchParams.get('b');
  let REP = url.searchParams.get('rep');
  if (!REP) {
    try { REP = localStorage.getItem('bullpen-rep'); } catch (e) {}
  }
  if (!BULLPEN || !REP) return;

  // Inject style once
  if (!document.getElementById('bullpenlm-challenge-style')) {
    const s = document.createElement('style');
    s.id = 'bullpenlm-challenge-style';
    s.textContent = `
      .bp-challenge-toast{position:fixed;bottom:24px;right:24px;z-index:9999;max-width:380px;
        background:linear-gradient(180deg,rgba(42,29,16,0.97),rgba(26,18,8,0.97));
        border:1px solid rgba(251,191,36,0.55);border-radius:14px;padding:18px 20px;
        font-family:"Switzer",-apple-system,sans-serif;font-size:14px;color:#f5e8d8;
        box-shadow:0 8px 32px rgba(0,0,0,0.6),0 0 24px rgba(251,191,36,0.18);
        animation:bp-toast-in 0.32s cubic-bezier(0.34,1.56,0.64,1)}
      .bp-challenge-toast.declining{opacity:0.5;pointer-events:none;transition:opacity 0.2s}
      @keyframes bp-toast-in {
        from {transform:translateX(420px);opacity:0}
        to   {transform:translateX(0);opacity:1}
      }
      .bp-challenge-toast .bp-label{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;
        font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:#fbbf24;
        margin-bottom:6px;display:flex;align-items:center;gap:8px}
      .bp-challenge-toast .bp-label .pulse{width:8px;height:8px;border-radius:50%;background:#fbbf24;
        box-shadow:0 0 10px #fbbf24;animation:bp-pulse 1.2s ease-in-out infinite}
      @keyframes bp-pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
      .bp-challenge-toast .bp-title{font-family:"Tanker",serif;font-size:20px;text-transform:uppercase;
        letter-spacing:-.01em;line-height:1.1;margin:0 0 6px}
      .bp-challenge-toast .bp-title .who{color:#34d399}
      .bp-challenge-toast .bp-meta{font-family:"Bespoke Serif",Georgia,serif;font-style:italic;
        color:#a89a87;font-size:13.5px;margin-bottom:14px}
      .bp-challenge-toast .bp-buyer{padding:8px 12px;background:rgba(0,0,0,0.30);border-radius:6px;
        font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:11.5px;
        color:#6ee7b7;letter-spacing:.04em;margin-bottom:14px}
      .bp-challenge-toast .bp-actions{display:flex;gap:8px}
      .bp-challenge-toast .bp-btn{flex:1;padding:9px 12px;border-radius:7px;
        font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:10.5px;
        letter-spacing:.14em;text-transform:uppercase;font-weight:700;cursor:pointer;
        border:none;text-decoration:none;text-align:center;display:inline-block}
      .bp-challenge-toast .bp-btn.accept{background:#34d399;color:#0a1a14}
      .bp-challenge-toast .bp-btn.decline{background:transparent;color:#a89a87;
        border:1px solid rgba(245,232,216,0.18)}
      .bp-challenge-toast .bp-btn:hover{transform:translateY(-1px)}
      .bp-challenge-toast .bp-dismiss{position:absolute;top:8px;right:10px;color:#a89a87;
        cursor:pointer;font-size:18px;line-height:1;padding:4px 6px;text-decoration:none}
      .bp-challenge-toast .bp-dismiss:hover{color:#f5e8d8}
    `;
    document.head.appendChild(s);
  }

  // Already-shown duo IDs in this page lifetime (dedupe SSE bursts)
  const shown = new Set();

  function popToast(duo){
    if (shown.has(duo.id)) return;
    shown.add(duo.id);

    // Remove any existing toast first (stack one at a time for clarity)
    document.querySelectorAll('.bp-challenge-toast').forEach(n => n.remove());

    const challenger = duo.challenger || duo.from || '?';
    const prospect = duo.prospect_slug || duo.prospect || '?';
    const persona = duo.card_persona_name || '';
    const buyerLine = persona ? `${prospect} · ${persona}` : prospect;

    const toast = document.createElement('div');
    toast.className = 'bp-challenge-toast';

    const dismiss = document.createElement('a');
    dismiss.className = 'bp-dismiss';
    dismiss.href = '#';
    dismiss.textContent = '×';
    dismiss.addEventListener('click', (e) => { e.preventDefault(); toast.remove(); });
    toast.appendChild(dismiss);

    const label = document.createElement('div');
    label.className = 'bp-label';
    const pulse = document.createElement('span');
    pulse.className = 'pulse';
    label.appendChild(pulse);
    label.appendChild(document.createTextNode('1V1 CHALLENGE'));
    toast.appendChild(label);

    const title = document.createElement('div');
    title.className = 'bp-title';
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = challenger.toUpperCase();
    title.appendChild(who);
    title.appendChild(document.createTextNode(' wants to duel.'));
    toast.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'bp-meta';
    meta.textContent = '5-min sprint. You take the buyer side.';
    toast.appendChild(meta);

    const buyer = document.createElement('div');
    buyer.className = 'bp-buyer';
    buyer.textContent = '▶ ' + buyerLine;
    toast.appendChild(buyer);

    const actions = document.createElement('div');
    actions.className = 'bp-actions';

    const acceptBtn = document.createElement('a');
    acceptBtn.className = 'bp-btn accept';
    const acceptUrl = `/app/duo.html?b=${encodeURIComponent(BULLPEN)}&rep=${encodeURIComponent(REP)}&duo_id=${encodeURIComponent(duo.id)}`;
    acceptBtn.href = acceptUrl;
    acceptBtn.textContent = 'ACCEPT';
    actions.appendChild(acceptBtn);

    const declineBtn = document.createElement('button');
    declineBtn.className = 'bp-btn decline';
    declineBtn.textContent = 'DECLINE';
    declineBtn.addEventListener('click', async () => {
      toast.classList.add('declining');
      try {
        await fetch(`/api/b/${encodeURIComponent(BULLPEN)}/duos/${encodeURIComponent(duo.id)}/end`, {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({rep: REP, reason: 'declined'}),
        });
      } catch(e) {}
      toast.remove();
    });
    actions.appendChild(declineBtn);

    toast.appendChild(actions);
    document.body.appendChild(toast);

    // Auto-dismiss after 60s if untouched
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 60000);
  }

  async function checkPending(){
    try {
      const r = await fetch(`/api/b/${encodeURIComponent(BULLPEN)}/duos`, {credentials:'same-origin'});
      if (!r.ok) return;
      const data = await r.json();
      const duos = data.duos || data || [];
      for (const d of duos) {
        if (d.status === 'pending' && d.opponent === REP) {
          popToast(d);
        }
      }
    } catch(e) {}
  }

  function subscribeSSE(){
    try {
      const es = new EventSource(`/api/b/${encodeURIComponent(BULLPEN)}/stream`);
      es.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.kind !== 'duo_challenged') return;
          const payload = event.payload || {};
          if (payload.opponent !== REP) return;
          // Build the duo descriptor from the event payload + best-known fields
          popToast({
            id: event.target_id,
            challenger: event.actor,
            prospect_slug: payload.prospect,
            card_persona_name: payload.card_persona_name || '',
            status: 'pending',
            opponent: payload.opponent,
          });
        } catch(e) {}
      };
      es.onerror = () => {};
    } catch(e) {}
  }

  // Initial sweep + live subscription
  checkPending();
  subscribeSSE();
  // Also poll every 60s as a slow fallback
  setInterval(checkPending, 60000);
})();
