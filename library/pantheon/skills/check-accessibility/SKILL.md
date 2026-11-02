---
name: check-accessibility
description: Check a page, screen or component for accessibility against WCAG AA: contrast, keyboard use, focus, labels, structure, motion and zoom, and report each problem with a fix.
version: 1.0.0
category: frontend
tags: [accessibility, a11y, wcag, contrast, keyboard, focus, screen, reader, aria, label, alt, qa, frontend, ui, audit]
requires_toolsets: []
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Asked to check accessibility or WCAG, as part of QA for any interface, or before shipping a page, form or component.

## Procedure

1. Contrast: body text at least 4.5 to 1 against its background, large text and meaningful icons and borders at least 3 to 1, in every theme the product ships.
2. Keyboard: everything a mouse can do is reachable with Tab, Shift+Tab, Enter, Space, Escape and the arrow keys; the order follows the reading order; nothing traps focus except an open dialog, which returns focus when it closes.
3. Focus: the focused element is always visibly marked.
4. Names: every control has an accessible name (visible label, `aria-label` only when there is no room for one); every input has a label tied to it; icon-only buttons say what they do; meaningful images have `alt`, decorative ones `alt=""`.
5. Structure: one `h1`, headings in order, landmarks (`header`, `nav`, `main`), lists as lists, tables with headers. Native elements before ARIA roles.
6. Errors and changes: form errors say what is wrong and how to fix it, next to the field and in text, not colour alone; changes that appear without a page load are announced.
7. Motion and zoom: nothing flashes; animation stops under reduced motion; the page works at 200 % zoom and 320 px wide with no sideways scrolling; touch targets at least 24 px, ideally 44.
8. Report each problem most severe first: where it is, who it stops, the WCAG criterion, and the fix.

## Pitfalls

- Checking only the default theme.
- Adding ARIA to fix what a native element would do on its own.
- Relying on colour alone for state, errors or links.

## Verification

- Each of the seven areas above has a result, and every problem found has a location and a fix.
