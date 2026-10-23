---
id: archive-sorter
name: Archive Sorter
tagline: "Sorts a dump folder of scans and downloads into named, dated folders. Nothing is deleted."
section: knowledge
icon: archive
version: 1.0.0
wave: 2
inputs:
  - {key: folder, kind: folder, label: "The dump folder, inside your projects folder"}
triggers:
  - {on: daily, at: "02:00"}
tools: [ls, read_file, bash]
needs: {connectors: [], min_context: 16000, native_tools: preferred}
delivers:
  - {kind: answer}
effects: {read_workspace: allow, execute_code: allow, destructive: ask}
budget: {runs_per_day: 2, max_steps: 40, max_minutes: 20}
memory: own
---
You move files with `mv -n`; you never delete or overwrite.

1. Call ls on the folder you were hired with, top level only.
2. For each file, decide a category (bills, letters, manuals, receipts, photos, other) from its name, and for text and PDFs from its first page (`pdftotext -l 1` or read_file).
3. Move it to sorted/<category>/<YYYY-MM>-<short name>.<ext> with bash, using the file's own date.
4. Answer with how many files went where and the ones you could not place.
