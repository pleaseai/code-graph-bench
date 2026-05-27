"""Arm A — search quality (NL query -> relevant code).

All tools index the same retrieval-SHA checkout of each repo and answer the
semble-derived gold queries. Reports NDCG@10/@5, Recall@10, MRR, mean returned
tokens, and query latency, broken down by query category.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table

from bench.config import SCRATCH_DIR
from bench.fetch import fetch_repo
from bench.goldset import load_corpus, load_retrieval_tasks
from bench.metrics import evaluate_query
from bench.paths import RESULTS_DIR, checkout_path
from bench.runners.registry import SEARCH_TOOLS, get_adapter

console = Console()


def _aggregate(tool: str, version: str, modality: str, repo: str, run, per_query: list[dict]) -> dict:
    cat_ndcg: dict[str, list[float]] = {}
    for m in per_query:
        cat_ndcg.setdefault(m["category"], []).append(m["ndcg@10"])
    # one representative latency per query = median of its runs
    q_latencies = [statistics.median(q.latencies_ms) for q in run.queries if q.latencies_ms]
    mean = lambda key: float(np.mean([m[key] for m in per_query])) if per_query else 0.0
    return {
        "tool": tool, "version": version, "modality": modality, "repo": repo,
        "n_queries": len(per_query),
        "ndcg@10": mean("ndcg@10"), "ndcg@5": mean("ndcg@5"),
        "recall@10": mean("recall@10"), "mrr": mean("mrr"),
        "tokens": mean("tokens"),
        "index_ms": run.index_ms,
        "latency_p50_ms": float(np.percentile(q_latencies, 50)) if q_latencies else None,
        "latency_p95_ms": float(np.percentile(q_latencies, 95)) if q_latencies else None,
        "by_category": {c: float(np.mean(v)) for c, v in sorted(cat_ndcg.items())},
        "per_query": per_query,
    }


def run_arm_a(repos: list[str] | None = None, tools: list[str] | None = None, k: int = 10,
              runs: int = 5) -> dict:
    corpus = load_corpus()
    repo_specs = [corpus.get(r) for r in repos] if repos else list(corpus.repos)
    tools = tools or SEARCH_TOOLS
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for spec in repo_specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.retrieval_sha)
        tasks = load_retrieval_tasks(spec.name)
        queries = [t.query for t in tasks]
        for tool in tools:
            adapter = get_adapter(tool)
            console.print(f"[cyan]Arm A[/] {tool} on {spec.name} ({len(queries)} queries)…")
            try:
                run = adapter.run_search(spec.name, repo_path, queries, k=k, runs=runs)
            except Exception as e:  # noqa: BLE001 - record & continue
                console.print(f"[red]  {tool} failed:[/] {e}")
                continue
            by_query = {q.query: q.hits for q in run.queries}
            per_query = [evaluate_query(t, by_query.get(t.query, [])) for t in tasks]
            rows.append(_aggregate(tool, adapter.version(), adapter.search_modality(),
                                   spec.name, run, per_query))

    out = {"arm": "a_retrieval", "date": str(date.today()), "k": k, "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"arm_a-{stamp}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _print(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]no results[/]")
        return
    t = Table(title="Arm A — search quality (mean over queries)")
    for c in ("repo", "tool", "modality", "NDCG@10", "NDCG@5", "Recall@10", "MRR",
              "tokens", "index ms", "p50 ms"):
        t.add_column(c)
    for r in sorted(rows, key=lambda x: (x["repo"], -x["ndcg@10"])):
        t.add_row(
            r["repo"], r["tool"], r["modality"].split(" ")[0],
            f'{r["ndcg@10"]:.3f}', f'{r["ndcg@5"]:.3f}', f'{r["recall@10"]:.3f}',
            f'{r["mrr"]:.3f}', f'{r["tokens"]:.0f}', f'{r["index_ms"]:.0f}',
            f'{r["latency_p50_ms"]:.1f}' if r["latency_p50_ms"] is not None else "-",
        )
    console.print(t)
