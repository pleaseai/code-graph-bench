# soop (RPG) worker image (linux/amd64).
#
# soop's native tree-sitter backend (@kreuzberg/tree-sitter-language-pack) bundles
# prebuilt .node bindings for darwin-arm64 / linux-x64 / linux-arm64 / win32, but
# NOT darwin-x64 — so soop can't run natively on Intel Macs. This image runs the
# soop worker on linux/amd64, where the bundled linux-x64 binding loads.
#
# Runs under NODE (not Bun): soop's SemanticCache hard-requires better-sqlite3,
# which Bun doesn't support. Node loads the native better-sqlite3 addon fine.
#
# Benchmarks the PUBLISHED @pleaseai/soop (parity with semble/crg/codegraph
# releases), in free/deterministic no-LLM mode.
FROM --platform=linux/amd64 node:22-bookworm-slim

# git for soop's gitignore handling; python3/make/g++ for better-sqlite3 native build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG SOOP_VERSION=0.1.33
# better-sqlite3 is a runtime peer dep of @pleaseai/soop that isn't auto-installed.
RUN npm init -y >/dev/null && npm install --no-audit --no-fund \
        "@pleaseai/soop@${SOOP_VERSION}" better-sqlite3

COPY bench/workers/soop_worker.mjs /app/soop_worker.mjs

ENV SOOP_IMPORT=@pleaseai/soop SOOP_CACHE_DIR=/tmp/rpgcache
ENTRYPOINT ["node", "/app/soop_worker.mjs"]
