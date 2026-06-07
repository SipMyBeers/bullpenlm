/* BullpenLM — money feel. Cash renders as actual currency; earning money
 * fires a money printer that ejects bills. No emojis, no image assets —
 * pure CSS/SVG so it stays crisp and ours. Optional: uses window.bpSfx.
 *
 *   window.bpMoney.fmt(4950)            -> "$4,950"
 *   window.bpMoney.cashChip(4950)       -> a styled cash <span> (green, $, microtext)
 *   window.bpMoney.printer(4950, {label:"COMMISSION"})  -> prints the bills, then a +$ readout
 */
(function () {
  if (window.bpMoney) return;

  // ── one-time styles ──────────────────────────────────────────────────
  var css = document.createElement('style');
  css.textContent = [
    // a single bill — layered gradients give it printed-currency texture
    '.bp-bill{position:relative;display:inline-flex;align-items:center;justify-content:center;',
    '  font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-weight:700;color:#0a3d2c;',
    '  background:',
    '    repeating-linear-gradient(135deg,rgba(6,78,59,.05) 0 6px,transparent 6px 12px),',
    '    radial-gradient(circle at 50% 50%,rgba(255,255,255,.18),transparent 60%),',
    '    linear-gradient(160deg,#7bdcad,#3faf81 45%,#2e8c66);',
    '  border:1px solid #0a3d2c;border-radius:4px;box-shadow:inset 0 0 0 2px rgba(10,61,44,.25),inset 0 0 12px rgba(255,255,255,.25),0 2px 6px rgba(0,0,0,.4);}',
    '.bp-bill .bp-bill-amt{font-size:13px;letter-spacing:.02em;text-shadow:0 1px 0 rgba(255,255,255,.35);}',
    '.bp-bill .bp-bill-seal{position:absolute;left:5px;top:50%;transform:translateY(-50%);width:14px;height:14px;border:1.5px solid rgba(10,61,44,.55);border-radius:50%;}',
    '.bp-bill .bp-bill-corner{position:absolute;right:4px;bottom:2px;font-size:6.5px;letter-spacing:.14em;color:rgba(10,61,44,.6);}',
    // inline cash chip (for ledgers / readouts)
    '.bp-cash{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-weight:700;',
    '  color:#6ee7b7;letter-spacing:.01em;text-shadow:0 0 10px rgba(52,211,153,.35);white-space:nowrap;}',
    // printer overlay
    '.bp-printer-wrap{position:fixed;inset:0;z-index:120;display:flex;align-items:center;justify-content:center;pointer-events:none;}',
    '.bp-printer{position:relative;width:240px;}',
    '.bp-printer .body{height:74px;border-radius:12px;background:linear-gradient(180deg,#2a2018,#15100a);',
    '  border:1px solid #3d2c1a;box-shadow:0 14px 40px rgba(0,0,0,.6),inset 0 1px 0 rgba(245,232,216,.08);position:relative;z-index:2;}',
    '.bp-printer .slot{position:absolute;left:18px;right:18px;top:14px;height:5px;border-radius:3px;background:#05030a;box-shadow:inset 0 2px 4px rgba(0,0,0,.8);}',
    '.bp-printer .led{position:absolute;right:16px;bottom:12px;width:7px;height:7px;border-radius:50%;background:#34d399;box-shadow:0 0 8px #34d399;animation:bp-led .5s steps(2) infinite;}',
    '.bp-printer .lbl{position:absolute;left:16px;bottom:10px;font-family:"JetBrains Mono",monospace;font-size:8.5px;letter-spacing:.22em;color:#a89a87;text-transform:uppercase;}',
    '.bp-printer .stage{position:absolute;left:0;right:0;top:6px;height:0;display:flex;flex-direction:column-reverse;align-items:center;z-index:1;}',
    '.bp-printer .stage .bp-bill{width:160px;height:30px;margin-top:-22px;}',
    '.bp-printer .total{position:absolute;left:0;right:0;top:90px;text-align:center;font-family:"Tanker",serif;',
    '  font-size:40px;color:#6ee7b7;text-shadow:0 0 22px rgba(52,211,153,.6),0 6px 24px rgba(0,0,0,.6);opacity:0;transform:translateY(8px);}',
    '.bp-printer .total .sub{display:block;font-family:"JetBrains Mono",monospace;font-size:10px;letter-spacing:.24em;color:#a89a87;text-transform:uppercase;margin-top:2px;text-shadow:none;}',
    '@keyframes bp-led{0%{opacity:1}100%{opacity:.25}}',
    '@keyframes bp-eject{0%{transform:translateY(0) rotate(0);opacity:0}',
    '  20%{opacity:1}100%{transform:translateY(-46px) rotate(var(--bp-rot));opacity:1}}',
    '@keyframes bp-shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-1.5px)}75%{transform:translateX(1.5px)}}',
    '@keyframes bp-total-in{to{opacity:1;transform:translateY(0)}}',
  ].join('');
  document.head.appendChild(css);

  function fmt(n) {
    n = Math.round(Number(n) || 0);
    var s = Math.abs(n).toLocaleString('en-US');
    return (n < 0 ? '-$' : '$') + s;
  }

  function bill(amount, wide) {
    var b = document.createElement('span');
    b.className = 'bp-bill';
    if (wide) { b.style.width = '160px'; b.style.height = '30px'; }
    b.innerHTML = '<span class="bp-bill-seal"></span>' +
                  '<span class="bp-bill-amt">' + fmt(amount) + '</span>' +
                  '<span class="bp-bill-corner">BULLPEN RESERVE</span>';
    return b;
  }

  function cashChip(amount) {
    var s = document.createElement('span');
    s.className = 'bp-cash';
    s.textContent = fmt(amount);
    return s;
  }

  // Print the money. amount -> a small stack of bills ejecting, then the total.
  function printer(amount, opts) {
    amount = Math.round(Number(amount) || 0);
    if (amount <= 0) return;
    opts = opts || {};
    var wrap = document.createElement('div');
    wrap.className = 'bp-printer-wrap';
    var p = document.createElement('div');
    p.className = 'bp-printer';
    var stage = document.createElement('div');
    stage.className = 'stage';
    var body = document.createElement('div');
    body.className = 'body';
    body.innerHTML = '<div class="slot"></div><div class="led"></div>' +
                     '<div class="lbl">' + (opts.label || 'Bullpen Reserve') + '</div>';
    var total = document.createElement('div');
    total.className = 'total';
    total.innerHTML = fmt(amount) + '<span class="sub">' + (opts.sub || 'cash in') + '</span>';
    p.appendChild(stage); p.appendChild(body); p.appendChild(total);
    wrap.appendChild(p);
    document.body.appendChild(wrap);

    // eject N bills (cap the count; denominations are flavor)
    var n = Math.max(3, Math.min(7, Math.round(amount / 1500) + 3));
    var per = Math.max(1, Math.round(amount / n));
    body.style.animation = 'bp-shake .12s linear ' + n + ', none';
    for (var i = 0; i < n; i++) {
      (function (i) {
        setTimeout(function () {
          var b = bill(per, true);
          b.style.setProperty('--bp-rot', (Math.round((i % 2 ? 1 : -1) * (2 + i)) ) + 'deg');
          b.style.animation = 'bp-eject .42s cubic-bezier(.2,.9,.3,1) forwards';
          stage.appendChild(b);
          if (window.bpSfx && window.bpSfx.coin) { try { window.bpSfx.coin(); } catch (e) {} }
        }, 90 + i * 110);
      })(i);
    }
    setTimeout(function () {
      total.style.animation = 'bp-total-in .4s ease-out forwards';
      if (window.bpSfx && window.bpSfx.bell) { try { window.bpSfx.bell(); } catch (e) {} }
    }, 90 + n * 110 + 120);
    setTimeout(function () {
      wrap.style.transition = 'opacity .5s'; wrap.style.opacity = '0';
      setTimeout(function () { wrap.remove(); }, 520);
    }, 90 + n * 110 + 1900);
  }

  window.bpMoney = { fmt: fmt, cashChip: cashChip, bill: bill, printer: printer };
})();
