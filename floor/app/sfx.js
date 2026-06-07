/* sfx.js — BullpenLM WebAudio synth (no asset files).
 *
 * Exposes window.bpSfx with bell(), levelUp(), coin(), trophy(rarity).
 * All sounds are synthesized with oscillators (same approach as
 * wallboard.html's bellSound) so there are zero audio assets to ship.
 * Gated behind localStorage 'bp-sfx' (default ON). Also fires
 * navigator.vibrate() where supported for a little haptic punch.
 *
 * Usage:
 *   bpSfx.bell()            // close-won: bright bell-overtone stack
 *   bpSfx.levelUp()         // rising 3-note arpeggio
 *   bpSfx.coin()            // +XP / quest-claim blip
 *   bpSfx.trophy('epic')    // rarity-pitched chime
 *   bpSfx.isOn()  / bpSfx.setOn(true|false) / bpSfx.toggle()
 */
(function () {
  'use strict';

  // ── Enable gate (default ON) ──────────────────────────────────
  function isOn() {
    try { return localStorage.getItem('bp-sfx') !== 'off'; }
    catch (_) { return true; }
  }
  function setOn(on) {
    try { localStorage.setItem('bp-sfx', on ? 'on' : 'off'); } catch (_) {}
  }
  function toggle() { setOn(!isOn()); return isOn(); }

  // ── Lazy shared AudioContext ──────────────────────────────────
  // Created on first use so we don't trip autoplay policies before a
  // user gesture. Resumed defensively each play.
  let _ctx = null;
  function ctx() {
    if (_ctx) return _ctx;
    try {
      _ctx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (_) { _ctx = null; }
    return _ctx;
  }

  // ── Haptics ───────────────────────────────────────────────────
  function vibrate(pattern) {
    try {
      if (navigator && typeof navigator.vibrate === 'function') {
        navigator.vibrate(pattern);
      }
    } catch (_) {}
  }

  // ── One synthesized tone ──────────────────────────────────────
  // freq Hz, dur seconds, type wave, peak gain, delay seconds before start.
  function tone(c, freq, dur, type, peak, delay) {
    try {
      const t0 = c.currentTime + (delay || 0);
      const o = c.createOscillator();
      const g = c.createGain();
      o.connect(g); g.connect(c.destination);
      o.type = type || 'sine';
      o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(Math.max(0.001, peak || 0.3), t0 + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.start(t0);
      o.stop(t0 + dur + 0.02);
    } catch (_) {}
  }

  // ── bell() — close-won: bright bell-overtone stack ────────────
  // Fundamental + bell partials (octave, 12th, double-octave) layered
  // for a real campanile-ish ring. Mirrors wallboard.html bellSound but
  // richer + longer because this is the marquee celebration.
  function bell() {
    if (!isOn()) return;
    const c = ctx(); if (!c) return;
    try { if (c.state === 'suspended') c.resume(); } catch (_) {}
    // Bell partials relative to a 660Hz fundamental
    tone(c, 660,  1.6, 'sine', 0.45, 0.00);
    tone(c, 990,  1.4, 'sine', 0.30, 0.00);  // perfect 5th up (≈1.5x)
    tone(c, 1320, 1.2, 'sine', 0.24, 0.01);  // octave
    tone(c, 1980, 0.9, 'sine', 0.14, 0.02);  // 12th
    // A second strike for the "ring it twice" feel
    tone(c, 880,  1.0, 'sine', 0.32, 0.26);
    tone(c, 1760, 0.8, 'sine', 0.16, 0.27);
    vibrate([40, 60, 40]);
  }

  // ── levelUp() — rising 3-note arpeggio ────────────────────────
  // Major triad climb (C5-E5-G5-C6) on a triangle wave for a chiptune
  // "ding-ding-ding-DING" power-up.
  function levelUp() {
    if (!isOn()) return;
    const c = ctx(); if (!c) return;
    try { if (c.state === 'suspended') c.resume(); } catch (_) {}
    const notes = [523.25, 659.25, 783.99, 1046.50]; // C5 E5 G5 C6
    notes.forEach((f, i) => tone(c, f, 0.30, 'triangle', 0.34, i * 0.10));
    // Sparkle on top of the final note
    tone(c, 1568, 0.5, 'sine', 0.16, 0.30);
    vibrate([30, 40, 30, 40, 60]);
  }

  // ── coin() — +XP / quest-claim blip ───────────────────────────
  // Classic two-note coin pickup: quick low → high square blip.
  function coin() {
    if (!isOn()) return;
    const c = ctx(); if (!c) return;
    try { if (c.state === 'suspended') c.resume(); } catch (_) {}
    tone(c, 988,  0.08, 'square', 0.22, 0.00);  // B5
    tone(c, 1319, 0.18, 'square', 0.22, 0.07);  // E6
    vibrate(20);
  }

  // ── trophy(rarity) — rarity-pitched chime ─────────────────────
  // Higher base pitch + more shimmer the rarer the trophy. Legendary
  // gets a full sparkle cascade.
  function trophy(rarity) {
    if (!isOn()) return;
    const c = ctx(); if (!c) return;
    try { if (c.state === 'suspended') c.resume(); } catch (_) {}
    const r = (rarity || 'common').toLowerCase();
    // Base fundamental rises with rarity
    const base = ({ common: 523.25, rare: 659.25, epic: 783.99, legendary: 1046.50 })[r] || 523.25;
    tone(c, base,       0.6, 'sine', 0.34, 0.00);
    tone(c, base * 1.5, 0.5, 'sine', 0.22, 0.04);  // 5th shimmer
    tone(c, base * 2,   0.4, 'sine', 0.16, 0.08);  // octave
    if (r === 'epic' || r === 'legendary') {
      tone(c, base * 3, 0.5, 'triangle', 0.14, 0.16);
    }
    if (r === 'legendary') {
      // Sparkle cascade — descending high glints
      [2637, 2349, 2093, 1760].forEach((f, i) =>
        tone(c, f, 0.28, 'sine', 0.12, 0.30 + i * 0.07));
    }
    vibrate(r === 'legendary' ? [30, 40, 30, 40, 30, 40, 80] : [30, 50, 30]);
  }

  window.bpSfx = { bell, levelUp, coin, trophy, isOn, setOn, toggle, vibrate };
})();
