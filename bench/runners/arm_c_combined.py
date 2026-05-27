"""Arm C — combined pipeline (semble as anchor-finder for the graph tools).

The unique contribution of this benchmark. Arm B showed the graph tools' own
lexical search struggles to locate the anchor symbol from a verbose NL query.
Here semble (semantic) localizes the query to a file+line region; the graph tool
resolves the symbol at that location *using its own index* and traverses from it.

For each graph tool we report, side by side:
  baseline  = tool's own search -> anchor -> traverse   (== Arm B)
  combined  = semble -> anchor -> tool's traverse
and the delta in anchor-found rate and neighbor recall.

Everything runs on the graph-SHA checkout so semble's file/line spans line up
with the graph tool's symbol spans.
"""

from __future__ import annotations

import json
import time
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table

from bench.adapters.semble_adapter import SembleAdapter
from bench.fetch import fetch_repo
from bench.goldset import load_corpus, load_graph_config
from bench.paths import RESULTS_DIR, checkout_path
from bench.runners.registry import GRAPH_TOOLS, get_adapter

console = Console()


def _agg(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "anchor_found_rate": 0.0, "mean_recall": 0.0, "mean_score": 0.0}
    found = [r for r in rows if r["anchor_found"]]
    return {
        "n": len(rows),
        "anchor_found_rate": len(found) / len(rows),
        "mean_recall": float(np.mean([r["neighbor_recall"] for r in rows])),
        "mean_score": float(np.mean([r["score"] for r in rows])),
    }


def run_arm_c(repos: list[str] | None = None, k: int = 10) -> dict:
    corpus = load_corpus()
    specs = [corpus.get(r) for r in (repos or [])] if repos else corpus.with_graph()
    specs = [s for s in specs if s.has_graph]
    semble = SembleAdapter()

    rows: list[dict] = []
    for spec in specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.graph_sha)
        cfg = load_graph_config(spec.name)
        if not cfg.multi_hop_tasks:
            continue
        nl_queries = [t.nl_query for t in cfg.multi_hop_tasks]
        topk = max((t.k for t in cfg.multi_hop_tasks), default=k)

        console.print(f"[cyan]Arm C[/] semble anchor search on {spec.name}…")
        try:
            srun = semble.run_search(spec.name, repo_path, nl_queries, k=topk, runs=1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]  semble failed on {spec.name}:[/] {e}")
            continue
        hits_by_query = {q.query: q.hits for q in srun.queries}
        semble_hits = {
            t.id: [
                {"file": h.file_path, "start_line": h.start_line, "end_line": h.end_line}
                for h in hits_by_query.get(t.nl_query, [])
            ]
            for t in cfg.multi_hop_tasks
        }

        for tool in GRAPH_TOOLS:
            adapter = get_adapter(tool)
            console.print(f"[cyan]Arm C[/] {tool} baseline vs combined on {spec.name}…")
            try:
                baseline = adapter.multihop(spec.name, repo_path, list(cfg.multi_hop_tasks))
                combined = adapter.combined(spec.name, repo_path,
                                            list(cfg.multi_hop_tasks), semble_hits)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]  {tool} failed:[/] {e}")
                continue
            b, c = _agg(baseline), _agg(combined)
            rows.append({
                "repo": spec.name, "tool": tool, "version": adapter.version(),
                "baseline": b, "combined": c,
                "delta_anchor_found": c["anchor_found_rate"] - b["anchor_found_rate"],
                "delta_recall": c["mean_recall"] - b["mean_recall"],
                "baseline_rows": baseline, "combined_rows": combined,
            })

    out = {"arm": "c_combined", "date": str(date.today()), "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"arm_c-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _print(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]no results[/]")
        return
    t = Table(title="Arm C — combined pipeline (semble anchor → graph traverse)")
    for c in ("repo", "graph tool", "anchor found B→C", "neighbor recall B→C",
              "Δ found", "Δ recall"):
        t.add_column(c)
    for r in sorted(rows, key=lambda x: (x["repo"], x["tool"])):
        b, c = r["baseline"], r["combined"]
        t.add_row(
            r["repo"], r["tool"],
            f'{b["anchor_found_rate"]:.2f} → {c["anchor_found_rate"]:.2f}',
            f'{b["mean_recall"]:.3f} → {c["mean_recall"]:.3f}',
            f'{r["delta_anchor_found"]:+.2f}', f'{r["delta_recall"]:+.3f}',
        )
    console.print(t)
