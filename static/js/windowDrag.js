// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared window-drag helper. Replaces the duplicated mousedown / mousemove
// / mouseup + snap-to-top fullscreen + left/right edge dock patterns that
// were copy-pasted across calendar.js, tasks.js, gallery.js, emailLibrary.js,
// documentLibrary.js, theme.js. Behavior stays identical to the old per-file
// copies — each callsite provides its own enter/exit-fullscreen callbacks
// since the CSS class + inline styles differ per modal.
//
// API:
//   makeWindowDraggable(modal, { content, header, ...options })
//     modal:           the wrapping .modal element (or a standalone pane)
//     content:         the element being moved (usually .modal-content)
//     header:          the drag handle (usually .modal-header)
//     fsClass:         optional class name representing "fullscreen" state
//     onEnterFullscreen: optional () => void — called when cursor releases
//                        near the top edge (within SNAP_PX). Caller is
//                        responsible for adding fsClass + applying inline
//                        styles that produce the fullscreen layout.
//     onExitFullscreen:  optional (cx, cy) => void — called mid-drag when
//                        the cursor leaves the fullscreen "unsnap" band
//                        (down > UNSNAP_PX OR near either horizontal edge
//                        in dock-snap range). Caller restores windowed
//                        inline styles centered around the cursor.
//     skipSelector:    CSS selector for elements inside `header` whose
//                        clicks should NOT start a drag (close button,
//                        form fields, etc). Default: 'button, input, select'
//     onDragEnd:       optional (state) => void — fires after mouseup
//                        WHEN no snap was committed. state = { rect } so
//                        callers can persist the final position.
//     enableTouch:     bool — also wire touchstart/touchmove/touchend
//                        with the same drag (no fs/dock on touch). Default
//                        true on desktop, irrelevant on mobile (mobileSkip).
//     mobileSkip:      drag is disabled below this viewport width.
//                        Default 768. Set to 0 to never skip.
//     enableDock:      bool — enable left + right edge docks.
//                        Default true.
//     enableFullscreen: bool — enable top-edge fullscreen snap.
//                        Default true when onEnterFullscreen is supplied.
//
// `P10-06` / `B660`: every window wired here also gets a keyboard handle as
// the first control in its header — arrow keys move it, Shift + arrow keys
// resize it (see `_wireKeyboard` below).

import { makeEdgeDockController, clearRightDock } from './modalSnap.js';
import { makeWindowResizable } from './windowResize.js';

// `P10-06`. How far one arrow press moves or resizes a window: the step the
// three separators take (`P10-03`), so an arrow key means one distance
// everywhere in the window system.
const KEY_STEP = 16;
const KEY_DIRS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

const SNAP_PX = 6;        // cursor distance from top edge for fullscreen snap
const UNSNAP_PX = 24;     // cursor distance from top before fullscreen exits
const DOCK_EDGE_PX = 60;  // cursor distance from L/R edge to trigger dock
                          // exit while still in fullscreen state

// CSS-var lookup for the rail+sidebar width — used to decide where the
// "left edge" effectively is during a fullscreen drag-out (the cursor
// has to pass the rail to count as "near left").
function _leftNavWidth() {
  const rs = getComputedStyle(document.documentElement);
  const rail = parseInt(rs.getPropertyValue('--icon-rail-w') || '48', 10) || 0;
  const sb = parseInt(rs.getPropertyValue('--sidebar-w') || '0', 10) || 0;
  return rail + sb;
}

