// SPDX-License-Identifier: AGPL-3.0-or-later
// getpantheon.ai page behaviour: the nav's rule once the page moves, the install tabs,
// and copy buttons that copy commands without their prompts.
(() => {
  "use strict";
  const root = document.documentElement;
  root.classList.add("js");

  // nav border once the page moves
  const nav = document.querySelector(".nav");
  const onScroll = () => {
    if (nav) nav.classList.toggle("scrolled", scrollY > 8);
  };

  addEventListener("scroll", onScroll, { passive: true });
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

})();
