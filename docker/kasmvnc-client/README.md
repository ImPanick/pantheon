# The live desktop's web client: its licence texts

`D-2026-10-31-01`. Pantheon's image unpacks KasmVNC's web client from the pinned
KasmVNC package (`workstation/provision.sh client`, the `desktop-client` stage in
`Dockerfile`) and serves it itself (`src/desktop_client.py`). The client's own
`LICENSE.txt` names the texts in this folder; they were read from
[kasmtech/noVNC](https://github.com/kasmtech/noVNC) at commit
`402c0c59d62424ff110bad8f14682deec7d4c780`, the one KasmVNC 1.5.2 was built from,
and they are copied into the image at `/opt/pantheon/kasmvnc/LICENSES/` beside the
package's own `copyright` file. This README is not.

| File | What it is |
|---|---|
| `noVNC-LICENSE.txt` | Which licence covers which of the client's files |
| `noVNC-AUTHORS.txt` | The noVNC authors |
| `LICENSE.MPL-2.0.txt` | The JavaScript core |
| `LICENSE.BSD-2-Clause.txt` | The HTML and CSS |
| `LICENSE.BSD-3-Clause.txt` | Parts the core incorporates |
| `LICENSE.OFL-1.1.txt` | The Orbitron font |

The images are CC BY-SA 3.0, by the URL in `noVNC-LICENSE.txt`. `CREDITS.md`,
"Docker images — the live workstation desktop", is the summary. Moving KasmVNC's
version means reading these again from the client commit that release names.
