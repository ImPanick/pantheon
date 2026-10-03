// SPDX-License-Identifier: AGPL-3.0-or-later
// Settings modal lifecycle primitives.
//
// Panel-specific behavior belongs elsewhere. This module owns only the window
// shell: dragging/docking reset, close semantics, visibility animation, and the
// delegated link that opens the Persona editor over Settings.

import { makeWindowDraggable } from '../windowDrag.js';
import { clearDockSide } from '../modalSnap.js';
import backStack from '../backStack.js';

const _dragBound = new WeakSet();
const _closeBound = new WeakSet();
let _promptLinkBound = false;

export function bindSettingsDrag(modalEl) {
  if (!modalEl || _dragBound.has(modalEl)) return;

  const header = modalEl.querySelector('.modal-header');
  const content = modalEl.querySelector('.settings-modal-content');
  if (!header || !content) return;

  _dragBound.add(modalEl);
  makeWindowDraggable(modalEl, {
    content,
    header,
    skipSelector: 'button, input, select, .theme-opacity-wrap',
    enableDock: true,
  });
}

export function resetSettingsWindowPlacement(modalEl) {
  const content = modalEl?.querySelector('.settings-modal-content');
  if (!content) return;

  const hadLeft = modalEl.classList.contains('modal-left-docked');
  const hadRight = modalEl.classList.contains('modal-right-docked');
  modalEl.classList.remove('modal-left-docked', 'modal-right-docked');
  if (hadLeft) clearDockSide('left', modalEl);
  if (hadRight) clearDockSide('right', modalEl);

  if (content._leftDockNavObs) {
    try { content._leftDockNavObs.navObs && content._leftDockNavObs.navObs.disconnect(); } catch (_) {}
    try { window.removeEventListener('resize', content._leftDockNavObs.reanchor); } catch (_) {}
    delete content._leftDockNavObs;
  }

  delete content._preDockSnapshot;
  delete content._dockSide;
  delete content._dockSuspended;
  delete content.dataset._tilePreSnap;
  delete content.dataset._tileZone;

  [
    'position', 'left', 'top', 'right', 'bottom', 'margin', 'transform',
    'width', 'height', 'max-width', 'max-height', 'border-radius', 'transition',
  ].forEach(property => content.style.removeProperty(property));
}

export function bindOpenPromptModalLink({ getModal, closeSettings } = {}) {
  if (_promptLinkBound) return;
  _promptLinkBound = true;

  document.addEventListener('click', async event => {
    const link = event.target?.closest?.('[data-open-prompt-modal]');
    if (!link) return;
    event.preventDefault();

    // `P23-01` (Doc 2's Settings map). This closed Settings first, so *Edit
    // persona settings here →* left no way back. The persona editor opens over
    // Settings with `← Settings` in its header, and Settings waits beneath.
    const settingsModal = typeof getModal === 'function' ? getModal() : null;
    if (settingsModal && !settingsModal.classList.contains('hidden')) {
      backStack.noteOpener('custom-preset-modal', 'settings-modal');
    }

    try {
      const module = await import('../presets.js');
      const openPrompt = module.openCustomPresetModal
        || (module.default && module.default.openCustomPresetModal);
      if (typeof openPrompt === 'function') openPrompt();
    } catch (_) {
      const modal = document.getElementById('custom-preset-modal');
      if (modal) modal.classList.remove('hidden');
    }

    const personaTab = document.querySelector(
      '#custom-preset-modal .preset-tab[data-chartab="character"]'
    );
    if (personaTab) personaTab.click();
  });
}

export function bindSettingsClose(modalEl, options = {}) {
  if (!modalEl || _closeBound.has(modalEl)) return;
  _closeBound.add(modalEl);

  const closeSettings = options.closeSettings;
  const isTouchInsideModal = options.isTouchInsideModal;

  const closeButton = modalEl.querySelector('.close-btn');
  closeButton?.addEventListener('click', () => {
    if (typeof closeSettings === 'function') closeSettings();
  });

  modalEl.addEventListener('mousedown', event => {
    if (typeof isTouchInsideModal === 'function' && isTouchInsideModal()) return;
    if (event.target === modalEl && typeof closeSettings === 'function') {
      closeSettings();
    }
  });

  // `P23-01` (NAV-M-6). Settings kept its own `document` Escape listener; the
  // one arbiter in `ui.js` closes it now (through this close button), after the
  // Escape stack and after the popovers this listener used to check for, which
  // moved there (`peelInnerLayer`). With a text field focused this listener
  // closed Settings at once — the key that left SET-M-7's stale listener behind.
}

export function showSettingsModal(modalEl) {
  if (!modalEl) return;
  if (modalEl.classList.contains('hidden')) {
    resetSettingsWindowPlacement(modalEl);
  }
  // Opened again while the close was still animating: it stays open.
  modalEl.querySelector('.modal-content, .settings-modal-content')?.classList.remove('modal-closing');
  modalEl.classList.remove('hidden');
}

// `P23-01` (SET-M-7). The close used a `{ once: true }` `animationend`
// listener and a 250 ms timer, and whichever ran second was meant to find
// nothing to do. When the window was hidden without the exit animation playing
// (Escape from a field, a minimise and restore), the listener stayed armed and
// the NEXT open's `modal-enter` animation fired it: Settings opened and hid
// itself a quarter-second later (measured `[5418 animationend modal-enter]
// [5418 modal hidden]`). The listener answers only its own `modal-exit`, and
// whichever of the two runs first takes the other down.
export function hideSettingsModal(modalEl) {
  if (!modalEl) return;

  const content = modalEl.querySelector('.modal-content, .settings-modal-content');
  if (content && !content.classList.contains('modal-closing')) {
    content.classList.add('modal-closing');
    let timer = null;
    const finish = () => {
      content.removeEventListener('animationend', onEnd);
      clearTimeout(timer);
      // Opened again while it was closing: leave it open.
      if (!content.classList.contains('modal-closing')) return;
      modalEl.classList.add('hidden');
      content.classList.remove('modal-closing');
    };
    const onEnd = (e) => {
      if (e && e.target !== content) return;
      if (e && e.animationName && e.animationName !== 'modal-exit') return;
      finish();
    };
    content.addEventListener('animationend', onEnd);
    timer = setTimeout(finish, 250);
    return;
  }

  modalEl.classList.add('hidden');
}
