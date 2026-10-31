# ---- the base: one Python patch release, for all three stages ----
# `B1667`. Every stage read `python:3.14-slim`, a minor line rather than a
# release, so a rebuild could swap the interpreter under the product with
# nothing in the tree saying so — `B445`'s class, which the compose files had
# already closed. Pinned to the patch release that tag resolved to when this
# was read from Docker Hub's tag list on 2026-10-29: `3.14-slim` and
# `3.14.10-slim` named the same amd64 (sha256:ec6a14df…697f2d) and arm64
# (sha256:29434a59…18ca1f) images, so this pins what a build was already
# getting. Dependabot's docker ecosystem proposes the next patch as a pull
# request; move all three `FROM`s together (`B1591`'s stage shares the base on
# purpose). tests/test_searxng_image_pinned.py holds every Dockerfile to it.

# ---- builder: patch + build wheels for Real-ESRGAN's broken-on-3.14 deps ----
# basicsr/gfpgan/facexlib read their version via exec()+locals()['__version__'],
# which raises KeyError on Python 3.13+ (PEP 667). Build patched wheels here so
# the final image / the Forge never has to compile the broken sdists. See
# docker/build-realesrgan-wheels.sh for the full rationale.
FROM python:3.14.10-slim AS realesrgan-wheels
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY docker/build-realesrgan-wheels.sh /usr/local/bin/build-realesrgan-wheels.sh
RUN bash /usr/local/bin/build-realesrgan-wheels.sh /wheels

# ---- js-without-comments: Pantheon's own JavaScript, served without comments ----
# `B1591` (`D-2026-10-29-02` §6). The repository's modules keep every comment
# (`Law 1`); the image serves them without, which took the 244 modules from
# 2,648 KB to 1,674 KB gzipped when it was measured. scripts/strip-js-comments.mjs
# finds the comments with acorn's parser (a regular expression is never read as
# a comment, nor a division as a regular expression), keeps every token on its
# line and column so a stack trace still points into the repository's file,
# keeps the licence notices, never touches static/lib/ (vendored), and proves
# each file is the same token stream before it writes it — a file it cannot
# prove stops the build. acorn is the one `dependencies` entry in
# package-lock.json, at an exact version whose sha512 `npm ci` checks. The
# stage runs on the base the other two use, with Debian's node (the one the
# app's stage installs below), so no new image enters the build.
FROM python:3.14.10-slim AS js-without-comments
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY scripts/strip-js-comments.mjs scripts/
COPY static/ static/
RUN node scripts/strip-js-comments.mjs /build /out

FROM python:3.14.10-slim

# P0-18. A published image is a distribution, and this one declared no licence
# anywhere in its metadata — the same failure class as P0-30, where the desktop
# builds shipped a dozen libraries with their attribution stripped because the
# payload was listed by hand. `docker inspect` now answers the question.
# `org.opencontainers.image.source` is deliberately absent: it has to point at
# a repository a reader can actually open, and that waits on P0-17.
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later"

# System deps. tmux is required by the Forge for background downloads/serves.
# openssh-client is required for Forge remote server tests, setup, probes,
# downloads, and serves from Docker installs.
# git/cmake are required when the Forge builds llama.cpp on first llama.cpp
# launch inside Docker.
# nodejs/npm provide npx for the built-in Browser MCP server.
# chromium provides the actual browser binary used by that MCP server.
# firefox-esr is the agent browser for a person without a workstation — their
# own headless Firefox, which they watch and take over in the app and the
# agent drives (`src/local_browser.py`, over WebDriver BiDi like the
# workstation's); fonts-dejavu-core gives its pages letters to draw.
# gosu lets the entrypoint drop privileges cleanly so signals still reach
# uvicorn directly (no extra shell layer like `su`/`sudo` would add).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    curl \
    git \
    nodejs \
    npm \
    chromium \
    firefox-esr \
    fonts-dejavu-core \
    tmux \
    openssh-client \
    gosu \
    libgl1 \
    libglib2.0-0t64 \
    libxcb1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# libgl1/libglib2.0-0t64/libxcb1 are runtime shared libs (libGL.so.1,
# libglib-2.0/libgthread, libxcb.so.1) that opencv-python (cv2) loads. The
# slim base omits them, so the Forge's "install realesrgan" path imports cv2
# and dies with `libxcb.so.1: cannot open shared object file` despite a clean
# pip install. Using full opencv-python (not -headless) because basicsr/gfpgan/
# facexlib/realesrgan all depend on the `opencv-python` distribution by name.
#
# libmagic1 is the shared lib (libmagic.so.1) that python-magic dlopens for
# content-based MIME sniffing in src/upload_handler.py. We install both here
# (libmagic1 + the python-magic wrapper, below) rather than in requirements.txt
# because python-magic resolves libmagic at import time: where the lib is
# absent the import can block or raise, so keeping it image-only avoids
# regressing pip/venv installs on hosts without libmagic. Debian always has the
# lib here, so the import is instant and detection actually works.

