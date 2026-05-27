"""Arm B — graph capability (graph tools only: crg, codegraph).

Primary metric: multi-hop retrieval (search -> anchor -> one-hop traversal),
scored against code-review-graph's curated ``multi_hop_tasks`` whose
``expected_neighbor_names`` are tool-independent. Each tool uses its OWN search
to find the anchor and its OWN traversal to expand — this is the end-to-end
graph pipeline that Arm C later augments with semble as the anchor finder.

Secondary: impact accuracy (blast-radius) reproducing crg's own methodology,
run only when the graph checkout has enough git history (see fetch.deepen).
"""

from __future__ import annotations

import json
import time
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table

from bench.fetch import deepen_for_commits, fetch_repo
from bench.goldset import load_corpus, load_graph_config
from bench.metrics import precision_recall_f1
from bench.paths import RESULTS_DIR, checkout_path
from bench.runners.registry import GRAPH_TOOLS, get_adapter

console = Console()


def _agg_multihop(tool: str, version: str, repo: str, rows: list[dict]) -> dict:
    if not rows:
        return {"tool": tool, "version": version, "repo": repo, "n_tasks": 0}
    found = [r for r in rows if r["anchor_found"]]
    ranks = [r["anchor_rank"] for r in found if r["anchor_rank"] >= 0]
    return {
        "tool": tool, "version": version, "repo": repo, "n_tasks": len(rows),
        "anchor_found_rate": len(found) / len(rows),
        "mean_anchor_rank": float(np.mean(ranks)) if ranks else None,
        "mean_neighbor_recall": float(np.mean([r["neighbor_recall"] for r in rows])),
        "mean_score": float(np.mean([r["score"] for r in rows])),
        "rows": rows,
    }


def _agg_impact(tool: str, repo: str, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        m = precision_recall_f1(set(r["predicted"]), set(r["actual"]))
        out.append({"tool": tool, "repo": repo, "sha": r["sha"], **m})
    return out


def run_arm_b(repos: list[str] | None = None, tools: list[str] | None = None,
              impact: bool = True) -> dict:
    corpus = load_corpus()
    specs = [corpus.get(r) for r in (repos or [])] if repos else corpus.with_graph()
    specs = [s for s in specs if s.has_graph]
    tools = tools or GRAPH_TOOLS

    multihop_rows: list[dict] = []
    impact_rows: list[dict] = []
    for spec in specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.graph_sha)
        cfg = load_graph_config(spec.name)
        for tool in tools:
            adapter = get_adapter(tool)
            if cfg.multi_hop_tasks:
                console.print(f"[cyan]Arm B[/] multihop {tool} on {spec.name} "
                              f"({len(cfg.multi_hop_tasks)} tasks)…")
                try:
                    rows = adapter.multihop(spec.name, repo_path, list(cfg.multi_hop_tasks))
                    multihop_rows.append(_agg_multihop(tool, adapter.version(), spec.name, rows))
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]  {tool} multihop failed:[/] {e}")
            if impact and cfg.test_commits and hasattr(adapter, "impact"):
                ok = deepen_for_commits(repo_path, spec.url,
                                        [tc.sha for tc in cfg.test_commits])
                if not ok:
                    console.print(f"[yellow]  skip impact ({spec.name}): no git history[/]")
                    continue
                console.print(f"[cyan]Arm B[/] impact {tool} on {spec.name}…")
                try:
                    rows = adapter.impact(spec.name, repo_path, list(cfg.test_commits))
                    impact_rows.extend(_agg_impact(tool, spec.name, rows))
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]  {tool} impact failed:[/] {e}")

    out = {"arm": "b_graph", "date": str(date.today()),
           "multihop": multihop_rows, "impact": impact_rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"arm_b-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(multihop_rows, impact_rows)
    return out


def _print(multihop_rows, impact_rows) -> None:
    if multihop_rows:
        t = Table(title="Arm B — multi-hop retrieval (search → anchor → traverse)")
        for c in ("repo", "tool", "tasks", "anchor found", "mean rank",
                  "neighbor recall", "score"):
            t.add_column(c)
        for r in sorted(multihop_rows, key=lambda x: (x["repo"], -x.get("mean_score", 0))):
            t.add_row(
                r["repo"], r["tool"], str(r["n_tasks"]),
                f'{r.get("anchor_found_rate", 0):.2f}',
                f'{r["mean_anchor_rank"]:.1f}' if r.get("mean_anchor_rank") is not None else "-",
                f'{r.get("mean_neighbor_recall", 0):.3f}', f'{r.get("mean_score", 0):.3f}',
            )
        console.print(t)
    if impact_rows:
        t = Table(title="Arm B — impact accuracy (blast-radius, crg methodology)")
        for c in ("repo", "tool", "commit", "predicted", "actual", "P", "R", "F1"):
            t.add_column(c)
        for r in impact_rows:
            t.add_row(r["repo"], r["tool"], r["sha"][:8], str(r["predicted"]),
                      str(r["actual"]), f'{r["precision"]:.2f}', f'{r["recall"]:.2f}',
                      f'{r["f1"]:.2f}')
        console.print(t)
