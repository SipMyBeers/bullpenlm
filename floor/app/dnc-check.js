/**
 * DNC pre-claim check widget — drop into any page that has a phone
 * number visible (contact.html, deals.html). Injects a small badge
 * next to elements with [data-dnc-check="<phone>"] showing whether
 * the number is clear to dial right now.
 *
 * Auto-runs on DOMContentLoaded. Safe to re-run after content changes.
 *
 * Usage in HTML:
 *   <span data-dnc-check="5035550100" data-dnc-state="CA">503-555-0100</span>
 *
 * After mount, the span gets a sibling badge:
 *   <span class="dnc-badge dnc-ok">✓ CLEAR</span>   (or)
 *   <span class="dnc-badge dnc-bad">DNC: national list</span>
 */
(function(){
  const url = new URL(window.location.href);
  const BULLPEN = url.searchParams.get('b');
  if (!BULLPEN) return;

  // Inject style once
  if (!document.getElementById('bullpenlm-dnc-style')) {
    const s = document.createElement('style');
    s.id = 'bullpenlm-dnc-style';
    s.textContent = `
      .dnc-badge{display:inline-block;margin-left:6px;padding:2px 8px;border-radius:5px;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:700;vertical-align:middle}
      .dnc-ok{background:rgba(52,211,153,0.12);color:#6ee7b7;border:1px solid rgba(52,211,153,0.40)}
      .dnc-bad{background:rgba(248,113,113,0.08);color:#fda4a4;border:1px solid rgba(248,113,113,0.40)}
      .dnc-pending{background:rgba(168,154,135,0.10);color:#a89a87;border:1px solid rgba(168,154,135,0.30)}
    `;
    document.head.appendChild(s);
  }

  async function checkOne(node){
    const phone = node.getAttribute('data-dnc-check');
    const state = node.getAttribute('data-dnc-state') || '';
    if (!phone) return;
    // Skip if already badged adjacent
    if (node.nextElementSibling && node.nextElementSibling.classList && node.nextElementSibling.classList.contains('dnc-badge')) {
      node.nextElementSibling.remove();
    }
    const pending = document.createElement('span');
    pending.className = 'dnc-badge dnc-pending';
    pending.textContent = 'CHECKING';
    node.after(pending);
    try {
      const r = await fetch(`/api/b/${encodeURIComponent(BULLPEN)}/dnc/check?phone=${encodeURIComponent(phone)}&state=${encodeURIComponent(state)}`);
      const d = await r.json();
      const badge = document.createElement('span');
      badge.className = 'dnc-badge ' + (d.ok ? 'dnc-ok' : 'dnc-bad');
      if (d.ok) {
        badge.textContent = '✓ CLEAR';
      } else {
        const reason = (d.dnc && !d.dnc.ok && d.dnc.reason) || (d.hours && !d.hours.ok && d.hours.reason) || 'blocked';
        badge.textContent = 'DNC: ' + reason.toUpperCase().slice(0, 40);
      }
      pending.replaceWith(badge);
    } catch(e) {
      pending.textContent = '? UNKNOWN';
    }
  }

  function scan(){
    document.querySelectorAll('[data-dnc-check]:not([data-dnc-checked])').forEach(n => {
      n.setAttribute('data-dnc-checked', '1');
      checkOne(n);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  } else {
    scan();
  }
  // Periodically re-scan in case the page rendered new contacts via JS
  const obs = new MutationObserver(scan);
  obs.observe(document.body, {childList:true, subtree:true});
})();