# Docker CLI (client only — daemon stays on the host via the
# /var/run/docker.sock mount). The Debian `docker.io` package ships
# dockerd but not the client binary on slim, so grab the static client
# tarball from download.docker.com instead.
ARG DOCKER_CLI_VERSION=29.6.2
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
         amd64) DARCH=x86_64 ;; \
         arm64) DARCH=aarch64 ;; \
         *) echo "unsupported arch $ARCH"; exit 1 ;; \
       esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
       -o /tmp/docker.tgz \
    && tar -xzf /tmp/docker.tgz -C /tmp \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

WORKDIR /app

# Install Python deps first (layer cache). Optional extras (PyMuPDF AGPL, etc.)
# are opt-in so the default image stays MIT-core; see requirements-optional.txt.
ARG INSTALL_OPTIONAL=false
COPY requirements.txt requirements-optional.txt requirements-image.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install --no-cache-dir -r requirements-optional.txt; fi

# python-magic powers content-based MIME sniffing in src/upload_handler.py.
# Image-only (not in requirements.txt) because it needs the libmagic1 system
# lib installed above; see the apt note near the top of this stage.
#
# `B321`. The version used to be written inline here, where Dependabot and the
# dependency audit could not see it. It now lives in requirements-image.txt for
# exactly that reason — same package, same pin, visible to the tooling.
RUN pip install --no-cache-dir -r requirements-image.txt

# Pre-install the patched basicsr/gfpgan/facexlib wheels built in the
# realesrgan-wheels stage (--no-deps keeps the image lean — torch & friends are
# pulled only when realesrgan is actually installed). With these dists already
# satisfied, the Forge's plain `pip install realesrgan` resolves them from
# wheels instead of rebuilding the sdists that fail on Python 3.14.
COPY --from=realesrgan-wheels /wheels/ /tmp/pantheon-wheels/
RUN pip install --no-cache-dir --no-deps /tmp/pantheon-wheels/*.whl \
    && rm -rf /tmp/pantheon-wheels

# `B1712`. The default local embedding model, fetched while the image is built
# so that memory and document search are semantic on a fresh install. Without
# it the in-process index had no model, Pantheon will not fetch one on its own
# (`allow_model_download`, `Law 16`), and every search fell back to keywords.
# Fetching here is the build reaching Hugging Face the way `pip install` reaches
# PyPI: a running install still reaches nobody. Kept outside /app/data and
# /app/.cache/huggingface, which compose bind-mounts over, and copied into the
# data volume by `docker/entrypoint.sh` (`seed_model_cache`) when that holds
# no model yet. The seed is fastembed's own cache layout, which it opens
# offline first. `--build-arg BAKE_MODELS=false` leaves it out.
ARG BAKE_MODELS=true
ARG FASTEMBED_SEED_MODEL=sentence-transformers/all-MiniLM-L6-v2
ENV PANTHEON_SEED_MODELS=/opt/pantheon/seed-models \
    PANTHEON_FASTEMBED_SEED_MODEL=${FASTEMBED_SEED_MODEL}
RUN if [ "$BAKE_MODELS" = "true" ]; then \
        python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1], cache_dir=sys.argv[2])" \
            "$FASTEMBED_SEED_MODEL" "$PANTHEON_SEED_MODELS/fastembed" \
        && test -n "$(find "$PANTHEON_SEED_MODELS/fastembed" -name '*.onnx' -print -quit)" \
        && chmod -R a+rX "$PANTHEON_SEED_MODELS"; \
    fi

# Copy app code
COPY . .

# `B1591`. Pantheon's own modules as the image serves them — the files `COPY .
# .` just wrote, without their comments (the `js-without-comments` stage above)
# — and `js-without-comments.json`, the record of which git blob each was made
# from, which `scripts/pantheon-deploy`'s byte check reads. The record is
# outside `static/`, so it is never served.
COPY --from=js-without-comments /out/ ./

# `B453`. The commit this image was built from, read by `GET /api/version`
# (`src/constants.build_commit`). `.git` is not copied in, so the build has to
# say it: `docker-publish.yml` passes `github.sha`, `scripts/pantheon-deploy`
# passes the checkout's HEAD, and a plain `docker compose build` passes
# whatever `PANTHEON_BUILD_COMMIT` holds in its environment — nothing, by
# default, and the app then answers `commit: null` rather than guessing.
# Declared after `COPY . .` so a new commit does not bust the dependency layers.
ARG PANTHEON_BUILD_COMMIT=""
ENV PANTHEON_BUILD_COMMIT=${PANTHEON_BUILD_COMMIT}

# Create data directory (mount a volume here for persistence)
RUN mkdir -p data logs services/cache/search

# Entrypoint that drops to PUID/PGID (default 1000:1000) and repairs
# ownership on the bind-mounted /app/data and /app/logs. Without this,
# the container runs as root and writes root-owned files into host
# bind mounts — any later non-root run (or a host user trying to
# update them) silently fails on EPERM, breaking skill extraction,
# prefs persistence, mail attachments, etc.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 7000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
