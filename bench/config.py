"""Locations of tool runtimes and worker scripts."""

from __future__ import annotations

import shutil

from bench.paths import REPO_ROOT

WORKERS_DIR = REPO_ROOT / "bench" / "workers"

# Isolated tool environments / runtimes.
CRG_VENV_PYTHON = REPO_ROOT / ".venv-crg" / "bin" / "python"
CRG_WORKER = WORKERS_DIR / "crg_worker.py"

SEMBLE_DOCKER_IMAGE = "cgbench-semble:latest"
SEMBLE_WORKER = WORKERS_DIR / "semble_worker.py"  # baked into the image

SOOP_DOCKER_IMAGE = "cgbench-soop:latest"
SOOP_WORKER = WORKERS_DIR / "soop_worker.mjs"  # baked into the image

CODEGRAPH_BIN = shutil.which("codegraph") or "codegraph"

# Where graph DBs are written during a run (kept out of the checkouts).
SCRATCH_DIR = REPO_ROOT / ".scratch"
