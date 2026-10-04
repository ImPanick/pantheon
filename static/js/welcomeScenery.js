// SPDX-License-Identifier: AGPL-3.0-or-later
// CSS animates the empty-chat scenery. Suspend it when the page is hidden.
const scenery = document.getElementById('welcome-scenery');

if (scenery) {
  const syncVisibility = () => {
    scenery.dataset.paused = String(document.hidden);
  };
  document.addEventListener('visibilitychange', syncVisibility);
  window.addEventListener('pagehide', () => { scenery.dataset.paused = 'true'; });
  window.addEventListener('pageshow', syncVisibility);
  syncVisibility();
}
