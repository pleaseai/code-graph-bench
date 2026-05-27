"""Perf — speed & footprint (cross-cutting dimension).

Cold index time (with parse/post-process breakdown for graph tools), query
latency percentiles, index disk footprint, and indexing throughput. Measured on
the retrieval-SHA checkout so it lines up with Arm A.

Caveats recorded in the output: codegraph query latency includes Node process
startup (CLI), whereas semble/crg query in-process; semble runs in Docker so its
index time includes container startup. Peak-RSS and incremental-update timing
are not yet captured (see README roadmap).
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table

from bench.fetch import fetch_repo
from bench.goldset import load_corpus, load_retrieval_tasks
from bench.paths import RESULTS_DIR, checkout_path
from bench.runners.registry import SEARCH_TOOLS, get_adapter

console = Console()


def run_perf(repos: list[str] | None = None, tools: list[str] | None = None,
             k: int = 10, runs: int = 5) -> dict:
    corpus = load_corpus()
    repo_specs = [corpus.get(r) for r in repos] if repos else list(corpus.repos)
    tools = tools or SEARCH_TOOLS

    rows: list[dict] = []
    for spec in repo_specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.retrieval_sha)
        queries = [t.query for t in load_retrieval_tasks(spec.name)]
        for tool in tools:
            adapter = get_adapter(tool)
            console.print(f"[cyan]Perf[/] {tool} on {spec.name}…")
            try:
                run = adapter.run_search(spec.name, repo_path, queries, k=k, runs=runs)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]  {tool} failed:[/] {e}")
                continue
            meds = [statistics.median(q.latencies_ms) for q in run.queries if q.latencies_ms]
            units = run.stats.get("total_chunks") or run.stats.get("total_nodes")
            rows.append({
                "tool": tool, "version": adapter.version(), "repo": spec.name,
                "language": spec.language,
                "index_ms": run.index_ms, "build_ms": run.build_ms, "post_ms": run.post_ms,
                "stats": run.stats, "db_bytes": run.db_bytes,
                "units": units,
                "throughput_units_per_s": (units / (run.index_ms / 1000.0))
                    if units and run.index_ms else None,
                "latency_p50_ms": _pct(meds, 50), "latency_p90_ms": _pct(meds, 90),
                "latency_p95_ms": _pct(meds, 95), "latency_p99_ms": _pct(meds, 99),
            })

    out = {"arm": "perf", "date": str(date.today()), "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"perf-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _pct(xs, p):
    return float(np.percentile(xs, p)) if xs else None


def _print(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]no results[/]")
        return
    t = Table(title="Perf — speed & footprint")
    for c in ("repo", "tool", "index ms", "build/post ms", "units", "units/s",
              "db MB", "p50 ms", "p95 ms", "p99 ms"):
        t.add_column(c)
    for r in sorted(rows, key=lambda x: (x["repo"], x["tool"])):
        bp = (f'{r["build_ms"]:.0f}/{r["post_ms"]:.0f}'
              if r["build_ms"] is not None else "-")
        db = f'{r["db_bytes"]/1e6:.1f}' if r["db_bytes"] else "-"
        thr = f'{r["throughput_units_per_s"]:.0f}' if r["throughput_units_per_s"] else "-"
        t.add_row(
            r["repo"], r["tool"], f'{r["index_ms"]:.0f}', bp,
            str(r["units"] or "-"), thr, db,
            *[f'{r[f"latency_p{p}_ms"]:.1f}' if r[f"latency_p{p}_ms"] is not None else "-"
              for p in (50, 95, 99)],
        )
    console.print(t)
