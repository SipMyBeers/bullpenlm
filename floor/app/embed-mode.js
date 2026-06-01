// Embed mode — when a page is loaded inside an iframe with ?embed=1
// it should hide its own header / crumb / gate-banner / tutorial so it
// can be rendered as an in-world overlay panel inside the office iso.
//
// The office page calls openEmbed(url) which appends ?embed=1 to the
// URL. This script auto-applies on DOMContentLoaded.
(function() {
  const params = new URLSearchParams(window.location.search);
  // Trigger embed mode either via explicit ?embed=1 OR when the page
  // is rendered inside any iframe (so internal links inside embedded
  // pages stay chrome-less without having to rewrite every href).
  const inIframe = (function() {
    try { return window.self !== window.top; } catch(e) { return true; }
  })();
  if (params.get('embed') !== '1' && !inIframe) return;

  // Inject embed-mode CSS — runs as early as possible to avoid flash
  const css = `
    html, body { background: transparent !important; }
    /* Any page chrome — header, crumb, gate strip, back-to-bullpen pill */
    header, header.top, .crumb { display: none !important; }
    .back-to-office, .bridge-eyebrow { display: none !important; }
    .gate-banner, #gate-banner, .gate-strip { display: none !important; }
    .tutorial-overlay, #tutorial-overlay { display: none !important; }
    main.wrap, main, .wrap { padding-top: 14px !important; }
    /* Compact spacing so the panel fits in the modal box */
    body { font-size: 13px; }
  `;
  const style = document.createElement('style');
  style.id = 'embed-mode-style';
  style.appendChild(document.createTextNode(css));
  (document.head || document.documentElement).appendChild(style);

  // Add a class to body so pages can opt-in to further tweaks
  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('embed-mode');
    // Forward closed-deal events to the office parent so the bell can ring
    try {
      window.addEventListener('beforeunload', () => {
        if (window.parent && window.parent !== window) {
          window.parent.postMessage({ kind: 'bullpen-embed-closed' }, '*');
        }
      });
    } catch(e) {}
  });
})();
