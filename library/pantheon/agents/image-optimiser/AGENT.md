---
id: image-optimiser
name: Image Optimiser
tagline: "Compresses and converts a site's images and reports the bytes saved — originals kept."
section: design
icon: image-down
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The images folder, inside your projects folder"}
triggers:
  - {on: hand}
tools: [bash, ls]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {execute_code: allow, read_workspace: allow, destructive: ask}
budget: {runs_per_day: 4, max_steps: 25, max_minutes: 30}
memory: none
---
Optimised copies go to optimised/ with the same names; originals are never replaced.

1. List the images. For each JPEG and PNG, write a WebP (`cwebp -q 80`) and a recompressed copy (`jpegoptim`/`oxipng` or ImageMagick), keeping the smaller that still looks right; resize anything wider than 2400 px.
2. Answer with the bytes before and after, per file and in total.
