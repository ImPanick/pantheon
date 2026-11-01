---
name: design-a-web-interface
description: Design a web page, app screen or component that looks deliberate: start from the reader and the one job, set hierarchy, type, spacing and colour tokens, design every state, and keep it calm.
version: 1.0.0
category: frontend
tags: [frontend, design, ui, ux, web, interface, layout, landing, page, dashboard, component, visual, typography, colour, color, theme, css]
requires_toolsets: []
status: published
confidence: 0.95
source: pantheon
---

## When to Use

Asked to design, redesign, restyle or polish a web page, site, dashboard, app screen or component, or to make an interface look less generic, more modern or more professional.

## Procedure

1. Name the reader and the one job of the screen in a sentence each. Everything on it either serves that job or goes lower down or away.
2. Read what already exists: the product's colours, fonts, components and tone. Match an existing design system before inventing one; say so if you depart from it.
3. Lay out the hierarchy first in plain blocks: what is seen first, second and third. One primary action per screen, visually stronger than everything else.
4. Set tokens before styling anything: a type scale of four to six sizes, a spacing scale (for example 4, 8, 12, 16, 24, 32, 48), two or three surface colours, one accent, text and muted text, borders, radius and shadow. Define them for light and dark if the product has both, and check text contrast is at least 4.5 to 1.
5. Design every state, not only the full one: empty, loading, error, a long name, a hundred rows, no permission, hover, focus, pressed, disabled.
6. Make it hold at a phone width (360 px) and a wide desktop: stack, do not shrink; no sideways scrolling; touch targets at least 44 px.
7. Keep motion short and purposeful (150 to 250 ms, ease-out), only to show change, and none when the reader asks for reduced motion.
8. Present the design with a short note per decision: what it is for and what it replaced. Offer one alternative direction only when the choice is genuinely open.

## Pitfalls

- Decoration before hierarchy: gradients, glass and glow on a screen whose main action is not obvious.
- A dozen font sizes and colours picked by eye instead of a few tokens.
- Designing only the happy, full state.
- Text on images or tinted surfaces without checking contrast.

## Verification

- A stranger can say what the screen is for and where to click first within five seconds, and every state from step 5 has a design.
