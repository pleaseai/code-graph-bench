"""csp (pleaseai/code-search) adapter — native Rust CLI.

csp is a chunk-based hybrid retriever: static code embeddings
(minishlab/potion-code-16M, local/offline) + BM25. The index is built with
``csp index <repo> -o <dir>`` into the bench scratch dir (keeps checkouts
clean) and queried with ``csp search <q> --index <dir>``. Query latency is
measured as CLI wall time and therefore INCLUDES process startup — like
codegraph, unlike semble/crg's in-process latency. Flagged in Perf; quality
metrics unaffected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from bench.adapters.base import Hit, QueryResult, SearchRun
from bench.config import CSP_BIN, SCRATCH_DIR


class CspAdapter:
    name = "csp"

    def version(self) -> str:
        try:
            out = subprocess.run([CSP_BIN, "--version"], capture_output=True, text=True)
            return out.stdout.strip() if out.returncode == 0 else "csp"
        except FileNotFoundError:
            return "csp (not found)"

    def search_modality(self) -> str:
        return "semantic+lexical (static embeddings + BM25)"

    def _index_dir(self, repo_path: Path) -> Path:
        return SCRATCH_DIR / "csp" / repo_path.name

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun:
        idx = self._index_dir(repo_path)
        if idx.exists():
            shutil.rmtree(idx)
        idx.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        build = subprocess.run(
            [CSP_BIN, "index", str(repo_path), "-o", str(idx)],
            capture_output=True, text=True,
        )
        index_ms = (time.perf_counter() - t0) * 1000.0
        if build.returncode != 0:
            raise RuntimeError(f"csp index failed:\n{build.stderr[-2000:]}")

        qrs = []
        for q in queries:
            latencies = []
            hits = None
            for i in range(max(1, runs)):
                s = time.perf_counter()
                res = subprocess.run(
                    [CSP_BIN, "search", q, "--index", str(idx), "-k", str(k)],
                    capture_output=True, text=True,
                )
                latencies.append((time.perf_counter() - s) * 1000.0)
                if i == 0:
                    hits = _parse_hits(res.stdout)
            qrs.append(QueryResult(query=q, hits=hits or [], latencies_ms=latencies))

        return SearchRun(
            tool=self.name, repo=repo, index_ms=index_ms, queries=qrs,
            stats=_stats(idx),
            db_bytes=sum(f.stat().st_size for f in idx.rglob("*") if f.is_file()),
        )


def _parse_hits(stdout: str) -> list[Hit]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    hits = []
    for r in data.get("results", []):
        c = r.get("chunk", {})
        hits.append(
            Hit(
                file_path=c.get("file_path"), start_line=c.get("start_line"),
                end_line=c.get("end_line"), symbol=None,
                score=float(r.get("score", 0.0)),
                n_chars=len(c.get("content") or ""),
            )
        )
    return hits


def _stats(idx: Path) -> dict:
    try:
        chunks = json.loads((idx / "chunks.json").read_text())
        return {"total_chunks": len(chunks)}
    except (OSError, json.JSONDecodeError):
        return {}
