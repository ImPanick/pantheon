# Credits

Pantheon stands on a great deal of other people's work. This file credits the
projects whose code, assets or design are included in or adapted by this
repository, and notes their licences.

If something here is mis-attributed or missing, please open an issue — it will be
corrected promptly.

> **Pantheon as a whole is licensed under the GNU Affero General Public License,
> version 3 or later.** See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The
> permissive licences named throughout this file are the licences of the
> individual third-party components listed beside them — they describe what
> Pantheon is *permitted to include*, not what Pantheon is *distributed under*.
> The two are not in tension and never were; see
> [Licence scope](#licence-scope--what-applies-to-what) below.

---

## Odysseus

**Pantheon is a fork of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus).**

Everything Pantheon is began as Odysseus. The agent loop, the tool layer, the
approval and untrusted-context security model, the window system, the theme
engine, the skills system, the task scheduler, the MCP integration, the email
client, the image editor, the research pipeline — all of it originates there.

Pantheon's contribution is elevation: surfacing what the backend already computed
and discarded, lighting what was already written, and building the authoring
surfaces the engines deserved. The hard parts were already solved.

- **Licence:** AGPL-3.0-or-later
- **Forked at:** `b4d1293`, 2026-08-24
- **Modifications:** see `CHANGELOG.md` and `NOTICE`

### Two upstream identities, and which is which

Odysseus is reachable under two GitHub identities, and this attribution names
both, because naming one of two would be an incomplete AGPL §5(a) notice.

