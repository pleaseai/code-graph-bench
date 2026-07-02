"""Arm H — hybrid pipeline (csp anchor → LSP + soop traversal).

Arm C showed a semantic retriever fixes the graph tools' anchor problem.
Arm H composes three *complementary* tools end to end:

  csp   (semantic+lexical retrieval) localizes the NL query to file+lines,
  LSP   (compiler/type-checker)      resolves the symbol there and expands
                                     precise one-hop callers/callees,
  soop  (repository planning graph)  expands its own dependency edges from
                                     the same anchor.

Reported per repo, side by side:
  csp→lsp        anchor from csp, LSP callHierarchy neighbors
  csp→soop       anchor from csp, soop dependency-graph neighbors
  csp→lsp+soop   union of both neighbor sets (the full hybrid)

Scored exactly like Arm B/C (anchor-found × neighbor recall on crg's
multi_hop_tasks), on the graph-SHA checkout.
"""

from __future__ import annotations

import json
import time
from datetime import date

import numpy as np
from rich.console import Console
from rich.table import Table

from bench.adapters.csp_adapter import CspAdapter
from bench.adapters.lsp_adapter import LspAdapter
from bench.adapters.soop_adapter import SoopAdapter
from bench.fetch import fetch_repo
from bench.goldset import load_corpus, load_graph_config
from bench.paths import RESULTS_DIR, checkout_path

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


def _union_rows(tasks: list, lsp_rows: list[dict], soop_rows: list[dict]) -> list[dict]:
    by_id = lambda rows: {r["task_id"]: r for r in rows}
    lsp_by, soop_by = by_id(lsp_rows), by_id(soop_rows)
    out = []
    for t in tasks:
        a, b = lsp_by.get(t.id), soop_by.get(t.id)
        parts = [r for r in (a, b) if r]
        names = set().union(*(set(r.get("neighbor_names", [])) for r in parts)) if parts else set()
        found = any(r["anchor_found"] for r in parts)
        ranks = [r["anchor_rank"] for r in parts if r["anchor_found"] and r["anchor_rank"] >= 0]
        expected = [e.lower() for e in t.expected_neighbor_names]
        matched = sum(1 for e in expected if e in names)
        recall = matched / len(expected) if expected else 0.0
        out.append({
            "task_id": t.id, "anchor_found": found,
            "anchor_rank": min(ranks) if ranks else -1,
            "neighbor_count": len(names), "expected_count": len(expected),
            "matched_count": matched, "neighbor_recall": round(recall, 3),
            "score": round(recall, 3) if found else 0.0,
            "neighbor_names": sorted(names),
        })
    return out


def run_arm_h(repos: list[str] | None = None, k: int = 10) -> dict:
    corpus = load_corpus()
    specs = [corpus.get(r) for r in (repos or [])] if repos else corpus.with_graph()
    specs = [s for s in specs if s.has_graph]
    csp, lsp, soop = CspAdapter(), LspAdapter(), SoopAdapter()

    rows: list[dict] = []
    for spec in specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.graph_sha)
        cfg = load_graph_config(spec.name)
        tasks = list(cfg.multi_hop_tasks)
        if not tasks:
            continue
        nl_queries = [t.nl_query for t in tasks]
        topk = max((t.k for t in tasks), default=k)

        console.print(f"[cyan]Arm H[/] csp anchor search on {spec.name}…")
        try:
            srun = csp.run_search(spec.name, repo_path, nl_queries, k=topk, runs=1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]  csp failed on {spec.name}:[/] {e}")
            continue
        hits_by_query = {q.query: q.hits for q in srun.queries}
        anchor_hits = {
            t.id: [
                {"file": h.file_path, "start_line": h.start_line, "end_line": h.end_line}
                for h in hits_by_query.get(t.nl_query, [])
            ]
            for t in tasks
        }

        pipelines: dict[str, list[dict]] = {}
        for label, adapter in (("csp→lsp", lsp), ("csp→soop", soop)):
            console.print(f"[cyan]Arm H[/] {label} on {spec.name}…")
            try:
                pipelines[label] = adapter.combined(spec.name, repo_path, tasks, anchor_hits)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]  {label} failed:[/] {e}")
        if "csp→lsp" in pipelines and "csp→soop" in pipelines:
            pipelines["csp→lsp+soop"] = _union_rows(
                tasks, pipelines["csp→lsp"], pipelines["csp→soop"])

        for label, prows in pipelines.items():
            rows.append({"repo": spec.name, "pipeline": label,
                         **_agg(prows), "rows": prows})

    out = {"arm": "h_hybrid", "date": str(date.today()), "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"arm_h-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _print(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]no results[/]")
        return
    t = Table(title="Arm H — hybrid (csp anchor → LSP/soop traverse)")
    for c in ("repo", "pipeline", "tasks", "anchor found", "neighbor recall", "score"):
        t.add_column(c)
    for r in sorted(rows, key=lambda x: (x["repo"], x["pipeline"])):
        t.add_row(
            r["repo"], r["pipeline"], str(r["n"]),
            f'{r["anchor_found_rate"]:.2f}', f'{r["mean_recall"]:.3f}',
            f'{r["mean_score"]:.3f}',
        )
    console.print(t)
