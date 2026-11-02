# SPDX-License-Identifier: AGPL-3.0-or-later
# `B1729`. Chatterbox Turbo (Resemble AI, MIT), the voice Pantheon speaks
# with on a server with an NVIDIA GPU (`server.py` says what it serves).
# Started by the NVIDIA overlay (`docker/gpu.nvidia.yml`, and the standalone
# `docker-compose.gpu-nvidia.yml`); Pantheon finds it at
# `PANTHEON_CHATTERBOX_URL` and its "Automatic" voice prefers it to Kokoro
# while it answers.
#
# The base is PyTorch's own CUDA 12.4 runtime image, at the torch and
# torchaudio chatterbox-tts 0.1.7 pins (2.6.0), pinned to its digest so a
# rebuild cannot change it unseen. The weights (`ResembleAI/chatterbox-turbo`
# on Hugging Face, MIT) are fetched while the image is built, the way the
# main image bakes its models (`BAKE_MODELS`), and the container then runs
# offline (`HF_HUB_OFFLINE`): it reaches nothing at run time (`Law 16`).
# About 3 GB of GPU memory once loaded.
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime@sha256:77f17f843507062875ce8be2a6f76aa6aa3df7f9ef1e31d9d7432f4b0f563dee

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    CHATTERBOX_MODEL_DIR=/opt/chatterbox/model \
    CHATTERBOX_VOICES_DIR=/voices \
    CHATTERBOX_PORT=8004

WORKDIR /opt/chatterbox
COPY requirements.txt ./
# torch and torchaudio stay the image's: they are the versions chatterbox-tts
# pins, so pip has nothing to replace.
RUN pip install -r requirements.txt \
    && python -c "import torch, torchaudio; assert torch.__version__.startswith('2.6.0'), torch.__version__"

ARG CHATTERBOX_REPO=ResembleAI/chatterbox-turbo
RUN python -c "import sys; from huggingface_hub import snapshot_download; snapshot_download(sys.argv[1], local_dir=sys.argv[2], allow_patterns=['*.safetensors', '*.json', '*.txt', '*.pt', '*.model'])" \
        "$CHATTERBOX_REPO" "$CHATTERBOX_MODEL_DIR" \
    && test -f "$CHATTERBOX_MODEL_DIR/t3_turbo_v1.safetensors" \
    && test -f "$CHATTERBOX_MODEL_DIR/s3gen_meanflow.safetensors" \
    && test -f "$CHATTERBOX_MODEL_DIR/ve.safetensors" \
    && test -f "$CHATTERBOX_MODEL_DIR/conds.pt" \
    && rm -rf "$CHATTERBOX_MODEL_DIR/.cache" \
    && mkdir -p "$CHATTERBOX_VOICES_DIR"

# Offline from here on. librosa's numba functions cache what they compile
# beside their own source unless told otherwise, which the unprivileged user
# below cannot write: it would refuse to import.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/tmp/huggingface \
    NUMBA_CACHE_DIR=/tmp/numba

COPY server.py ./
RUN useradd --system --uid 10040 --no-create-home --home-dir /tmp chatterbox
USER chatterbox
EXPOSE 8004
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import json,sys,urllib.request as u; sys.exit(0 if json.load(u.urlopen('http://127.0.0.1:8004/health', timeout=5)).get('ok') else 1)"
CMD ["python", "server.py"]
