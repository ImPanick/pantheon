# Credits

Pantheon stands on a great deal of other people's work. This file credits the
projects whose code, assets or design are included in or adapted by this
repository, and notes their licences.

If something here is mis-attributed or missing, please open an issue — it will be
corrected promptly.

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

Pantheon is not affiliated with or endorsed by the Odysseus project.

---

## Adapted sources

Inherited from Odysseus' own acknowledgements. These are under permissive
licences, which permit this use **as long as their original copyright and licence
notices are preserved**. Full texts are in [`licenses/`](licenses/).

| Project | Licence | Used for |
|---|---|---|
| [opencode](https://github.com/sst/opencode) | MIT | Agent-loop and tool-execution patterns, UI concepts |
| [llmfit](https://github.com/kryptonut/llmfit) | MIT | Hardware-fit calculation in the model cookbook |
| [Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) | Apache-2.0 | Deep-research pipeline |

Apache-2.0 §4(b) requires modified files to carry a change notice. Files derived
from Tongyi DeepResearch carry one at the top.

---

## Vendored libraries — `static/lib/`

Shipped byte-identical to upstream releases so their embedded licence banners
survive. Never reformat these.

| Library | Licence |
|---|---|
| highlight.js | BSD-3-Clause |
| KaTeX | MIT (fonts separately OFL 1.1 — see below) |
| Mermaid | MIT |
| SheetJS / xlsx | Apache-2.0 |
| docx | MIT |
| mammoth.js | BSD-2-Clause |
| jsPDF | MIT |
| html2canvas | MIT |
| html2pdf.js | MIT |
| node-qrcode | MIT |

---

## Fonts

All shipped unmodified. **Do not subset or re-convert them** — that produces a
Modified Version and OFL §3's Reserved Font Name restriction then applies.

| Font | Licence | Reserved Font Name |
|---|---|---|
| Fira Code | OFL 1.1 | none declared |
| Inter | OFL 1.1 | none declared |
| OpenDyslexic | OFL 1.1 | **yes — `OpenDyslexic`** |
| KaTeX (20 faces) | OFL 1.1 | **yes — every face** |

The 20 KaTeX faces are `KaTeX_AMS`, `KaTeX_Caligraphic`, `KaTeX_Fraktur`,
`KaTeX_Main`, `KaTeX_Math`, `KaTeX_SansSerif`, `KaTeX_Script`, `KaTeX_Size1–4`
and `KaTeX_Typewriter`, copyright Design Science, Inc. and Khan Academy.

---

## Runtime dependencies

Python and JavaScript dependencies are listed in `requirements.txt`,
`requirements-optional.txt` and `package.json` with their own licences.

**PyMuPDF is AGPL-3.0** and is deliberately optional. It is absent from the
default install and the default Docker image, every import is lazy and guarded,
and it is reached only when an operator explicitly installs the optional
requirements or builds with optional extras enabled. Its feature surface is PDF
form-filling, the side-panel PDF viewer's page rendering, and the annotation-fill
endpoint. PDF *text* extraction uses pypdf and does not require it.

---

## Licence

Pantheon is licensed under the **GNU Affero General Public License v3.0 or later**.
See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
