#!/usr/bin/env python
"""Standalone semble worker (runs inside .venv-semble).

Stdin: a JSON job. Stdout: a JSON result. No dependency on the `bench` package
so it can run under semble's isolated environment.

Job:
    {"op": "search", "repo_path": str, "root": str|null,
     "queries": [str, ...], "k": int, "runs": int}

Result:
    {"index_ms": float, "stats": {...},
     "results": [{"query": str, "latencies_ms": [float],
                  "hits": [{"file_path","start_line","end_line","symbol",
                            "score","n_chars"}]}]}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _hit(r):
    c = r.chunk
    return {
        "file_path": c.file_path,
        "start_line": c.start_line,
        "end_line": c.end_line,
        "symbol": None,  # semble chunks are line ranges, not named symbols
        "score": float(r.score),
        "n_chars": len(c.content or ""),
    }


def main() -> None:
    job = json.load(sys.stdin)
    from semble import SembleIndex

    repo = Path(job["repo_path"])
    target = repo / job["root"] if job.get("root") else repo
    k = int(job.get("k", 10))
    runs = int(job.get("runs", 5))

    t0 = time.perf_counter()
    index = SembleIndex.from_path(str(target))
    index_ms = (time.perf_counter() - t0) * 1000.0

    stats = index.stats
    out_stats = {
        "indexed_files": getattr(stats, "indexed_files", None),
        "total_chunks": getattr(stats, "total_chunks", None),
    }

    results = []
    for q in job["queries"]:
        latencies = []
        hits_payload = None
        for i in range(max(1, runs)):
            s = time.perf_counter()
            hits = index.search(q, top_k=k)
            latencies.append((time.perf_counter() - s) * 1000.0)
            if i == 0:
                hits_payload = [_hit(h) for h in hits]
        results.append({"query": q, "latencies_ms": latencies, "hits": hits_payload})

    json.dump({"index_ms": index_ms, "stats": out_stats, "results": results}, sys.stdout)


if __name__ == "__main__":
    main()
