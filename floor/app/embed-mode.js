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
  const slim = params.get('slim') === '1';
  const css = `
    html, body { background: transparent !important; }
    /* Any page chrome — header, crumb, gate strip, back-to-bullpen pill */
    header, header.top, .crumb { display: none !important; }
    .back-to-office, .bridge-eyebrow { display: none !important; }
    .gate-banner, #gate-banner, .gate-strip { display: none !important; }
    .tutorial-overlay, #tutorial-overlay { display: none !important; }
    main.wrap, main, .wrap { padding-top: 14px !important; max-width: 100% !important; }
    body { font-size: 13px; }
    ${slim ? `
      /* SLIM mode — used by office.html mode-tab embeds (FLOOR/OUTREACH).
         Strip secondary panels, big banners, footer, marketing copy. */
      .marketing-banner, .promo, .upgrade-banner,
      .ad-creative-engine, .hero, .footer, footer { display: none !important; }
      .grid-3, .grid-4 { gap: 12px !important; }
      .stat-card, .panel { padding: 14px !important; }
      h1 { font-size: 26px !important; margin-bottom: 8px !important; }
      h2 { font-size: 14px !important; }
      .lede, .sub, .blurb { font-size: 12.5px !important; line-height:1.4 !important; }
      /* Tighten the kanban/pipeline grid so 5+ columns fit */
      .kanban, .pipeline, .stages { gap: 6px !important; }
      .kanban-col, .stage-col, .pipeline-col { min-width: 0 !important; padding: 10px !important; }
      /* Make sure the iframe's body scrolls internally — and leave
         padding at the bottom so the last row isn't kissed by the edge */
      html, body { height: 100% !important; overflow: auto !important; }
      main.wrap, main, .wrap { padding-bottom: 80px !important; }
    ` : ''}
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
