// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P26-04`. The Design window's starting points, in one place (`Law 7`): its
// cards and the + menu's *Design ›* both read this list. A leaf — it imports
// nothing — so anything may import it.
//
// Each start says what it makes and what its short brief asks: `asks` are the
// brief's fields beyond the two every start has (who it is for, what it shows).

export const STARTS = Object.freeze([
  Object.freeze({ id: 'document', label: 'Document', hint: 'Reports, briefs, print ready',
    makes: 'a document page, print ready (A4 and Letter)', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h6',
    asks: [{ key: 'length', label: 'How long', placeholder: 'One page, or about 4 pages' }] }),
  Object.freeze({ id: 'mockup', label: 'Mockup', hint: 'Static high-fidelity screens',
    makes: 'static high-fidelity screens', icon: 'M3 3h18v18H3zM3 9h18M9 21V9',
    asks: [{ key: 'screens', label: 'Which screens', placeholder: 'Sign in, the dashboard, settings' },
      { key: 'size', label: 'For what size', placeholder: 'Desktop 1440 wide, and a phone' }] }),
  Object.freeze({ id: 'prototype', label: 'Prototype', hint: 'Clickable working UI',
    makes: 'a clickable working prototype in HTML, CSS and a little JavaScript', icon: 'M5 3l14 9-6 1.5L10 20z',
    asks: [{ key: 'flow', label: 'What can be clicked through', placeholder: 'Sign up, then the first project' }] }),
  Object.freeze({ id: 'motion', label: 'Motion', hint: 'Animated intros and reels',
    makes: 'an animated piece in HTML and CSS animation', icon: 'M4 4h16v16H4zM10 9l5 3-5 3z',
    asks: [{ key: 'duration', label: 'How long', placeholder: 'About 8 seconds, looping' }] }),
  Object.freeze({ id: 'slides', label: 'Slides', hint: 'A deck to present',
    makes: 'a slide deck as HTML pages, one per slide', icon: 'M3 4h18v12H3zM8 20h8M12 16v4',
    asks: [{ key: 'count', label: 'How many slides', placeholder: 'About 8' }] }),
  Object.freeze({ id: 'dashboard', label: 'Dashboard', hint: 'Numbers at a glance',
    makes: 'a dashboard page with charts and stat tiles', icon: 'M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z',
    asks: [{ key: 'data', label: 'Which numbers', placeholder: 'Weekly sign-ups, revenue, churn' }] }),
]);

/** The message a brief becomes: what to make, for whom, showing what, in
 *  which design system — and where its files go, so the agent works in the
 *  project, not in the chat. */
export function briefMessage(start, answers, system, folder) {
  const a = answers || {};
  const lines = [`Design ${start.makes}.`];
  if (a.who) lines.push(`Who it is for: ${a.who}`);
  if (a.what) lines.push(`What it shows: ${a.what}`);
  (start.asks || []).forEach((q) => { if (a[q.key]) lines.push(`${q.label}: ${a[q.key]}`); });
  if (system) {
    const pal = (system.tokens && system.tokens.palette) || [];
    const t = (system.tokens && system.tokens.type) || {};
    lines.push('');
    lines.push(`Use the design system “${system.name}”${system.file ? ` — its tokens are in ${system.file}` : ''}: `
      + `${pal.map((c) => `${c.name} ${c.value} (${c.role})`).join(', ')}`
      + `${t.heading || t.body ? `; type ${[t.heading, t.body].filter(Boolean).join(' / ')}` : ''}`
      + `${system.tokens && system.tokens.voice ? `; voice: ${String(system.tokens.voice).replace(/[.\s]+$/, '')}` : ''}.`);
  }
  lines.push('');
  if (folder) {
    lines.push(`Write it in ${folder}/ in the workspace: the page is ${folder}/index.html, self-contained `
      + '(its CSS in a <style>, any script inline or beside it), with its colours, sizes and spacing as :root '
      + `CSS variables so they can be tweaked. Leave ${folder}/design.json and brief.md as they are. `
      + 'Say when the page is there.');
  } else {
    lines.push('Make it as files in the workspace, in its own folder under design/, and say which file to open.');
  }
  return lines.join('\n');
}

export default { STARTS, briefMessage };