export function makeWindowDraggable(modal, options = {}) {
  const content = options.content;
  const header = options.header;
  if (!content || !header) return;
  const fsClass = options.fsClass || null;
  const onEnterFullscreen = options.onEnterFullscreen || null;
  const onExitFullscreen = options.onExitFullscreen || null;
  const enableFullscreen = false;
  const onDragEnd = options.onDragEnd || null;
  const onDragStart = options.onDragStart || null;
  const skipSelector = options.skipSelector || 'button, input, select';
  const mobileSkip = (typeof options.mobileSkip === 'number') ? options.mobileSkip : 768;
  const enableTouch = options.enableTouch !== false;
  const enableDock = options.enableDock !== false && !!modal;

  header.style.cursor = 'move';
  header.style.userSelect = 'none';

  // Edge/corner resize. Every draggable window also becomes resizable — the
  // same gesture a native desktop window uses (grab an edge or corner, drag).
  // Skipped on mobile (windows are full-screen sheets there) and while the
  // window is fullscreen-snapped or docked. Wired here so all ~12 callsites
  // get it without per-file changes.
  let resizer = null;
  if (options.enableResize !== false) {
    const _dockClasses = ['modal-right-docked', 'modal-left-docked'];
    resizer = makeWindowResizable(content, {
      modal,
      mobileSkip,
      minWidth: options.minWidth,
      minHeight: options.minHeight,
      isLocked: () => (fsClass && modal && modal.classList.contains(fsClass))
        || (modal && _dockClasses.some((c) => modal.classList.contains(c))),
      storageKey: options.resizeStorageKey
        || (modal && modal.id ? 'winsize-' + modal.id
          : (content.id ? 'winsize-' + content.id : null)),
    });
  }

  const rightDock = enableDock ? makeEdgeDockController(modal, 'right') : null;
  // Left dock is enabled by default too. modalSnap collapses the wide sidebar
  // and anchors the panel beside the icon rail, so it no longer collides with
  // the navigation. Callers can still pass enableLeftDock:false for a special
  // modal that should only dock right.
  const leftDock = (enableDock && options.enableLeftDock !== false) ? makeEdgeDockController(modal, 'left') : null;

  // Per-drag state, reset on mousedown.
  let dragging = false;
  let startX = 0, startY = 0;
  let startLeft = 0, startTop = 0;
  let snapHint = null;
  // Whether the pointer actually moved beyond a small threshold this drag.
  // Used to suppress the synthetic click the browser fires on mouseup —
  // header click handlers (e.g. "collapse expanded card / back to list")
  // would otherwise fire after a drag and collapse the modal contents.
  let movedDuringDrag = false;
  const MOVE_THRESHOLD = 4;

  const _showSnapHint = (on) => {
    // Top-edge fullscreen hint. Side hints come from the dock controllers.
    if (!on) {
      if (snapHint) { snapHint.remove(); snapHint = null; }
      return;
    }
    if (snapHint) return;
    snapHint = document.createElement('div');
    snapHint.className = 'modal-snap-hint';
    snapHint.style.cssText =
      'position:fixed;left:0;top:0;right:0;bottom:0;' +
      'background:color-mix(in srgb, var(--accent-primary, #60a5fa) 12%, transparent);' +
      'border:2px dashed color-mix(in srgb, var(--accent-primary, #60a5fa) 60%, transparent);' +
      'z-index:9998;pointer-events:none;';
    document.body.appendChild(snapHint);
  };

  const _enterFs = () => {
    if (!onEnterFullscreen) return;
    if (fsClass && modal && modal.classList.contains(fsClass)) return;
    onEnterFullscreen();
  };
  const _exitFs = (cx, cy) => {
    if (!onExitFullscreen) return;
    if (fsClass && modal && !modal.classList.contains(fsClass)) return;
    onExitFullscreen(cx, cy);
    // After exit, re-anchor the drag offsets to the new windowed rect so
    // the drag continues smoothly from the cursor's position.
    const r = content.getBoundingClientRect();
    startX = cx; startY = cy;
    startLeft = r.left; startTop = r.top;
  };

  const _isFullscreen = () => fsClass && modal && modal.classList.contains(fsClass);

  const _startDrag = (cx, cy) => {
    dragging = true;
    if (modal) modal.classList.add('modal-dragging');
    // Cancel any in-flight open animation so we don't pin a mid-animation
    // rect and then jump once the animation settles.
    try {
      content.getAnimations()
        .filter(a => a.playState !== 'finished')
        .forEach(a => a.cancel());
    } catch (_) {}
    const rect = content.getBoundingClientRect();
    if (onDragStart) {
      try { onDragStart({ rect, cx, cy }); } catch (_) {}
    }
    startX = cx; startY = cy;
    startLeft = rect.left; startTop = rect.top;
    // Pin position so the drag follows the cursor instead of fighting a
    // centering transform / margin. Inline styles win unless CSS uses
    // !important (the fullscreen rules do, by design).
    content.style.position = 'fixed';
    content.style.left = startLeft + 'px';
    content.style.top = startTop + 'px';
    content.style.transform = 'none';
    content.style.margin = '0';
  };

  const _onMove = (cx, cy) => {
    if (!dragging) return;
    // Fullscreen state: unsnap on drag-down or drag toward either horizontal
    // edge. Update dock hover immediately after exit so a fast release
    // commits the dock instead of dropping the modal mid-air.
    if (_isFullscreen()) {
      // Corner guard: ignore the side edges while the cursor is still in the
      // top fullscreen band, so dragging across the top corners keeps
      // fullscreen instead of flipping into a corner dock.
      const inTopBand = cy <= SNAP_PX;
      const nearRight = !inTopBand && (window.innerWidth - cx) <= DOCK_EDGE_PX;
      const nearLeft = !inTopBand && (cx - _leftNavWidth()) <= DOCK_EDGE_PX;
      // Dragging a fullscreen window to a SIDE edge → keep it fullscreen and
      // just arm the side-dock hint; releasing there docks it (handled in
      // _onEnd, which drops the fullscreen class). Previously this exited
      // fullscreen first, which re-CENTERED the window — so it looked like
      // it "centered instead of docking". Only a downward drag unsnaps to a
      // windowed (centered) modal.
      if (nearRight && rightDock) {
        if (leftDock) leftDock.release();
        rightDock.onMove(cx, cy);
        return;
      }
      if (nearLeft && leftDock) {
        if (rightDock) rightDock.release();
        leftDock.onMove(cx, cy);
        return;
      }
      if (cy > UNSNAP_PX) {
        _exitFs(cx, cy);
        if (rightDock) rightDock.onMove(cx, cy);
        if (leftDock) leftDock.onMove(cx, cy);
      } else {
        if (rightDock) rightDock.release();
        if (leftDock) leftDock.release();
      }
      return;
    }
    // Right-docked: pulling away from the right edge un-docks. Same for left.
    if (rightDock && modal && modal.classList.contains('modal-right-docked')) {
      if (rightDock.onMove(cx, cy)) {
        const r = content.getBoundingClientRect();
        startX = cx; startY = cy;
        startLeft = r.left; startTop = r.top;
      }
      return;
    }
    if (leftDock && modal && modal.classList.contains('modal-left-docked')) {
      if (leftDock.onMove(cx, cy)) {
        const r = content.getBoundingClientRect();
        startX = cx; startY = cy;
        startLeft = r.left; startTop = r.top;
      }
      return;
    }
    // Windowed: just follow the cursor.
    if (Math.abs(cx - startX) > MOVE_THRESHOLD || Math.abs(cy - startY) > MOVE_THRESHOLD) {
      movedDuringDrag = true;
    }
    content.style.left = (startLeft + cx - startX) + 'px';
    content.style.top = (startTop + cy - startY) + 'px';
    // Corner guard: in the top fullscreen band the side docks stay OFF, so a
    // top corner only ever snaps to fullscreen — never the corner hybrid.
    const inTopBand = cy <= SNAP_PX;
    _showSnapHint(enableFullscreen && inTopBand);
    if (inTopBand) {
      if (rightDock) rightDock.release();
      if (leftDock) leftDock.release();
    } else {
      if (rightDock) rightDock.onMove(cx, cy);
      if (leftDock) leftDock.onMove(cx, cy);
    }
  };

  const _onEnd = (cx, cy) => {
    if (!dragging) return;
    dragging = false;
    if (modal) modal.classList.remove('modal-dragging');
    _showSnapHint(false);
    // Top edge wins over side edges — fullscreen is the more common gesture.
    if (enableFullscreen && typeof cy === 'number' && cy <= SNAP_PX) {
      if (rightDock) rightDock.release();
      if (leftDock) leftDock.release();
      _enterFs();
      return;
    }
    if (rightDock && rightDock.hovering()) {
      if (leftDock) leftDock.release();
      if (fsClass && modal) modal.classList.remove(fsClass);  // dock takes over from fullscreen
      rightDock.commit();
      return;
    }
    if (leftDock && leftDock.hovering()) {
      if (rightDock) rightDock.release();
      if (fsClass && modal) modal.classList.remove(fsClass);
      leftDock.commit();
      return;
    }
    if (rightDock) rightDock.release();
    if (leftDock) leftDock.release();
    if (onDragEnd) {
      const r = content.getBoundingClientRect();
      try { onDragEnd({ rect: r }); } catch (_) {}
    }
  };

  header.addEventListener('mousedown', (e) => {
    if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
    if (skipSelector && e.target.closest(skipSelector)) return;
    e.preventDefault();
    movedDuringDrag = false;
    _startDrag(e.clientX, e.clientY);
    const onMove = (ev) => _onMove(ev.clientX, ev.clientY);
    const onUp = (ev) => {
      _onEnd(ev.clientX, ev.clientY);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      // If the pointer actually moved, swallow the synthetic click the
      // browser fires next — otherwise a header click handler (collapse
      // expanded card / "back to list") runs and undoes the drag intent.
      if (movedDuringDrag) {
        const swallow = (clickEv) => {
          clickEv.stopPropagation();
          clickEv.preventDefault();
        };
        header.addEventListener('click', swallow, { capture: true, once: true });
        // Safety: if no click fires (some browsers), drop the listener.
        setTimeout(() => header.removeEventListener('click', swallow, { capture: true }), 50);
      }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  if (enableTouch) {
    header.addEventListener('touchstart', (e) => {
      if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
      if (skipSelector && e.target.closest(skipSelector)) return;
      const t = e.touches[0];
      if (!t) return;
      movedDuringDrag = false;
      _startDrag(t.clientX, t.clientY);
      const onMove = (ev) => {
        const tt = ev.touches[0];
        if (tt) _onMove(tt.clientX, tt.clientY);
      };
      const onEnd = (ev) => {
        const tt = (ev.changedTouches && ev.changedTouches[0]) || null;
        _onEnd(tt ? tt.clientX : null, tt ? tt.clientY : null);
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend', onEnd);
        document.removeEventListener('touchcancel', onEnd);
      };
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onEnd);
      document.addEventListener('touchcancel', onEnd);
    }, { passive: true });
  }

  // ── The keyboard (`P10-06` / `B660`) ──────────────────────────────────────
  // Every move and resize above is a pointer drag. `P10-06` measured zero
  // keydown handlers between this file and `windowResize.js` on 2026-09-18,
  // and there were still zero on 2026-09-27: a keyboard could open a tool
  // window and close it, and never get it out of the way of what was under
  // it. So the header gets a real button as its FIRST control — the first
  // stop inside the window, and the one `a11y.js` hands the focus to when the
  // window was opened from the keyboard. It is not painted until it has the
  // focus, when it shows what it does, so nothing changes for a mouse.
  //
  //   * an arrow key moves the window 16px, kept whole on the screen — a
  //     keyboard cannot drag back a title bar it pushed off the edge;
  //   * Shift + an arrow key resizes it from the right and bottom edges,
  //     through `windowResize.js`, so a size set this way persists as a
  //     dragged one does. A window wired with `enableResize: false` has no
  //     resize, and its handle does not offer one;
  //   * a docked window is un-docked by the first arrow, as dragging it off
  //     the edge does, and moves from where it was before it docked.
  //
  // Both report through the same `onDragStart`/`onDragEnd` a drag does, so a
  // caller that saves its position (the Library) saves this one too.
  _wireKeyboard();

  function _docked() {
    return !!(modal && (modal.classList.contains('modal-right-docked')
      || modal.classList.contains('modal-left-docked')));
  }

  function _keyMove(dx, dy) {
    if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return false;
    if (_isFullscreen()) return false;
    if (_docked()) {
      try { clearRightDock(modal); } catch (_) {}
    }
    if (onDragStart) {
      const rect = content.getBoundingClientRect();
      try { onDragStart({ rect, cx: rect.left, cy: rect.top }); } catch (_) {}
    }
    try {
      content.getAnimations()
        .filter(a => a.playState !== 'finished')
        .forEach(a => a.cancel());
    } catch (_) {}
    const r = content.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const left = Math.max(0, Math.min(r.left + dx, vw - r.width));
    const top = Math.max(0, Math.min(r.top + dy, vh - r.height));
    content.style.position = 'fixed';
    content.style.left = left + 'px';
    content.style.top = top + 'px';
    content.style.transform = 'none';
    content.style.margin = '0';
    if (onDragEnd) {
      try { onDragEnd({ rect: content.getBoundingClientRect() }); } catch (_) {}
    }
    return true;
  }

  function _wireKeyboard() {
    // Wired once per header. The guard is its own attribute: `a11y.js` finds
    // windows by `[data-window-keys]`, and a header carrying that too would
    // count as a window of its own.
    if (header.dataset.windowKeysWired === '1') return;
    header.dataset.windowKeysWired = '1';
    content.setAttribute('data-window-keys', '');
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'window-move-handle';
    handle.textContent = resizer
      ? 'Move: arrow keys · Resize: Shift + arrows'
      : 'Move: arrow keys';
    // The chip is positioned inside the header; a header that is not a
    // positioned box would place it against the window instead.
    try {
      if (getComputedStyle(header).position === 'static') header.style.position = 'relative';
    } catch (_) {}
    header.insertBefore(handle, header.firstChild);
    // A header's own click handler (Library's "back to the list") must not
    // run because Enter was pressed on the handle.
    handle.addEventListener('click', (e) => { e.stopPropagation(); });
    handle.addEventListener('keydown', (e) => {
      const dir = KEY_DIRS[e.key];
      if (!dir || e.altKey || e.ctrlKey || e.metaKey) return;
      const done = e.shiftKey
        ? !!(resizer && resizer.resizeBy(dir[0] * KEY_STEP, dir[1] * KEY_STEP))
        : _keyMove(dir[0] * KEY_STEP, dir[1] * KEY_STEP);
      if (done) e.preventDefault();
    });
  }
}
