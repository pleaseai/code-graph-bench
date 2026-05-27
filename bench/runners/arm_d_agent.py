"""Arm D — end-to-end agent efficiency (OPTIONAL, costs real Claude API spend).

For each repo, runs Claude Code headless (`claude -p`) on a fixed question with
each tool's MCP server attached, plus a no-tool baseline, and parses stream-json
for tokens / cost / duration / tool-calls. Generalizes codegraph's audit harness
(parse-run.mjs). Reports the no-tool-relative delta per tool.

This arm is GUARDED: it does nothing unless ``confirm=True`` and a positive
``budget_usd`` are passed (CLI: ``cgbench run d --confirm --budget 2``), because
each run spends money. semble's MCP requires the Docker image with an MCP
entrypoint and is left as a documented extension; crg and codegraph serve MCP
natively.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from bench.config import CODEGRAPH_BIN, CRG_VENV_PYTHON
from bench.fetch import fetch_repo
from bench.goldset import load_corpus, load_graph_config
from bench.paths import RESULTS_DIR, checkout_path

console = Console()

# One representative question per repo (architecture/flow style).
QUESTIONS = {
    "flask": "How does Flask dispatch an incoming HTTP request to a view function?",
    "fastapi": "How does FastAPI resolve and inject dependencies for a request?",
    "httpx": "How does httpx send a request through its transport layer?",
    "express": "How does Express route a request through its middleware chain?",
    "gin": "How does gin route a request through its middleware chain?",
}


def _mcp_config(tool: str, repo_path: Path) -> dict:
    if tool == "none":
        return {"mcpServers": {}}
    if tool == "crg":
        return {"mcpServers": {"crg": {
            "command": str(CRG_VENV_PYTHON.parent / "code-review-graph"),
            "args": ["serve", "--mcp"], "cwd": str(repo_path)}}}
    if tool == "codegraph":
        return {"mcpServers": {"codegraph": {
            "command": CODEGRAPH_BIN,
            "args": ["serve", "--mcp", "--path", str(repo_path)]}}}
    raise ValueError(tool)


def _parse_stream_json(stdout: str) -> dict:
    tool_calls: dict[str, int] = {}
    usage = {"input": 0, "output": 0, "cost_usd": 0.0, "duration_ms": 0, "turns": 0}
    exposed = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            exposed = len([x for x in ev.get("tools", []) if "mcp" in str(x).lower()])
        elif t == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls[block.get("name", "?")] = tool_calls.get(block.get("name", "?"), 0) + 1
        elif t == "result":
            u = ev.get("usage", {})
            usage["input"] = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                              + u.get("cache_creation_input_tokens", 0))
            usage["output"] = u.get("output_tokens", 0)
            usage["cost_usd"] = ev.get("total_cost_usd", 0.0)
            usage["duration_ms"] = ev.get("duration_ms", 0)
            usage["turns"] = ev.get("num_turns", 0)
    return {"mcp_tools_exposed": exposed, "tool_calls": tool_calls,
            "total_tool_calls": sum(tool_calls.values()), **usage}


def _run_arm(tool: str, repo_path: Path, question: str, budget: float, model: str) -> dict:
    cfg = _mcp_config(tool, repo_path)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
        cfg_path = f.name
    cmd = [
        "claude", "-p", question, "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions", "--model", model,
        "--max-budget-usd", str(budget), "--strict-mcp-config", "--mcp-config", cfg_path,
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True)
    wall = time.perf_counter() - t0
    parsed = _parse_stream_json(proc.stdout)
    parsed["wall_s"] = wall
    parsed["arm"] = tool
    return parsed


def run_arm_d(repos: list[str] | None = None, tools: list[str] | None = None,
              confirm: bool = False, budget: float = 0.0, model: str = "sonnet",
              runs: int = 1) -> dict:
    if not confirm or budget <= 0:
        console.print("[yellow]Arm D is guarded (spends Claude API credits).[/]\n"
                      "Run with: [bold]cgbench run d --confirm --budget <usd>[/] "
                      "(e.g. --budget 2). See README §Arm D.")
        return {"arm": "d_agent", "skipped": True}

    corpus = load_corpus()
    specs = [corpus.get(r) for r in (repos or [])] if repos else corpus.with_graph()
    arms = ["none"] + (tools or ["crg", "codegraph"])

    rows: list[dict] = []
    for spec in specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.graph_sha)
        question = QUESTIONS.get(spec.name) or f"How does {spec.name} work end to end?"
        per_arm = {}
        for tool in arms:
            console.print(f"[cyan]Arm D[/] {tool} on {spec.name} (×{runs})…")
            samples = [_run_arm(tool, repo_path, question, budget, model) for _ in range(runs)]
            per_arm[tool] = _median(samples)
        rows.append({"repo": spec.name, "question": question, "arms": per_arm,
                     "deltas": _deltas(per_arm)})

    out = {"arm": "d_agent", "date": str(date.today()), "model": model, "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"arm_d-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _median(samples: list[dict]) -> dict:
    import statistics
    keys = ["input", "output", "cost_usd", "duration_ms", "total_tool_calls", "wall_s"]
    return {k: statistics.median([s[k] for s in samples]) for k in keys}


def _deltas(per_arm: dict) -> dict:
    base = per_arm.get("none")
    if not base:
        return {}
    out = {}
    for tool, m in per_arm.items():
        if tool == "none":
            continue
        out[tool] = {
            k: (1 - m[k] / base[k]) if base[k] else None
            for k in ("input", "cost_usd", "duration_ms", "total_tool_calls")
        }
    return out


def _print(rows: list[dict]) -> None:
    t = Table(title="Arm D — agent efficiency (reduction vs no-tool baseline)")
    for c in ("repo", "tool", "tokens↓", "cost↓", "time↓", "tool-calls↓"):
        t.add_column(c)
    for r in rows:
        for tool, d in r.get("deltas", {}).items():
            t.add_row(r["repo"], tool,
                      *[f'{d[k]*100:.0f}%' if d.get(k) is not None else "-"
                        for k in ("input", "cost_usd", "duration_ms", "total_tool_calls")])
    console.print(t)
