<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Getting a change from a session onto the server

`B1409`. This page exists because the procedure used to live in chat messages,
and a procedure in a chat message is one nobody can find twice (`Law 15`). The
failure it is written against is this one:

```
PS C:\Users\josep\Projects\odysseus> & 'C:\Program Files\Git\bin\bash.exe' .pantheon-transfer/apply-release.sh
/usr/bin/bash: .pantheon-transfer/apply-release.sh: No such file or directory
```

That path existed in one session and not the next. The script is committed now,
at [`.pantheon/apply-release.sh`](../.pantheon/apply-release.sh), and that path
does not move.

## The chain, end to end

```
  session  ──►  this clone  ──►  git push  ──►  docker-publish.yml
                                                      │
                                      ghcr.io/impanick/pantheon:latest
                                                      │
                                     server: docker compose pull && up -d
```

Two things about the last step are easy to get wrong:

* **`pull_policy: always` only fires when a container is CREATED.** `up -d` on
  an already-running container does not re-pull, so the explicit
  `docker compose pull` is the step that actually moves the image. Running only
  `up -d` is how a server sits on a two-week-old build while every link above
  it is green.
* The build has to be green *before* the pull. `docker-publish.yml` is what
  pushes the tag; pulling before it finishes gets you the previous image.

## Which of the two paths you are on

**A session has a live bridge to this machine.** Then it fast-forwards this
clone itself and there is nothing to apply — all that is left is:

```powershell
cd C:\Users\josep\Projects\odysseus
git push origin main
```

Check before reaching for anything else:

```powershell
git log --oneline -1          # is the work already here?
git rev-list --count origin/main..HEAD   # how many commits are waiting?
```

If the first shows the newest commit and the second is non-zero, you are on
this path. **This is the normal case.**

**No bridge, so a bundle arrives instead.** Two git commands, and they depend
on nothing but git:

```powershell
cd C:\Users\josep\Projects\odysseus
git fetch ~/Downloads/pantheon.bundle main:refs/remotes/bundle/main
git merge --ff-only refs/remotes/bundle/main
```

That is the whole mechanism, and it is written out here rather than hidden
behind a script on purpose: **the script cannot help with the delivery that
installs it.** A clone sitting on an older commit does not have
`.pantheon/apply-release.sh` yet, which is the chicken-and-egg the committed
path does not escape — so the two commands above are the answer that always
works, and the script is a convenience for every delivery after this one.

`--ff-only` is what makes it safe: a bundle that is not a fast-forward is
refused and nothing is changed.

The script adds guards around those two commands — it verifies the bundle,
refuses to touch anything while tracked files are dirty, reads the bundle's own
ref name rather than assuming it, deletes the spent bundle so the next run
cannot apply a stale one, and prints the three steps above:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' .pantheon/apply-release.sh ~/Downloads/pantheon.bundle
```

Both were rehearsed against a clone at the real previous tip on 2026-10-20,
including a missing bundle, a dirty tracked file (refused, nothing changed) and
a clean fast-forward of ten commits.

## Why a bundle at all

A cloud session cannot push to `ImPanick/pantheon`. The git proxy answers 403
(`not in this session's authorized repository set`) for **every** repository,
public ones included — so this is not a missing whitelist entry but a session
with no GitHub source attached, and the `add_repo` tool the error names is not
available in that session. Reads work: `api.github.com` answers 200 and an
anonymous `git ls-remote` succeeds, which is what made git look functional for
a long time while no push had ever happened.

Measured 2026-10-18: zero push entries across 334 reflog entries going back to
2026-09-27, against 15 fetches and 5 clones.

The two ways to make pushing belong to the session rather than to you:

1. **Start the task against the GitHub repository** rather than only a folder,
   so the git proxy has it in scope. This is the one that ends the problem.
2. **Computer use, through GitHub Desktop's Push button** — measured working
   on 2026-10-21, 26 commits, `87207630` → `208f60d6`.

   Not through a terminal. That was this page's first answer and it is wrong:
   computer use grants terminals and IDEs in **click-only** mode on purpose —
   *"you can see and left-click, but cannot type, press keys, or paste"* — so a
   session cannot type `git push` into PowerShell no matter what is enabled,
   and PowerShell is masked out of screenshots as well. A GUI client's Push
   button is a *click*, which is allowed, and GitHub Desktop carries its own
   GitHub sign-in so no credential passes through the session at all.

   Two practical notes from doing it: GitHub Desktop's window is owned by a
   versioned child process (`…\app-3.5.8\githubdesktop.exe`), which has to be
   granted separately from the launcher or the window is masked out of every
   screenshot; and it opens on whatever repository it last had, which may not
   be this one and may have uncommitted work in it.

A credential helper inside the bridge's Linux VM would also work and is the
worst of the three: it means a personal access token in plaintext in a
throwaway VM.
