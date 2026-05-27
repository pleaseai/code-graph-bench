#!/usr/bin/env python
"""Standalone code-review-graph worker (runs inside .venv-crg).

Faithful to code-review-graph's own eval sequence (eval/runner.py):
``GraphStore`` -> ``full_build`` -> ``run_post_processing`` -> ``hybrid_search``.
No embeddings are computed (crg's published eval is lexical FTS/keyword), which
also keeps it offline and avoids torch — matching how the tool is benchmarked
upstream.

Stdin: a JSON job. Stdout: a JSON result. No dependency on the `bench` package.

Job (op="search"):
    {"op":"search","repo_path":str,"db_path":str,"queries":[str],"k":int,"runs":int}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _build(repo_path: Path, db_path: Path):
    from code_review_graph.graph import GraphStore
    from code_review_graph.incremental import full_build
    from code_review_graph.postprocessing import run_post_processing

    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = GraphStore(str(db_path))
    t0 = time.perf_counter()
    full_build(repo_path, store)
    build_ms = (time.perf_counter() - t0) * 1000.0
    t1 = time.perf_counter()
    run_post_processing(store)
    post_ms = (time.perf_counter() - t1) * 1000.0
    return store, build_ms, post_ms


def _rel(path: str | None, repo_path: Path) -> str | None:
    if not path:
        return path
    try:
        return str(Path(path).resolve().relative_to(repo_path.resolve()))
    except ValueError:
        return path


def _hit(d: dict, repo_path: Path) -> dict:
    sig = " ".join(str(d.get(k) or "") for k in ("name", "signature", "params", "return_type"))
    return {
        "file_path": _rel(d.get("file_path"), repo_path),
        "start_line": d.get("line_start"),
        "end_line": d.get("line_end"),
        "symbol": d.get("qualified_name"),
        "name": d.get("name"),
        "kind": d.get("kind"),
        "score": float(d.get("score", 0.0)),
        # crg returns a node reference, not code body: payload to locate the symbol.
        "n_chars": len(f"{_rel(d.get('file_path'), repo_path)} {d.get('qualified_name','')} {sig}"),
    }


def main() -> None:
    job = json.load(sys.stdin)
    from code_review_graph.search import hybrid_search

    repo = Path(job["repo_path"])
    db_path = Path(job["db_path"])
    k = int(job.get("k", 10))
    runs = int(job.get("runs", 5))

    store, build_ms, post_ms = _build(repo, db_path)
    stats = store.get_stats()
    out_stats = {
        "total_nodes": getattr(stats, "total_nodes", None),
        "total_edges": getattr(stats, "total_edges", None),
        "files_count": getattr(stats, "files_count", None),
    }

    results = []
    for q in job["queries"]:
        latencies = []
        hits_payload = None
        for i in range(max(1, runs)):
            s = time.perf_counter()
            rows = hybrid_search(store, q, limit=k)
            latencies.append((time.perf_counter() - s) * 1000.0)
            if i == 0:
                hits_payload = [_hit(r, repo) for r in rows]
        results.append({"query": q, "latencies_ms": latencies, "hits": hits_payload})

    json.dump(
        {
            "index_ms": build_ms + post_ms,
            "build_ms": build_ms,
            "post_ms": post_ms,
            "stats": out_stats,
            "db_bytes": db_path.stat().st_size if db_path.exists() else None,
            "results": results,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
