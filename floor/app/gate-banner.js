/**
 * Closer gate banner — drop-in for any floor page.
 *
 * Polls /api/b/<bullpen>/gate/<rep> on load + every 60s. If the gate
 * is not green, mounts a sticky banner at the top of <body> showing
 * what's missing + a "Complete onboarding" CTA. Hides itself once the
 * gate is green.
 *
 * Usage:
 *   <script src="/app/gate-banner.js" defer></script>
 *
 * The script auto-discovers `?b=<bullpen>&rep=<rep>` from window.location
 * (the floor pages already pass these). If either is missing, the banner
 * stays dormant.
 *
 * Operators viewing their own floor (rep === 'self' or rep matches
 * operator entity) see no banner — the gate is a closer-side concern.
 */
(function(){
  const url = new URL(window.location.href);
  const BULLPEN = url.searchParams.get('b');
  const REP = url.searchParams.get('rep');
  if (!BULLPEN || !REP || REP === 'self' || REP === 'operator' || REP === 'founder') return;

  const labels = {
    operator_entity_not_set_up: 'Operator entity not set up',
    closer_disclosure_not_accepted: 'Disclosure not accepted',
    closer_agreement_not_signed: 'Closer Agreement not signed',
    closer_agreement_out_of_date: 'Closer Agreement out of date (template changed)',
    w9_not_on_file: 'W-9 not submitted',
    drill_certification_not_cleared: 'Drill certification not cleared (pass a Tier-3+ drill)',
    jurisdiction_check_failed: 'Jurisdiction compliance check failed',
    jurisdiction_check_unavailable: 'Jurisdiction check unavailable',
    dnc_scrub_failed: 'DNC scrub on this prospect',
    dnc_check_unavailable: 'DNC check unavailable',
    entity_check_failed: 'Entity check failed',
    gate_unavailable: 'Gate module unavailable',
  };

  function mountBanner(missing){
    let banner = document.getElementById('bullpenlm-gate-banner');
    if(!banner){
      banner = document.createElement('div');
      banner.id = 'bullpenlm-gate-banner';
      banner.style.cssText = 'position:sticky;top:0;z-index:99;background:rgba(248,113,113,0.10);border-bottom:1px solid rgba(248,113,113,0.40);padding:10px 18px;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:12px;letter-spacing:.04em;color:#fda4a4;display:flex;align-items:center;gap:14px;flex-wrap:wrap';
      document.body.insertBefore(banner, document.body.firstChild);
    }
    while(banner.firstChild) banner.removeChild(banner.firstChild);

    const lock = document.createElement('span');
    lock.textContent = '⛔';
    lock.style.fontSize = '14px';
    banner.appendChild(lock);

    const msg = document.createElement('span');
    msg.style.color = '#fda4a4';
    msg.textContent = 'Live work locked — ' + (missing.length === 1 ? '1 item missing:' : `${missing.length} items missing:`);
    banner.appendChild(msg);

    const list = document.createElement('span');
    list.style.color = '#a89a87';
    const labelled = missing.map(m => labels[m] || m).slice(0, 3);
    list.textContent = labelled.join(' · ') + (missing.length > 3 ? ` (+${missing.length - 3} more)` : '');
    banner.appendChild(list);

    const cta = document.createElement('a');
    cta.href = `/app/onboard/?b=${encodeURIComponent(BULLPEN)}&rep=${encodeURIComponent(REP)}`;
    cta.textContent = 'Complete onboarding →';
    cta.style.cssText = 'margin-left:auto;background:#34d399;color:#0a1a14;padding:5px 12px;border-radius:5px;text-decoration:none;font-weight:700;letter-spacing:.10em;text-transform:uppercase;font-size:10px';
    banner.appendChild(cta);
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
    } catch (e) {
      // Network blip — leave existing banner state alone.
    }
  }

  check();
  // Slow poll as a fallback; SSE handles the fast path.
  setInterval(check, 60000);

  // Subscribe to the bullpen audit stream — recheck the gate whenever any
  // event that could flip our status fires. Far less load than polling and
  // updates instantly when the operator signs an agreement on the closer's
  // behalf or the closer passes a cert-tier drill.
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
          // Small debounce so a burst of related events triggers one check
          clearTimeout(window.__bullpenlm_gate_recheck);
          window.__bullpenlm_gate_recheck = setTimeout(check, 400);
        }
      } catch(e){}
    };
    es.onerror = () => { /* let the slow poll cover it */ };
  } catch(e){
    // Older browser / no SSE — slow poll is enough.
  }

  // Also re-check after any state-changing POST from the same page (e.g.
  // submitting the W-9 form from /app/onboard/). Hooks into global fetch.
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
