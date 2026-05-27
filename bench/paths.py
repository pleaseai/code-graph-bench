"""Canonical filesystem locations for the benchmark."""

from __future__ import annotations

from pathlib import Path

# bench/paths.py -> bench/ -> repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "bench"
GOLDSET_DIR = BENCH_DIR / "goldset"
RETRIEVAL_DIR = GOLDSET_DIR / "retrieval"
GRAPH_DIR = GOLDSET_DIR / "graph"
CORPUS_FILE = BENCH_DIR / "corpus.json"

# Cloned repo snapshots live here (git-ignored). One checkout per (repo, sha).
CHECKOUTS_DIR = REPO_ROOT / "checkouts"
RESULTS_DIR = REPO_ROOT / "results"


def checkout_path(repo: str, sha: str) -> Path:
    """Directory for a specific pinned snapshot of a repo."""
    return CHECKOUTS_DIR / f"{repo}@{sha[:12]}"
