// loss-modal.js — shared "Mark lost" reason picker for BullpenLM floor pages.
// Exposes window.bpLossModal.open(onPick) which shows a small modal styled to
// match deal.html. On submit it calls onPick({reason, note}).
(function(){
  if (window.bpLossModal) return; // idempotent — don't redefine if already loaded

  const REASONS = [
    ['price',       'Price — too expensive'],
    ['timing',      'Timing — not now'],
    ['no_decision', 'No decision — stalled out'],
    ['competitor',  'Competitor won it'],
    ['no_budget',   'No budget'],
    ['bad_fit',     'Bad fit'],
    ['ghosted',     'Ghosted — went dark'],
    ['other',       'Other'],
  ];

  const STYLE_ID = 'bp-loss-modal-style';
  function injectStyle(){
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = `
.bp-loss-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.78);display:none;align-items:center;justify-content:center;z-index:200;font-family:"Switzer",-apple-system,sans-serif}
.bp-loss-overlay.open{display:flex}
.bp-loss-card{background:#2a1d10;border:1px solid rgba(248,113,113,0.35);border-radius:12px;padding:26px;max-width:480px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.7)}
.bp-loss-card h2{font-family:"Tanker",serif;font-size:26px;color:#f87171;margin:0 0 6px;text-transform:uppercase;letter-spacing:-.01em}
.bp-loss-card .bp-loss-sub{font-family:"Bespoke Serif",Georgia,serif;font-size:14px;color:#a89a87;margin:0 0 14px;line-height:1.4}
.bp-loss-card label{display:block;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#a89a87;margin:12px 0 5px}
.bp-loss-card select,.bp-loss-card textarea{width:100%;padding:10px 12px;background:rgba(0,0,0,0.30);border:1px solid rgba(245,232,216,0.15);border-radius:5px;color:#f5e8d8;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:12px;box-sizing:border-box}
.bp-loss-card textarea{font-family:"Bespoke Serif",Georgia,serif;font-size:14px;min-height:70px;resize:vertical}
.bp-loss-actions{display:flex;gap:10px;margin-top:18px;justify-content:flex-end}
.bp-loss-actions button{padding:10px 20px;border-radius:5px;border:none;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:700;cursor:pointer}
.bp-loss-actions .bp-loss-cancel{background:transparent;color:#a89a87;border:1px solid rgba(245,232,216,0.15)}
.bp-loss-actions .bp-loss-confirm{background:#f87171;color:#1a0707}
.bp-loss-actions .bp-loss-confirm:hover{background:#fca5a5}
`;
    document.head.appendChild(s);
  }

  let overlay = null;
  function build(){
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'bp-loss-overlay';
    overlay.id = 'bp-loss-overlay';

    const card = document.createElement('div');
    card.className = 'bp-loss-card';

    const h = document.createElement('h2');
    h.textContent = '✕ Mark lost';
    card.appendChild(h);

    const sub = document.createElement('p');
    sub.className = 'bp-loss-sub';
    sub.textContent = 'Log why this one slipped — it helps the floor learn.';
    card.appendChild(sub);

    const rLabel = document.createElement('label');
    rLabel.textContent = 'Reason';
    card.appendChild(rLabel);

    const sel = document.createElement('select');
    sel.id = 'bp-loss-reason';
    for (const [v, l] of REASONS){
      const op = document.createElement('option');
      op.value = v; op.textContent = l;
      sel.appendChild(op);
    }
    card.appendChild(sel);

    const nLabel = document.createElement('label');
    nLabel.textContent = 'Note (optional)';
    card.appendChild(nLabel);

    const note = document.createElement('textarea');
    note.id = 'bp-loss-note';
    note.placeholder = 'e.g. Went with incumbent on a 2-year renewal';
    card.appendChild(note);

    const actions = document.createElement('div');
    actions.className = 'bp-loss-actions';

    const cancel = document.createElement('button');
    cancel.className = 'bp-loss-cancel';
    cancel.type = 'button';
    cancel.textContent = 'Cancel';
    cancel.onclick = close;
    actions.appendChild(cancel);

    const confirm = document.createElement('button');
    confirm.className = 'bp-loss-confirm';
    confirm.type = 'button';
    confirm.textContent = 'Mark lost';
    confirm.id = 'bp-loss-confirm';
    actions.appendChild(confirm);

    card.appendChild(actions);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    return overlay;
  }

  function close(){
    if (overlay) overlay.classList.remove('open');
  }

  function open(onPick){
    injectStyle();
    build();
    const sel = document.getElementById('bp-loss-reason');
    const note = document.getElementById('bp-loss-note');
    const confirm = document.getElementById('bp-loss-confirm');
    sel.value = REASONS[0][0];
    note.value = '';
    // Re-bind to capture the current onPick callback.
    confirm.onclick = () => {
      const reason = sel.value;
      const noteVal = note.value.trim();
      close();
      if (typeof onPick === 'function') onPick({ reason, note: noteVal });
    };
    overlay.classList.add('open');
    setTimeout(() => sel.focus(), 50);
  }

  window.bpLossModal = { open, close };
})();
