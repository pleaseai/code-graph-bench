"""Render results/*.json into markdown tables (latest run per arm)."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from bench.paths import RESULTS_DIR

console = Console()


def _latest(prefix: str) -> Path | None:
    files = sorted(RESULTS_DIR.glob(f"{prefix}-*.json"))
    return files[-1] if files else None


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _arm_a_md(data: dict) -> str:
    rows = []
    for r in sorted(data["results"], key=lambda x: (x["repo"], -x["ndcg@10"])):
        rows.append([
            r["repo"], r["tool"], r["modality"],
            f'{r["ndcg@10"]:.3f}', f'{r["ndcg@5"]:.3f}', f'{r["recall@10"]:.3f}',
            f'{r["mrr"]:.3f}', f'{r["tokens"]:.0f}',
        ])
    body = _md_table(
        ["repo", "tool", "modality", "NDCG@10", "NDCG@5", "Recall@10", "MRR", "tokens"],
        rows,
    )
    return f"## Arm A — search quality ({data['date']}, k={data.get('k')})\n\n{body}\n"


def _perf_md(data: dict) -> str:
    rows = []
    for r in sorted(data["results"], key=lambda x: (x["repo"], x["tool"])):
        rows.append([
            r["repo"], r["tool"], f'{r["index_ms"]:.0f}',
            str(r.get("units") or "-"),
            f'{r["throughput_units_per_s"]:.0f}' if r.get("throughput_units_per_s") else "-",
            f'{r["db_bytes"]/1e6:.1f}' if r.get("db_bytes") else "-",
            f'{r["latency_p50_ms"]:.1f}' if r.get("latency_p50_ms") is not None else "-",
            f'{r["latency_p95_ms"]:.1f}' if r.get("latency_p95_ms") is not None else "-",
        ])
    body = _md_table(
        ["repo", "tool", "index ms", "units", "units/s", "db MB", "p50 ms", "p95 ms"],
        rows,
    )
    return f"## Perf — speed & footprint ({data['date']})\n\n{body}\n"


RENDERERS = {"a": ("arm_a", _arm_a_md), "perf": ("perf", _perf_md)}


def render(arm: str | None = None) -> None:
    keys = [arm] if arm else list(RENDERERS)
    chunks = []
    for key in keys:
        if key not in RENDERERS:
            continue
        prefix, fn = RENDERERS[key]
        path = _latest(prefix)
        if not path:
            console.print(f"[yellow]no results for {key}[/]")
            continue
        chunks.append(fn(json.loads(path.read_text())))
    md = "\n".join(chunks)
    print(md)