| | Identity | What it is, verifiably |
|---|---|---|
| **Clone source** | [`pewdiepie-archdaemon/odysseus`](https://github.com/pewdiepie-archdaemon/odysseus) | The repository Pantheon was actually cloned from. It is the `origin` remote of the fork-point checkout, and `CHANGELOG.md` records the fork from it at `b4d1293` (branch `dev`) on 2026-08-24. |
| **Referenced identity** | [`odysseus-dev/odysseus`](https://github.com/odysseus-dev/odysseus) | The identity Odysseus's **own** code and documentation point at. At commit `b4d1293` it appears **47 times across 16 files** — the README's `git clone` command, `CONTRIBUTING.md`, `package.json`'s `repository.url`, the four `.github/` issue and PR templates, `docs/`, and the outbound `HTTP-Referer` header set in `src/endpoint_resolver.py` and `src/llm_core.py`. |

*(Scope of the 47 / 16: case-insensitive literal `odysseus-dev` in tracked files
of the upstream tree at `b4d1293`, measured 2026-08-27.)*

Pantheon makes no claim about the relationship between the two — whether one
mirrors, renames or succeeds the other is upstream's business. What is on the
record here is what each one demonstrably is. Three of those upstream references
are deliberately preserved in Pantheon's tree, unswept, because they link to
specific upstream issues and discussions that are still the correct destination.

Pantheon is not affiliated with or endorsed by the Odysseus project, under
either identity. Please do not report Pantheon issues to them.

---

## Licence scope — what applies to what

This section exists because the acknowledgements Pantheon inherited from
Odysseus opened their compatibility notes with *"the core ships fully permissive
(MIT-compatible)"*, and that sentence, read alone, contradicts the `LICENSE`
file. Stated plainly, so nothing has to be inferred:

1. **Pantheon as a whole — every file in this repository that is not separately
   marked — is AGPL-3.0-or-later.** That is the licence you receive it under,
   the licence you must pass on under, and the licence whose §13 network clause
   applies if you run a modified Pantheon where other people can reach it. It is
   inherited from Odysseus and it is deliberate.
2. **The third-party licences below belong to those components
   individually.** MIT, BSD-2/3-Clause, Apache-2.0, OFL-1.1 and — for OpenMoji's
   artwork — CC BY-SA 4.0 are what let Pantheon *include* those components at
   all, and they travel with the copies: their copyright and licence notices
   must be preserved in every redistribution, which is what this file and
   [`licenses/`](licenses/) are for. They do not relicense Pantheon and they
   never could.
3. **The original "MIT-compatible core" claim was about dependency hygiene, and
   that part of it stands.** It meant: no dependency on the core install path
   imposes copyleft, so a downstream who wanted to combine Pantheon's core code
   with permissively-licensed work is not blocked by a *dependency*. It never
   meant Pantheon is distributable under MIT, and this file no longer says
   anything that could be read that way.
4. **Three third-party components are copyleft, and only one of them is
   optional.** Each is copyleft in a *different* way, which is the part worth
   reading — "copyleft" on its own tells you almost nothing about what you owe.

   - **OpenMoji** — the emoji artwork, **CC BY-SA 4.0**, in
     [`library/emoji/`](library/emoji/). **Ships by default**: it is what every
     emoji in the product is made of. Share-alike binds *the artwork and
     adaptations of it*, and Pantheon's serve-time transform is an adaptation,
     so the vendored file is CC BY-SA 4.0 too. It does **not** reach the code
     that reads it — see the aggregation note below.
   - **Pyodide** — the in-browser Python runtime, **MPL-2.0**, in
     `static/lib/pyodide/`. **Ships by default** since 2026-09-01, when it
     stopped being fetched from a CDN. MPL is **file-level** copyleft: it binds
     those files and any modification of them, and §3.3 expressly permits
     shipping them inside a larger work under a secondary licence. Pantheon
     ships them **unmodified**, so what is owed is the notice and a pointer to
     the source, both of which are here. Change one of those files and you owe
     that file's source under MPL — the rest of Pantheon is unaffected.
   - **PyMuPDF** — **AGPL-3.0**, and ships in neither the default install nor
     the default image. See [PyMuPDF](#pymupdf--scope-and-licence).

   This numbered point said "the one copyleft dependency is optional" until
   2026-09-01, and by then it had been wrong for as long as the product had been
   drawing emoji — which is to say, since before the fork. It was corrected when
   OpenMoji was finally attributed. The failure worth naming is not the sentence:
   it is that a *summary* of the licence position was maintained by hand, next to
   a detail section it was allowed to contradict. `.pantheon/check-licences.py`
   now fails the build if a copyleft entry is missing from this list.

Nothing in this repository restricts commercial use. AGPL §10 forbids adding
such a restriction and §7 lets any recipient strip one, so any statement of
preference you find in the README is exactly that — a preference, not a term.

**Why CC BY-SA 4.0 artwork can sit inside an AGPL-3.0 program.** The two
licences are not merged and neither one swallows the other. The emoji are a data
file that the program *reads* — glyph outlines in
`library/emoji/openmoji-black.json`, served as SVG — and no OpenMoji expression
is compiled into, linked against or derived from Pantheon's source. That is the
"aggregate" the AGPL describes in §5: separate and independent works distributed
on one medium, where including one does not extend its licence over the others.
So:

- Pantheon's code stays AGPL-3.0-or-later. CC BY-SA does not reach it.
- The emoji data stays CC BY-SA 4.0. The AGPL does not reach it either, and you
  may take that file, use it elsewhere and adapt it under CC BY-SA's own terms.
- **If you fork Pantheon and change the emoji artwork, share-alike applies to
  your changed artwork** — publish it under CC BY-SA 4.0 with attribution. If
  you replace the set entirely, you are simply not using OpenMoji any more.
- If you would rather ship no CC BY-SA material at all, `library/emoji/` is one
  directory and `routes/emoji_routes.py` degrades to blank glyphs without it.

Creative Commons has separately declared CC BY-SA 4.0 one-way compatible with
GPLv3, so relicensing the artwork *into* the program is also available if a
downstream ever wants it. Pantheon does not need that route and does not take
it — aggregation is the weaker claim and the true one.

---

## Adapted sources

Portions of this project were adapted from other open-source repositories.
Their original authors retain copyright over the adapted portions, under the
licences noted below. These are permissive licences, which permit this use
**as long as their original copyright and licence notices are preserved**. Full
texts are in [`licenses/`](licenses/).

| Project | Licence | Used for |
|---|---|---|
| [opencode](https://github.com/anomalyco/opencode) | MIT | Agent-loop and tool-execution patterns, UI concepts |
| [llmfit](https://github.com/AlexsJones/llmfit) | MIT | Hardware-fit calculation behind the model Cookbook's download / serve / "What Fits?" feature |
| [Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) | Apache-2.0 | Deep-research pipeline |
| [ECC](https://github.com/affaan-m/ECC) | MIT | The 286-skill library Pantheon ships with, in `library/ecc/` |
| [OpenMoji](https://openmoji.org) | **CC BY-SA 4.0** | Every emoji rendered in the product, in `library/emoji/` |

- **[OpenMoji](https://openmoji.org)** — the open-source emoji and icon project
  by the University of Applied Sciences Schwäbisch Gmünd (HfG). **Licensed
  CC BY-SA 4.0**, full text in
  [`licenses/OpenMoji-CC-BY-SA-4.0.txt`](licenses/OpenMoji-CC-BY-SA-4.0.txt).

  Every emoji you see in Pantheon is OpenMoji's black (monochrome line-art) set,
  4,147 glyphs, vendored under [`library/emoji/`](library/emoji/) and pinned in
  `MANIFEST.json`.

  **This attribution was missing until 2026-09-01, and the obligation was not
  new.** The product had been serving OpenMoji artwork through `/api/emoji/`
  since before the fork, fetched from a CDN, credited nowhere in the repository.
  CC BY-SA 4.0 requires attribution whether the bytes are proxied or bundled;
  vendoring them only made the omission easier to notice. It is recorded here in
  the same terms as the AGPL and MIT obligations rather than quietly fixed,
  because a licence you meet only once you are caught is not one you are
  meeting.

  **Share-alike applies to what we did to them.** The vendored JSON strips each
  SVG's wrapper and hoists the stroke attributes every glyph repeats onto one
  `<g>` at serve time. The artwork is unchanged, but that is an adaptation, so
  the adaptation is CC BY-SA 4.0 too — stated in `library/emoji/MANIFEST.json`
  as well as here.

- **[ECC](https://github.com/affaan-m/ECC)** — "the agent harness operating
  system" by Affaan Mustafa. Copyright © 2026 Affaan Mustafa. **MIT License**,
  full text in [`licenses/ECC-MIT.txt`](licenses/ECC-MIT.txt).

  Pantheon ships **286 skills** from it, vendored under
  [`library/ecc/`](library/ecc/) and pinned to a named upstream commit recorded
  in `library/ecc/MANIFEST.json`. They load as a **read-only** layer beneath the
  user's own skills, so a skill you write under a bundled name shadows it.

  **What is vendored and what is not.** The `SKILL.md` text only — 286 files,
  2.5 MB. ECC's scripts, assets and documentation are deliberately **not**
  included: they are third-party executables, and a product whose stated intent
  is to depend on nothing external should not ship code it has not read to
  execute on the user's machine. The skills are prose an agent reads. That is a
  different risk, and an auditable one.

  Six of the 286 name a commercial API in their own body — `videodb`,
  `nutrient-document-processing`, `social-publisher`, `ito-baskets`, `x-api`,
  `scientific-db-uspto-database`. Each is confined to a skill directory named
  after the thing it does, and none of them causes any traffic unless a person
  invokes that skill and supplies their own credentials. They are listed here
  rather than removed, because deleting a capability is not the same as
  defaulting it off, and the second is what the self-hosting rule asks for.

- **[opencode](https://github.com/anomalyco/opencode)** — open-source AI coding
  agent (originally [opencode-ai/opencode](https://github.com/opencode-ai/opencode),
  archived Sep 2025; now maintained at `anomalyco/opencode`). Copyright © the
  opencode authors. **MIT License.** Adapted for agent-loop / tool-execution
  patterns and UI concepts. Full text in
  [`licenses/opencode-MIT-LICENSE.txt`](licenses/opencode-MIT-LICENSE.txt).
- **[llmfit](https://github.com/AlexsJones/llmfit)** by **Alex Jones** — the
  engine behind the Cookbook's model download / serve / "What Fits?" feature.
  Copyright © Alex Jones. **MIT License.** Adapted in `services/hwfit/`
  (hardware detection, quant-aware fit scoring, model catalog),
  `routes/cookbook_*.py`, `routes/hwfit_routes.py`, `static/js/cookbook*.js`,
  and `scripts/pantheon-cookbook`. Full text in
  [`licenses/llmfit-MIT-LICENSE.txt`](licenses/llmfit-MIT-LICENSE.txt).
- **[Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch)** by
  **Alibaba-NLP / Tongyi Lab** — the multi-step deep-research agent pipeline.
  Copyright © Alibaba-NLP / Tongyi Lab. **Apache-2.0.** Adapted for Pantheon's
  Deep Research feature (`services/research/`, `src/research_handler.py`,
  `routes/research/research_routes.py`, `services/search/`). Full text in
  [`licenses/DeepResearch-Apache-2.0.txt`](licenses/DeepResearch-Apache-2.0.txt).

Apache-2.0 §4(b) requires modified files to carry a change notice. Eight files
carry one at the top as of 2026-08-27: the six under `services/research/`,
`routes/research/` and `src/research_handler.py`, plus `src/deep_research.py`
and `src/goal_based_extractor.py`, which declare their Alibaba derivation in
their own docstrings.

**`services/search/` appears in the path list above because that is upstream
Odysseus's own attribution, carried forward verbatim** — the copyright holder's
words, not ours. It is *not* stamped, and the reason belongs on the record: its
nine files contain no Tongyi DeepResearch expression (zero matches for `Tongyi`,
`DeepResearch`, `IterResearch` or `Alibaba` across 2,222 lines, measured
2026-08-27) and every one is byte-identical to the fork point. A §4(b) notice
states that the files were changed; putting one on a file nobody changed is a
false statement in the other direction. The path stays in the attribution, which
costs nothing and errs toward crediting. The stamp does not.

**Seven of the eight stamped files are also unchanged by Pantheon** — only
`routes/research/research_routes.py` differs from the fork point. Their notices
say exactly that, and name Odysseus as the party that changed them. §4(b) still
applies: they are modified files relative to Tongyi's original, and Pantheon
redistributes them.

*Paths updated for this tree: the llmfit CLI is now `scripts/pantheon-cookbook`,
and the research routes moved to `routes/research/research_routes.py`
(`routes/research_routes.py` survives as an import shim).*

---

## Bundled via Docker Compose

These services are pulled as images by the project's `docker-compose.yml` and
run alongside Pantheon on `docker compose up`. They are not modified — just
composed.

| Service | Image | Purpose | Licence |
|---|---|---|---|
| [SearXNG](https://github.com/searxng/searxng) | `docker.io/searxng/searxng:2026.5.31-7159b8aed` (pinned tag; see compose) | Default metasearch backend | AGPL-3.0 |
| [ChromaDB](https://github.com/chroma-core/chroma) | `docker.io/chromadb/chroma:latest` | Vector store for memory / RAG | Apache-2.0 |
| [ntfy](https://github.com/binwiederhier/ntfy) | `docker.io/binwiederhier/ntfy` | Push notifications (self-hosted reminders) | Apache-2.0 / GPL-2.0 (dual) |

*Image references measured from `docker-compose.yml:92, 107, 157` on 2026-08-27.
SearXNG is pinned rather than tracking `latest` because Pantheon waits on its
healthcheck.*

---

## Vendored libraries — `static/lib/`

Shipped byte-identical to the published upstream artifacts and served directly.
`.gitattributes` turns the whitespace check off for `static/lib/` so they stay
byte-identical. **Never reformat these** — reformatting is what strips an
embedded licence banner.

| Library | File | Purpose | Licence |
|---|---|---|---|
| [highlight.js](https://github.com/highlightjs/highlight.js) v11.9.0 | `highlight.min.js` | Code syntax highlighting | BSD-3-Clause ([`licenses/highlight.js-BSD-3-Clause.txt`](licenses/highlight.js-BSD-3-Clause.txt)) |
| [SheetJS / xlsx](https://github.com/SheetJS/sheetjs) v0.20.3 | `xlsx.full.min.js` | Spreadsheet (`.xlsx`) read/write | Apache-2.0 ([`licenses/SheetJS-Apache-2.0.txt`](licenses/SheetJS-Apache-2.0.txt)) |
| [docx](https://github.com/dolanmiu/docx) v8.5.0 | `docx.umd.min.js` | Generate `.docx` documents | MIT ([`licenses/docx-MIT-LICENSE.txt`](licenses/docx-MIT-LICENSE.txt)) |
| [mammoth.js](https://github.com/mwilliamson/mammoth.js) v1.8.0 | `mammoth.browser.min.js` | Convert `.docx` → HTML | BSD-2-Clause ([`licenses/mammoth.js-BSD-2-Clause.txt`](licenses/mammoth.js-BSD-2-Clause.txt)) |
| [html2pdf.js](https://github.com/eKoopmans/html2pdf.js) v0.10.2 | `html2pdf.bundle.min.js` | HTML → PDF export (bundles jsPDF + html2canvas) | MIT ([`licenses/html2pdf.js-MIT-LICENSE.txt`](licenses/html2pdf.js-MIT-LICENSE.txt)); bundle sidecar: [`licenses/html2pdf.bundle.min.js.LICENSE.txt`](licenses/html2pdf.bundle.min.js.LICENSE.txt) |
| [jsPDF](https://github.com/parallax/jsPDF) v2.3.1 | bundled inside `html2pdf.bundle.min.js` | PDF generation | MIT ([`licenses/jsPDF-MIT-LICENSE.txt`](licenses/jsPDF-MIT-LICENSE.txt)) |
| [html2canvas](https://github.com/niklasvh/html2canvas) v1.0.0 | bundled inside `html2pdf.bundle.min.js` | DOM → canvas rasterization | MIT ([`licenses/html2canvas-MIT-LICENSE.txt`](licenses/html2canvas-MIT-LICENSE.txt)) |
| [node-qrcode](https://github.com/soldair/node-qrcode) | `qrcode.min.js` | QR-code rendering (2FA setup) | MIT ([`licenses/node-qrcode-MIT-LICENSE.txt`](licenses/node-qrcode-MIT-LICENSE.txt)) |
| [KaTeX](https://github.com/KaTeX/KaTeX) v0.16.22 | `katex/katex.min.{js,css}` + `katex/fonts/*.woff2` | Math typesetting | MIT ([`licenses/KaTeX-MIT-LICENSE.txt`](licenses/KaTeX-MIT-LICENSE.txt)) |
| [Mermaid](https://github.com/mermaid-js/mermaid) v11.16.1 | `mermaid.min.js` | Diagrams from text | MIT ([`licenses/Mermaid-MIT-LICENSE.txt`](licenses/Mermaid-MIT-LICENSE.txt)) |
| [Pyodide](https://github.com/pyodide/pyodide) 0.27.5 | `pyodide/{pyodide.js,pyodide.asm.js,pyodide.asm.wasm,python_stdlib.zip,pyodide-lock.json}` | In-browser Python runtime for `” ```python ”` code blocks | MPL-2.0 ([`licenses/Pyodide-MPL-2.0.txt`](licenses/Pyodide-MPL-2.0.txt)) |

*Versions read out of the shipped bundles on 2026-08-27, not carried from a
document: `highlight.min.js` v11.9.0 from its own banner, `katex.min.js`
`version:"0.16.22"`, `mermaid.min.js` `11.16.1`.*

**Where each notice currently lives.** Two of the eight bundles carry their
notice inline — `highlight.min.js` opens with *"Highlight.js v11.9.0 (git:
f47103d4f1) (c) 2006-2023 undefined and other contributors License:
BSD-3-Clause"*, and `xlsx.full.min.js` opens with *"xlsx.js (C) 2013-present
SheetJS -- http://sheetjs.com"*. `html2pdf.bundle.min.js` opens with *"For
license information please see html2pdf.bundle.min.js.LICENSE.txt"*, and that
sidecar file is now in
[`licenses/html2pdf.bundle.min.js.LICENSE.txt`](licenses/html2pdf.bundle.min.js.LICENSE.txt)
— fetched verbatim from html2pdf.js 0.10.2, not reconstructed. **The other
seven files carry no banner at all**: docx, mammoth.js, KaTeX (`.js` and
`.css`), Mermaid, node-qrcode, and — inside the html2pdf bundle — jsPDF and
html2canvas. *(Measured 2026-09-01: zero `/*!` markers and zero occurrences of
"license" or "copyright" in the first 4 KB of each. An earlier version of this
paragraph named only five, which implied KaTeX and Mermaid had banners; they do
not.)* Their texts landed in [`licenses/`](licenses/) on 2026-08-27, each
fetched from upstream at the version actually vendored here.

MIT and both BSD variants require the notice to travel with redistributed
copies. Minifiers strip banners, so for seven of these files the *only* notice
in this repository is the one in [`licenses/`](licenses/) — which means copying
a single file out of `static/lib/` carries no notice with it, and whoever does
that has to bring the licence text along themselves. That is the reason the
texts are files here rather than a list in this one, and the reason
[`.pantheon/check-licences.py`](.pantheon/check-licences.py) fails if one goes
missing or stops being linked.

**The sidecar does not cover everything the bundle contains.**
`html2pdf.bundle.min.js` pulls in fifteen top-level packages; its `LICENSE.txt`
carries a copyright notice for **three** of them — `es6-promise`, `html2canvas`
and `jspdf` — plus html2pdf.js itself. The other twelve, `dompurify` among them,
have no notice anywhere in this repository, and DOMPurify is dual-licensed
Apache-2.0 **or** MPL-2.0, which is a choice someone has to make rather than a
file to fetch. That gap is real, it is tracked as `P0-21b`, and it is recorded
here rather than left for someone to rediscover.

KaTeX and Mermaid are loaded on first use by `static/js/markdown.js` rather than
from `index.html`, so a session that renders no math and no diagram never
fetches either. Only the `.woff2` KaTeX fonts are shipped, matching
`static/fonts/`; the `.woff` and `.ttf` variants its stylesheet also lists are
never requested by a browser that supports `woff2`.

---

## Loaded at runtime from a CDN

**Nothing. This section is empty as of 2026-09-01, and that is the point.**

Pyodide was the last entry and is now vendored — see
[vendored libraries](#vendored-libraries--staticlib). With it went the final
`https://cdn.jsdelivr.net` allowance in the Content-Security-Policy, which had
been in `script-src`, `style-src` **and** `font-src`. Every byte the app loads
now comes from its own origin.

The heading stays rather than being deleted, because "we removed the CDN loads"
is a claim that needs somewhere to be falsified. If a library reappears here, it
belongs in this table with its licence, and `.pantheon/check-licences.py` will
not catch it — a CDN load ships no file, so rule 1 has nothing to see. That is a
known limit of the checker and this table is the compensating control.

*Measured 2026-08-27: `static/js/codeRunner.js:156,158` is the only third-party
CDN load left in the tree — Mermaid and KaTeX used to load this way and are now
vendored.*

**Pyodide is MPL-2.0 and the paperwork landed with the bytes.** The five files
live in `static/lib/pyodide/` with a `MANIFEST.json` pinning each one's SHA-256.
MPL §3.2
attaches on *distribution* — pointing a browser at jsDelivr distributed nothing,
shipping the files does — so `P16-18` wrote this requirement onto the `P16-07`
row a commit before it came due, and `P16-07` paid it in the same commit that
vendored: licence text in [`licenses/`](licenses/), an `INVENTORY` entry in
[`.pantheon/check-licences.py`](.pantheon/check-licences.py), and the table row
above. MPL is **file-level** copyleft: it binds the covered files and their
modifications, and §3.3 expressly permits distributing them inside a larger work
under a secondary licence. Pantheon ships them **unmodified**, so the obligation
is the notice and the source pointer, both discharged here. It does not reach
Pantheon's own code, and the AGPL does not reach Pyodide's.

**[PDFObject](https://github.com/pipwerks/PDFObject) 2.1.1 (MIT)** was credited
by the acknowledgements Pantheon inherited, as a second CDN-loaded library for
inline PDF embedding. A case-insensitive search of the whole tree on 2026-08-27
finds it in no source file, no template and no stylesheet — the only match
outside this file is an unrelated identifier inside the html2pdf bundle. The
credit is kept on the record here rather than dropped silently, but this
repository does not appear to load PDFObject.

---

## Fonts

All shipped unmodified. **Do not subset or re-convert them** — that produces a
Modified Version and OFL §3's Reserved Font Name restriction then applies.

| Font | Files | Licence | Author | Reserved Font Name |
|---|---|---|---|---|
| [Fira Code](https://github.com/tonsky/FiraCode) | `static/fonts/FiraCode-{Light,Regular,SemiBold}.woff2` | SIL Open Font License 1.1 ([`licenses/FiraCode-OFL.txt`](licenses/FiraCode-OFL.txt)) | Nikita Prokopov & contributors | none declared |
| [Inter](https://github.com/rsms/inter) | `static/fonts/Inter-{Regular,Medium,SemiBold}.woff2` | SIL Open Font License 1.1 ([`licenses/Inter-OFL.txt`](licenses/Inter-OFL.txt)) | Rasmus Andersson | none declared |
| [OpenDyslexic](https://opendyslexic.org/) | `static/fonts/OpenDyslexic-{Regular,Bold}.woff2` | SIL Open Font License 1.1 ([`licenses/OpenDyslexic-OFL.txt`](licenses/OpenDyslexic-OFL.txt)) | Abbie Gonzalez | **yes — `OpenDyslexic`** |
| KaTeX (20 faces) | `static/lib/katex/fonts/*.woff2` | SIL Open Font License 1.1 ([`licenses/KaTeX-fonts-OFL.txt`](licenses/KaTeX-fonts-OFL.txt)) | Design Science, Inc. and Khan Academy | **yes — every face** |

The 20 KaTeX faces are `KaTeX_AMS`, `KaTeX_Caligraphic`, `KaTeX_Fraktur`,
`KaTeX_Main`, `KaTeX_Math`, `KaTeX_SansSerif`, `KaTeX_Script`, `KaTeX_Size1–4`
and `KaTeX_Typewriter`, copyright Design Science, Inc. and Khan Academy.
*(Counted 2026-08-27: 20 `.woff2` files in `static/lib/katex/fonts/`.)*

> **A GohuFont credit was removed from this table on 2026-08-27, and the reason
> belongs on the record.** `static/fonts/custom/GohuFont.ttf` was credited to
> Hugo Chargois under the WTFPL. It was not GohuFont. Measured from the file
> before deleting it: 1,468 bytes, 13 sfnt tables, **3 glyphs**, and a `name`
> table reading `Untitled1` (family), `Copyright (c) 2025, Unknown` (copyright),
> `FontForge 2.0 : Untitled1 : 1-3-2025` — a FontForge scratch file, not a
> typeface. It was the one affirmatively false statement in this repository's
> attribution rather than a merely incomplete one, so the file and its credit
> row went together (`P0-23`, D-2026-08-26-06). Nothing rendered with it.

---

## Vendor marks — `static/icons/`

Two of the images in `static/icons/` are other projects' brand marks. They are
not code and carry no licence text, which is exactly why they went nine months
without an entry anywhere: an attribution audit looks for `LICENSE` files, and a
logo does not have one.

| Mark | Files | Project | Why it is here |
|---|---|---|---|
| Ollama | `static/icons/ollama-mark.png`, `static/icons/ollama-mark-crop.png` | [Ollama](https://github.com/ollama/ollama) (MIT) | Labels the Ollama backend in the Cookbook's model list, download and serve views |
| SGLang | `static/icons/sglang-mark.png`, `static/icons/sglang-logo.png` | [SGLang](https://github.com/sgl-project/sglang) (Apache-2.0) | Labels the SGLang backend in the same views |

**What Pantheon claims, and does not.** These marks are used **nominatively** —
to name the thing a row is about, the way a table of adapters is allowed to say
which adapter. Pantheon is not affiliated with, endorsed by or sponsored by
either project. The marks belong to their owners; a permissive software licence
covers a project's *code*, not its trademarks, so neither MIT nor Apache-2.0 is
what permits this and nothing in `licenses/` should suggest otherwise. Either
owner may ask for the mark to be removed, and the answer would be yes — they are
four PNGs behind a `background: currentColor` mask, and the UI degrades to text
labels without them.

**Both were in the tree at the fork point** (`fff72ec`, baseline of cybertooth
`c3b2120`) and neither was mentioned in Odysseus's acknowledgements or in this
file until 2026-09-01. They were found the same week as OpenMoji and for the
same reason: someone finally compared what is *on disk* against what this file
*says*. That comparison is now `.pantheon/check-licences.py`, and it runs in CI.

> The Ollama entry under [Companion services](#companion-services--interoperated-with-not-bundled)
> says those projects are "not distributed with this project". That is true of
> Ollama's *software* and was never true of its mark. The line stays where it
> is, because Ollama genuinely is a companion service; this section is the part
> that ships.

---

## Python dependencies

Core (`requirements.txt`) and optional (`requirements-optional.txt`). Licences
below were re-read from each distribution's own published metadata on
2026-08-27 rather than carried from the inherited acknowledgements.

| Package | Where | Licence |
|---|---|---|
| FastAPI | core | MIT |
| Uvicorn | core | BSD-3-Clause |
| python-multipart | core | Apache-2.0 |
| python-dotenv | core | BSD-3-Clause |
| HTTPX | core | BSD-3-Clause |
| **httpcore** | core | BSD-3-Clause |
| **httpx2** | core (test client only) | BSD-3-Clause |
| Pydantic / pydantic-settings | core | MIT |
| SQLAlchemy | core | MIT |
| pypdf | core | BSD-3-Clause |
| BeautifulSoup4 | core | MIT |
| charset-normalizer | core | MIT |
| NumPy | core | BSD-3-Clause (with bundled components under 0BSD, MIT, Zlib and CC0-1.0) |
| ChromaDB (`chromadb-client`) | core | Apache-2.0 |
| fastembed | core | Apache-2.0 |
| youtube-transcript-api | core | MIT |
| markdown | core | BSD-3-Clause |
| **nh3** | core | MIT |
| icalendar | core | BSD-2-Clause |
| **python-dateutil** | core | Dual — Apache-2.0 OR BSD-3-Clause |
| caldav | core | GPL-3.0-or-later OR Apache-2.0 (dual; used under Apache-2.0) |
| cryptography | core | Apache-2.0 OR BSD-3-Clause |
| bcrypt | core | Apache-2.0 |
| MCP (Model Context Protocol SDK, pinned `<2`) | core | MIT |
| pyotp | core | MIT |
| qrcode\[pil] | core | BSD-3-Clause |
| croniter | core | MIT |
| pytest / pytest-asyncio | core | MIT / Apache-2.0 |
| faster-whisper | optional — local speech-to-text | MIT |
| kokoro | optional — local text-to-speech | Apache-2.0 |
| `soundfile` (python-soundfile) | optional — audio I/O for kokoro | BSD-3-Clause |
| **`ddgs`** | optional — DuckDuckGo search provider | MIT |
| markitdown\[docx,pptx,xlsx,xls] | optional — Office/EPUB text extraction | MIT |
| **PyMuPDF** | optional — see below | **AGPL-3.0** (dual: AGPL-3.0 or an Artifex commercial licence) |

**`duckduckgo-search` → `ddgs`.** The inherited acknowledgements credited
`duckduckgo-search`. That package was renamed by its author; this project
depends on **`ddgs`** (`requirements-optional.txt:28`) and imports it as
`from ddgs import DDGS` (`services/search/providers.py:418`). Both are MIT and
both are by deedy5; the credit here follows the package actually installed.

**`python-magic` — shipped in the Docker image, absent from `requirements.txt`.**
[python-magic](https://github.com/ahupp/python-magic) 0.4.27 (**MIT**, © Adam
Hupp) is pip-installed inside the Docker image only (`Dockerfile:84`), together
with the Debian `libmagic1` shared library it dlopens. It is deliberately absent
from `requirements.txt` because it resolves libmagic at import time and would
regress pip/venv installs on hosts without the library. It backs content-based
MIME sniffing in `src/upload_handler.py`.

---

## JavaScript dependencies

Pantheon has no build step, no bundler and no framework — ES modules load
directly, and everything a browser needs is vendored under `static/lib/` and
credited above. The one npm entry is a development dependency and ships in
nothing:

| Package | Where | Licence |
|---|---|---|
| [`@antithesishq/bombadil`](https://github.com/antithesishq/bombadil) `^0.6.1` | `package.json` — `devDependencies` | MIT |

*Read on 2026-08-27 from `package.json`, from `package-lock.json`'s recorded
`"license": "MIT"` for the pinned 0.6.1, and from the npm registry metadata.*

---

## Docker image — pre-built third-party wheels

The image's first build stage (`Dockerfile:1-10`) runs
`docker/build-realesrgan-wheels.sh`, which downloads three unmaintained
dependencies of Real-ESRGAN, **patches their `setup.py`**, builds wheels from
the patched source, and pre-installs those wheels into the final image
(`Dockerfile:87-92`). The patch is a one-line fix to `get_version()`: these
packages read their version with `exec()` + `locals()['__version__']`, which
raises `KeyError` on Python 3.13+ under PEP 667.

**These wheels are redistributed inside the Pantheon image, and they are
modified copies**, so their notices travel with them and the Apache-2.0 change-
notice obligation applies to the two Apache components.

| Package | Version | Upstream | Licence |
|---|---|---|---|
| basicsr | 1.4.2 | [xinntao/BasicSR](https://github.com/xinntao/BasicSR) | Apache-2.0 |
| gfpgan | 1.3.8 | [TencentARC/GFPGAN](https://github.com/TencentARC/GFPGAN) | Apache-2.0 — © 2021 THL A29 Limited, a Tencent company; its `LICENSE` excepts the third-party components it lists |
| facexlib | 0.3.0 | [xinntao/facexlib](https://github.com/xinntao/facexlib) | MIT — © 2020 Xintao Wang |

*Licences read on 2026-08-27 from each project's own `LICENSE` file and, for
facexlib, from the `LICENSE` inside the exact `facexlib-0.3.0` sdist that this
build downloads. Note for anyone auditing: facexlib's PyPI metadata says
"Apache License 2.0" while the `LICENSE` file it actually ships says MIT. The
shipped file governs.*

**[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) itself (BSD-3-Clause,
© 2021 Xintao Wang) is not distributed with Pantheon.** It powers the image
editor's Denoise and Upscale tools (`routes/gallery/gallery_routes.py`), and it
is installed on demand from the Cookbook's dependency list
(`routes/shell_routes.py`) — the three wheels above exist only so that
`pip install realesrgan` resolves without rebuilding sdists that fail on Python
3.14. Its model weights (`realesr-general-x4v3`, `RealESRGAN_x4plus`) are
downloaded at runtime from Real-ESRGAN's own GitHub releases and are likewise
not redistributed here.

---

## macOS MLX bridge — Swift packages

`swift/pantheon-mlx-image-bridge` builds two small executables
(`pantheon-mlx-inpaint`, `pantheon-mlx-colorize`) against two SwiftPM
dependencies declared at `swift/pantheon-mlx-image-bridge/Package.swift:12-13`.
They are resolved at build time, not vendored into this repository.

| Package | Products used | Licence |
|---|---|---|
| [mlx-lama-swift](https://github.com/xocialize/mlx-lama-swift) | `LaMa`, `MIGAN` — inpainting | MIT — Copyright (c) 2026 Xocialize |
| [mlx-ddcolor-swift](https://github.com/xocialize/mlx-ddcolor-swift) | `DDColor` — colorization | MIT — Copyright (c) 2026 Xocialize |

*Both licences fetched from each repository's `LICENSE` file on 2026-08-27.*

---

## PyMuPDF — scope and licence

**PyMuPDF is AGPL-3.0** (dual-licensed: AGPL-3.0, or a commercial licence sold
by Artifex that lifts the network clause) and is deliberately optional. It is
absent from the default install and the default Docker image — it lives in
`requirements-optional.txt:35`, and the image only installs that file when built
with `--build-arg INSTALL_OPTIONAL=true`. Every import is lazy and guarded
(`src/pdf_forms.py:17`, `src/pdf_runtime.py:12`), and each guard raises a clear
setup hint naming the licence rather than failing obscurely.

**Its scope is wider than form-filling, and the earlier "form-filling only"
description was wrong.** Scope of the measurement, stated: every `import fitz`
and every `src.pdf_forms` import in non-test Python, resolved through its call
graph to the enclosing route handler. Tree-wide, 2026-08-27 — **ten handlers
reach PyMuPDF**:

| Route | Reaches PyMuPDF via | Feature |
|---|---|---|
| `GET /api/document/{doc_id}/render-pages` | `_load_pdf_viewer_fitz()` | **PDF viewer — page render** |
| `GET /api/document/{doc_id}/page/{page_no}.png` | `_load_pdf_viewer_fitz()` | **PDF viewer — page render** |
| `POST /api/document/{doc_id}/ai-fill-annotations` | `import fitz` | **Annotation fill** |
| `POST /api/documents/import-pdf` | `has_form_fields`, `extract_fields` | Form detection / field extraction |
| `GET /api/document/{doc_id}/render-pdf` | `fill_fields`, `stamp_annotations` | Form filling |
| `GET /api/document/{doc_id}/export-pdf` | `fill_fields`, `stamp_signatures`, `stamp_annotations` | Form filling |
| `POST /api/document/{doc_id}/prepare-signed-reply` | `fill_fields`, `stamp_signatures`, `stamp_annotations` | Form filling |
| `POST …/attachment-as-doc/{uid}/{index}` (email) | `has_form_fields`, `extract_fields` | Form detection on a mail attachment |
| `POST /api/chat` | `build_user_content` → `has_form_fields`, `extract_fields` | Fillable-PDF detection on any chat attachment |
| `POST /api/chat_stream` | `build_user_content` → `has_form_fields`, `extract_fields` | Fillable-PDF detection on any chat attachment |

Three of these were missed by the description this section replaced: the
side-panel PDF viewer's page rendering and the annotation-fill endpoint are not
form-filling, and installing PyMuPDF is what turns them on.

**The last two were missed by the correction as well, and they are the two
busiest endpoints in the application.** The path is indirect, which is why a
two-file grep does not find it: `routes/chat_routes.py:738` and `:928` →
`routes/chat_helpers.py:336` `preprocess_message` → `src/chat_handler.py:284`
→ `src/document_processor.py:420` `build_user_content` → `:504`
`from src.pdf_forms import has_form_fields, extract_fields`. Attach a PDF to an
ordinary chat message and PyMuPDF is reached, if it is installed. That does not
change the licence position — the import is still lazy and still guarded — but
anyone reasoning about which features an AGPL dependency touches needs it on the
list.

**PDF *text* extraction does not use PyMuPDF and never requires it.** It goes
through **pypdf** (BSD-3-Clause) — `src/document_processor.py:140` and
`src/personal_docs.py:19`. Any documentation or docstring in this tree still
crediting PyMuPDF for text extraction is stale and is being corrected.

If you do install PyMuPDF, its AGPL network clause attaches to that feature for
your deployment. Since Pantheon as a whole is already AGPL-3.0-or-later, this
adds an upstream copyright holder rather than a new obligation class.

---

## Companion services — interoperated with, not bundled

Pantheon talks to these over the network or shells out to them. They are **not**
distributed with this project; their licences do not bind this codebase, but
they deserve credit:

- [Ollama](https://github.com/ollama/ollama) — local model serving (MIT)
- [Radicale](https://github.com/Kozea/Radicale) — CardDAV/CalDAV server (GPL-3.0)
- [Dovecot](https://www.dovecot.org/) — IMAP server
- [isync / mbsync](https://isync.sourceforge.io/) — IMAP mailbox sync (GPL-2.0)
- [tmux](https://github.com/tmux/tmux) — terminal multiplexer; the Cookbook shells
  out to it on Linux/macOS for background model downloads and serves (ISC)
- [OpenSSH](https://www.openssh.com/) (`ssh`, `ssh-keygen`, `ssh-copy-id`) — the
  Cookbook shells out to it to manage remote model servers and provision keys
  (BSD-style permissive)
- Model/API providers: Anthropic, OpenAI, Google (Gemini), DuckDuckGo

---

## Dependency-hygiene notes

These are the compatibility notes inherited from Odysseus's acknowledgements,
kept because the underlying facts are still true and still useful. They are
statements about **dependencies**, not about Pantheon's own licence — for that,
see [Licence scope](#licence-scope--what-applies-to-what).

- **PDF text extraction** uses **`pypdf`** (BSD-3-Clause) and **encoding
  detection** uses **`charset-normalizer`** (MIT). chardet (LGPL-2.1) has been
  removed entirely.
- **PyMuPDF (AGPL-3.0)** is not a core dependency. It is **optional**,
  lazy-imported and listed in `requirements-optional.txt`; the core install runs
  without it. Artifex also sells a commercial PyMuPDF licence that lifts the
  network clause. Its real feature surface is documented above.
- **`caldav`** (Python lib) is **dual-licensed GPL-3.0-or-later OR Apache-2.0**.
  Pantheon uses it under **Apache-2.0**.
- **`markitdown`** (Microsoft) is **MIT** and used only as an *optional*
  dependency for Office/EPUB text extraction (`src/markitdown_runtime.py`),
  lazy-imported with graceful fallback — the core runs without it. The cloud
  `az-doc-intel` extra is deliberately **not** installed, keeping extraction
  fully local.

---

## Thanks to

Inherited from Odysseus's own acknowledgements, and kept in full, because the
credit is theirs to have given and ours to preserve. In upstream's words: most
of Odysseus's code was written *with* AI models, not just by a human, and the
project would not exist without them.

- **gpt-oss-120b** — the legend that kicked this project off.
- **Qwen3-235B**
- **DeepSeek V3.1 · DeepSeek V4 Pro · DeepSeek V4 Flash**
- **Claude** (Anthropic)
- **Codex** (OpenAI)
- Friends, for helping debug.

---

## Licence

Pantheon is licensed under the **GNU Affero General Public License v3.0 or later**.
See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
