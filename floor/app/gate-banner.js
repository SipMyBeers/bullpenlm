/**
 * Closer gate banner — drop-in for any floor page.
 *
 * Renders a SINGLE-LINE strip at the top of <body> when the closer
 * isn't yet cleared for paid work. Tap to expand. Tone is friendly,
 * not alarmist — the practice product is fully usable behind the
 * gate, so the banner is a soft "unlock more" prompt, not a "LIVE
 * WORK LOCKED" wall.
 *
 * Usage:
 *   <script src="/app/gate-banner.js" defer></script>
 *
 * Auto-discovers `?b=<bullpen>&rep=<rep>` from window.location.
 *
 * Hidden for:
 *   - localhost (operator practicing on their own machine)
 *   - operator-reserved rep names ('self', 'operator', 'founder',
 *     'host', 'beers')
 *   - newcomer grace window — first 90 seconds on the floor, banner
 *     stays hidden so the very first impression isn't a yellow strip
 *     telling them what's broken
 *
 * Banner state persists across pages via localStorage key
 * `gate-banner-collapsed` — collapsed (the default) becomes their
 * preference unless they explicitly open it.
 */
(function(){
  const url = new URL(window.location.href);
  const BULLPEN = url.searchParams.get('b');
  const REP = url.searchParams.get('rep');

  const isLocalhost = ['localhost', '127.0.0.1', '::1', '0.0.0.0'].includes(window.location.hostname);
  const operatorReps = new Set(['self', 'operator', 'founder', 'host', 'beers']);

  if (!BULLPEN || !REP) return;
  if (isLocalhost) return;
  if (operatorReps.has((REP || '').toLowerCase())) return;

  // Newcomer grace: keep the banner hidden during the first 90s on the
  // floor so a brand-new friend doesn't see a yellow nag the moment
  // they land. They'll see it the next time they navigate.
  const GRACE_KEY = `gate-grace-${BULLPEN}-${REP}`;
  const GRACE_MS = 90 * 1000;
  try {
    let graceStart = parseInt(localStorage.getItem(GRACE_KEY) || '0', 10);
    if (!graceStart) {
      graceStart = Date.now();
      localStorage.setItem(GRACE_KEY, String(graceStart));
    }
    if (Date.now() - graceStart < GRACE_MS) return;
  } catch (e) { /* localStorage blocked — fall through */ }

  const labels = {
    operator_entity_not_set_up: 'Operator hasn\'t finished entity setup',
    closer_disclosure_not_accepted: 'Disclosure acknowledgment',
    closer_agreement_not_signed: 'Closer Agreement',
    closer_agreement_out_of_date: 'Closer Agreement (refresh — template updated)',
    w9_not_on_file: 'W-9 tax form',
    drill_certification_not_cleared: 'One Tier-3+ drill pass',
    jurisdiction_check_failed: 'Jurisdiction check',
    jurisdiction_check_unavailable: 'Jurisdiction check (unavailable)',
    dnc_scrub_failed: 'DNC scrub on this prospect',
    dnc_check_unavailable: 'DNC check (unavailable)',
    entity_check_failed: 'Entity check',
    gate_unavailable: 'Compliance check',
  };

  const COLLAPSE_KEY = 'gate-banner-expanded';
  function isExpanded(){
    try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch(e){ return false; }
  }
  function setExpanded(v){
    try { localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0'); } catch(e){}
  }

  function mountBanner(missing){
    let banner = document.getElementById('bullpenlm-gate-banner');
    if(!banner){
      banner = document.createElement('div');
      banner.id = 'bullpenlm-gate-banner';
      // Single thin line, no border-bottom slab. Soft amber not red.
      banner.style.cssText = [
        'position:sticky', 'top:0', 'z-index:99',
        'background:rgba(251,191,36,0.06)',
        'border-bottom:1px solid rgba(251,191,36,0.18)',
        'font-family:"JetBrains Mono",ui-monospace,Menlo,monospace',
        'font-size:11px', 'letter-spacing:.04em',
        'color:#fbbf24',
      ].join(';');
      document.body.insertBefore(banner, document.body.firstChild);
    }
    while(banner.firstChild) banner.removeChild(banner.firstChild);

    // ── Always-visible strip (single line) ────────────────────────
    const strip = document.createElement('div');
    strip.style.cssText = 'padding:7px 14px;display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none';
    strip.addEventListener('click', () => { setExpanded(!isExpanded()); renderDetail(); });

    const dot = document.createElement('span');
    dot.style.cssText = 'width:6px;height:6px;background:#fbbf24;border-radius:50%;flex-shrink:0';
    strip.appendChild(dot);

    const msg = document.createElement('span');
    msg.style.cssText = 'flex:1;min-width:0;color:#fbbf24;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    const itemCount = missing.length;
    msg.textContent = `Practice is free · ${itemCount} item${itemCount===1?'':'s'} to unlock paid work`;
    strip.appendChild(msg);

    const chev = document.createElement('span');
    chev.id = 'gate-banner-chev';
    chev.style.cssText = 'font-size:10px;color:#a89a87;flex-shrink:0';
    chev.textContent = isExpanded() ? '▴' : '▾';
    strip.appendChild(chev);

    banner.appendChild(strip);

    // ── Detail panel (expanded) ────────────────────────────────────
    const detail = document.createElement('div');
    detail.id = 'gate-banner-detail';
    detail.style.cssText = 'padding:0 14px 12px;display:none;flex-direction:column;gap:6px';
    banner.appendChild(detail);

    function renderDetail(){
      chev.textContent = isExpanded() ? '▴' : '▾';
      detail.style.display = isExpanded() ? 'flex' : 'none';
      if(!isExpanded()) return;
      while(detail.firstChild) detail.removeChild(detail.firstChild);
      const intro = document.createElement('div');
      intro.style.cssText = 'color:#a89a87;font-size:11px;line-height:1.45;margin-bottom:4px';
      intro.textContent = 'Drill, voice-chat, listen in, and post marketing are all open. To claim real prospects and earn commissions, knock these out:';
      detail.appendChild(intro);
      for(const m of missing){
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;color:#f5e8d8';
        const check = document.createElement('span');
        check.style.cssText = 'color:#a89a87';
        check.textContent = '○';
        row.appendChild(check);
        const text = document.createElement('span');
        text.textContent = labels[m] || m;
        row.appendChild(text);
        detail.appendChild(row);
      }
      const cta = document.createElement('a');
      cta.href = `/app/onboard/?b=${encodeURIComponent(BULLPEN)}&rep=${encodeURIComponent(REP)}`;
      cta.textContent = 'Get cleared →';
      cta.style.cssText = 'margin-top:8px;align-self:flex-start;background:#fbbf24;color:#0a1a14;padding:7px 14px;border-radius:5px;text-decoration:none;font-weight:700;letter-spacing:.10em;text-transform:uppercase;font-size:10px';
      detail.appendChild(cta);
    }
    renderDetail();
  }

  function dismount(){
    const banner = document.getElementById('bullpenlm-gate-banner');
    if(banner) banner.remove();
  }

  async function check(){
    try {
      const r = await fetch(`/api/b/${encodeURIComponent(BULLPEN)}/gate/${encodeURIComponent(REP)}`, {credentials:'same-origin'});
      if(!r.ok) return;
      const d = await r.json();
      if(d.ok) {
        dismount();
      } else {
        mountBanner(d.missing || []);
      }
    } catch (e) { /* network blip — leave existing banner alone */ }
  }

  check();
  setInterval(check, 60000);

  // SSE — recheck when any gate-affecting event fires
  const GATE_EVENT_KINDS = new Set([
    'doc_signed', 'doc_rendered', 'dual_sign',
    'w9_submitted',
    'closer_disclosure_accepted',
    'operator_tos_accepted',
    'classification_saved',
    'entity_set',
    'drill_passed', 'drill_attempt',
    'dnc_list_imported', 'dnc_internal_optout',
    'gate_refused',
  ]);
  try {
    const es = new EventSource(`/api/b/${encodeURIComponent(BULLPEN)}/stream`);
    es.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        const kind = event && event.kind;
        if(kind && GATE_EVENT_KINDS.has(kind)){
          clearTimeout(window.__bullpenlm_gate_recheck);
          window.__bullpenlm_gate_recheck = setTimeout(check, 400);
        }
      } catch(e){}
    };
    es.onerror = () => { /* slow poll fallback */ };
  } catch(e){}

  // Re-check after gate-affecting POSTs from the page itself
  const origFetch = window.fetch;
  window.fetch = async function(...args){
    const res = await origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url);
      if(url && /\/(legal\/sign|w9|disclosure\/accept|drill|gate)/.test(url)){
        setTimeout(check, 600);
      }
    } catch (e){}
    return res;
  };
})();
