// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Print a standalone HTML document — the one way this client makes a PDF of
 * text (`B1320`, `B1333`).
 *
 * `window.print()` prints the page; a document to be printed is written into a
 * frame of its own and that frame prints, so what reaches "Save as PDF" is
 * real text: selectable, searchable, read by a screen reader, a few tens of KB.
 * The chat's PDF item (`B1320`) prints the server's whole-chat HTML this way;
 * a document's *Print as PDF* (`B1333`) prints the standalone HTML its *Export
 * HTML* builds. One frame, one set of rules: this was `app.js`'
 * `_printWholeChat` body, moved here so the two cannot drift (`Law 7`).
 *
 * Returns `false` when the frame could not be written or printed, so a caller
 * can fall back to whatever it did before.
 */
export async function printHtmlInFrame(html, { id = 'export-print-frame', title = '' } = {}) {
  document.getElementById(id)?.remove();
  const frame = document.createElement('iframe');
  frame.id = id;
  if (title) frame.title = title;
  frame.setAttribute('aria-hidden', 'true');
  // Off-screen rather than display:none — a frame with no box does not lay
  // out, and a frame that has not laid out prints blank.
  frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:816px;height:1056px;border:0;';
  document.body.appendChild(frame);
  const doc = frame.contentDocument;
  if (!doc) { frame.remove(); return false; }
  doc.open();
  doc.write(html);
  doc.close();
  // `B1333`: a picture still loading prints as an empty box. Wait for each
  // (or its failure) — briefly, so one that never answers cannot hold the
  // print back for good.
  const pending = Array.from(doc.images || []).filter((img) => !img.complete);
  if (pending.length) {
    await Promise.race([
      Promise.all(pending.map((img) => new Promise((resolve) => {
        img.addEventListener('load', resolve, { once: true });
        img.addEventListener('error', resolve, { once: true });
      }))),
      new Promise((resolve) => setTimeout(resolve, 5000)),
    ]);
  }
  const win = frame.contentWindow;
  const done = () => frame.remove();
  try {
    win.addEventListener('afterprint', done, { once: true });
    win.focus();
    win.print();
  } catch (err) {
    console.warn('Printing failed:', err);
    frame.remove();
    return false;
  }
  // Headless browsers and some print paths never fire `afterprint`; the
  // frame must not be left in the page either way.
  setTimeout(done, 60000);
  return true;
}
