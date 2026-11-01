---
name: build-a-web-page
description: Build a web page or frontend component that works for everyone: semantic HTML, CSS from tokens, mobile-first layout, every state handled, and checked by actually opening it.
version: 1.0.0
category: frontend
tags: [frontend, web, page, html, css, javascript, component, ui, react, vue, layout, responsive, build, implement, site]
requires_toolsets: [read_file, edit_file]
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Asked to build, implement or code a web page, site, frontend feature or UI component, or to turn a design or mockup into working HTML, CSS and JavaScript (or the project's framework).

## Procedure

1. Read the project first with `read_file`: its framework, its component and style files, its tokens or theme, and a similar existing component to copy the pattern from. Use what is there rather than adding a library.
2. Write the structure in semantic HTML: headings in order, `nav`, `main`, `button` for actions and `a` for navigation, `label` for every input, `alt` on meaningful images.
3. Style from tokens (CSS custom properties or the theme) rather than raw values, mobile first, with flex or grid and `gap`. No fixed widths that break under 360 px; no sideways scrolling.
4. Handle every state in code: loading, empty, error with a way to retry, very long text, many items, disabled and focus styles. Respect `prefers-reduced-motion` and the product's dark mode.
5. Keep behaviour simple: progressive enhancement where possible, no layout shift when data arrives, inputs keep their values after an error.
6. Make the edits with `edit_file`, in small steps that each still work.
7. Open the result and use it at a phone width and a desktop width, with the keyboard as well as the mouse, before saying it is done. If you cannot open it, say so and say exactly what was not seen.

## Pitfalls

- Clickable `div`s, missing labels and focus outlines removed.
- Hard-coded colours that break the dark theme.
- Only building the populated, happy state.
- Saying it works without having opened it.

## Verification

- The page was opened and used at two widths and by keyboard, every state from step 4 was seen, and nothing scrolls sideways.
