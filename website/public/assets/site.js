// SPDX-License-Identifier: AGPL-3.0-or-later
// getpantheon.ai page behaviour: nav state, install tabs, copy buttons, reveals,
// the product window that settles flat as you scroll, and the tile glow.
(() => {
  "use strict";
  const root = document.documentElement;
  root.classList.add("js");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // nav border once the page moves
  const nav = document.querySelector(".nav");
  const onScroll = () => {
    if (nav) nav.classList.toggle("scrolled", scrollY > 8);
    tilt();
  };

  // product window: tilted back at rest, flat by the time it is centred
  const win = document.getElementById("window");
  function tilt() {
    if (!win || reduced) return;
    const r = win.getBoundingClientRect();
    const vh = innerHeight || 800;
    const t = Math.min(1, Math.max(0, (vh - r.top) / (vh * 0.9)));
    const ease = 1 - Math.pow(1 - t, 3);
    win.style.transform = `rotateX(${(14 * (1 - ease)).toFixed(2)}deg) scale(${(0.96 + 0.04 * ease).toFixed(4)})`;
  }
  addEventListener("scroll", onScroll, { passive: true });
  addEventListener("resize", tilt, { passive: true });
  onScroll();

  // install tabs (WAI-ARIA tabs pattern)
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  function select(tab, focus) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
    if (focus) tab.focus();
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => select(t));
    t.addEventListener("keydown", (e) => {
      let j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      if (e.key === "Home") j = 0;
      if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); select(tabs[j], true); }
    });
  });
  // a Mac visitor lands on the macOS tab
  const plat = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  if (/mac/i.test(plat)) {
    const mac = document.getElementById("t-mac");
    if (mac) select(mac);
  }

  // copy buttons copy the commands, never the prompt glyphs
  document.querySelectorAll(".copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = btn.parentElement.querySelector("code");
      const clone = code.cloneNode(true);
      clone.querySelectorAll(".p").forEach((n) => n.remove());
      const text = clone.textContent.trim();
      const done = (label) => { btn.textContent = label; setTimeout(() => (btn.textContent = "Copy"), 1600); };
      try {
        await navigator.clipboard.writeText(text);
        done("Copied");
      } catch {
        const range = document.createRange();
        range.selectNodeContents(code);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        done("Selected");
      }
    });
  });

  // reveal: only what starts below the fold waits, so the first frame is complete
  if (!reduced && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.remove("pending"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    document.querySelectorAll(".reveal").forEach((el) => {
      if (el.getBoundingClientRect().top > innerHeight) { el.classList.add("pending"); io.observe(el); }
    });
  }

  // tiles follow the pointer with a soft light
  document.querySelectorAll(".tile").forEach((tile) => {
    tile.addEventListener("pointermove", (e) => {
      const r = tile.getBoundingClientRect();
      tile.style.setProperty("--mx", `${e.clientX - r.left}px`);
      tile.style.setProperty("--my", `${e.clientY - r.top}px`);
    });
  });
})();
