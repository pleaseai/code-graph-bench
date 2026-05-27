# semble worker image (linux/amd64).
#
# semble pins tree-sitter-language-pack to >=1.0,!=1.6.3,<1.8.0. That range has
# manylinux x86_64 wheels (1.6.2) but NO x86_64-macOS wheel/sdist, so semble is
# unrunnable on Intel Macs natively. This image runs the semble worker in a
# linux/amd64 environment where the correct wheels exist.
#
# The model (potion-code-16M) is baked in at build time for offline, deterministic runs.
FROM --platform=linux/amd64 python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Pin tree-sitter-language-pack into semble's supported range (gets 1.6.2 wheel on linux/amd64).
RUN pip install --no-cache-dir \
        "semble[mcp]" \
        "tree-sitter-language-pack>=1.0,!=1.6.3,<1.8.0"

# Bake the embedding model into the image so runtime is offline & deterministic.
RUN python -c "from semble.model import load_model; load_model()" \
    || python -c "from model2vec import StaticModel; StaticModel.from_pretrained('minishlab/potion-code-16M')"

COPY bench/workers/semble_worker.py /app/semble_worker.py
WORKDIR /app

# Offline + quiet HF at runtime.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false

ENTRYPOINT ["python", "/app/semble_worker.py"]
