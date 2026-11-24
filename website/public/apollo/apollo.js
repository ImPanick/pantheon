// SPDX-License-Identifier: AGPL-3.0-or-later
(() => {
  // Apollo's orb, ported from Pantheon's static/js/apolloOrb.js and apolloOrbModel.js:
  // the same moods, colours, periods and paint routine, drawn larger for the page.
  const LOOK = {
    idle:      { core: '#ffd27a', rim: '#f29e38', halo: 'rgba(255,190,90,', period: 4.2, amp: 0.06, swirl: 0,   ring: 0 },
    listening: { core: '#fff3d1', rim: '#ffc45c', halo: 'rgba(255,230,170,', period: 1.1, amp: 0.10, swirl: 0,   ring: 1 },
    thinking:  { core: '#ffe08a', rim: '#f5a524', halo: 'rgba(255,200,90,', period: 2.0, amp: 0.08, swirl: 1.6, ring: 0 },
    speaking:  { core: '#ffe9a8', rim: '#f7b13d', halo: 'rgba(255,214,120,', period: 0.9, amp: 0.12, swirl: 0.4, ring: 2 },
    needs:     { core: '#ffc04d', rim: '#e8700c', halo: 'rgba(255,150,40,', period: 1.6, amp: 0.12, swirl: 0,   ring: 0 },
  };
  const canvas = document.getElementById('orb');
  const c = canvas.getContext('2d');
  const SIZE = canvas.width;
  let still = false;
  try { still = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { still = false; }
  let mood = 'idle';
  const order = ['idle', 'listening', 'thinking', 'speaking', 'needs'];

  function glow(L, t) {
    if (still) return 1;
    if (mood === 'speaking') {
      // A stand-in for the voice level the real orb reads from the audio element.
      const level = 0.5 + 0.5 * Math.sin(t * 7.3) * Math.sin(t * 2.1 + 1);
      return 1 + Math.max(0, level) * L.amp * 2.2;
    }
    return 1 + Math.sin((t / L.period) * Math.PI * 2) * L.amp;
  }

  function paint(t) {
    const L = LOOK[mood];
    const g = glow(L, t);
    const mid = SIZE / 2;
    const r = SIZE * 0.2 * g;
    c.clearRect(0, 0, SIZE, SIZE);
    const halo = c.createRadialGradient(mid, mid, r * 0.6, mid, mid, SIZE * 0.48);
    halo.addColorStop(0, L.halo + '0.55)');
    halo.addColorStop(1, L.halo + '0)');
    c.fillStyle = halo;
    c.beginPath(); c.arc(mid, mid, SIZE * 0.48, 0, Math.PI * 2); c.fill();
    if (!still && L.ring) {
      for (let i = 0; i < L.ring; i += 1) {
        const p = ((t / L.period) + i / L.ring) % 1;
        c.strokeStyle = L.halo + (0.5 * (1 - p)).toFixed(3) + ')';
        c.lineWidth = 1.5 * SIZE / 56;
        c.beginPath(); c.arc(mid, mid, r * (1.1 + p * 1.1), 0, Math.PI * 2); c.stroke();
      }
    }
    const core = c.createRadialGradient(mid - r * 0.3, mid - r * 0.3, r * 0.1, mid, mid, r);
    core.addColorStop(0, '#fffbe8');
    core.addColorStop(0.45, L.core);
    core.addColorStop(1, L.rim);
    c.fillStyle = core;
    c.beginPath(); c.arc(mid, mid, r, 0, Math.PI * 2); c.fill();
    if (L.swirl) {
      const a0 = still ? 0 : t * L.swirl * Math.PI;
      c.strokeStyle = L.halo + '0.8)';
      c.lineWidth = 2 * SIZE / 56;
      c.lineCap = 'round';
      for (let i = 0; i < 3; i += 1) {
        const a = a0 + (i * Math.PI * 2) / 3;
        c.beginPath(); c.arc(mid, mid, r * 1.35, a, a + 0.9); c.stroke();
      }
    }
  }

  function tick(now) {
    paint(now / 1000);
    if (!still) requestAnimationFrame(tick);
  }

  const buttons = Array.from(document.querySelectorAll('.moods button'));
  function setMood(m) {
    mood = m;
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mood === m)));
    if (still) paint(0);
  }
  buttons.forEach((b) => b.addEventListener('click', () => setMood(b.dataset.mood)));
  canvas.addEventListener('click', () => setMood(order[(order.indexOf(mood) + 1) % order.length]));

  paint(0);
  if (!still) requestAnimationFrame(tick);
})();
