"""Arm D — end-to-end agent efficiency (OPTIONAL, costs real Claude API spend).

For each repo, runs Claude Code headless (`claude -p`) on a fixed question with
each tool's MCP server attached, plus a no-tool baseline, and parses stream-json
for tokens / cost / duration / tool-calls. Generalizes codegraph's audit harness
(parse-run.mjs) and ports the methodology of @ttsc/graph's agent A/B benchmark
(experimental/benchmark/graph/agent-ab.mjs):

- **two prompt lanes** — `dedicated` (repo-specific question) and `common`
  (one shared repository-onboarding prompt across all repos, testing whether a
  tool keeps orientation cost flat as the codebase grows);
- **trace gate** — a baseline sample that answers without touching any tool
  (i.e. without reading source) is invalid, as is any sample that used a web
  tool; invalid samples are excluded from medians and flagged in the output;
- **per-turn token summing** — tokens are also summed across assistant turns
  (`tokens_turnsum`), not just taken from the final result event.

This arm is GUARDED: it does nothing unless ``confirm=True`` and a positive
``budget_usd`` are passed (CLI: ``cibench run d --confirm --budget 2``), because
each run spends money. semble's MCP requires the Docker image with an MCP
entrypoint and is left as a documented extension; crg, codegraph, csp and
ttsc (TS/JS repos only) serve MCP natively.
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

from bench.config import CODEGRAPH_BIN, CRG_VENV_PYTHON, CSP_BIN
from bench.fetch import fetch_repo
from bench.goldset import load_corpus
from bench.paths import RESULTS_DIR, checkout_path

console = Console()

# Dedicated lane: one representative question per repo (architecture/flow style).
QUESTIONS = {
    "flask": "How does Flask dispatch an incoming HTTP request to a view function?",
    "fastapi": "How does FastAPI resolve and inject dependencies for a request?",
    "httpx": "How does httpx send a request through its transport layer?",
    "express": "How does Express route a request through its middleware chain?",
    "gin": "How does gin route a request through its middleware chain?",
}

# Common lane (ported from @ttsc/graph's benchmark): ONE shared onboarding
# prompt across all repos — tests whether a tool keeps the agent's orientation
# cost flat as the repository grows.
COMMON_QUESTION = (
    "Give me a repository onboarding: the main entry points, the core "
    "request/data flow between the central components, and where the most "
    "important logic lives. Cite files and symbols."
)


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
    if tool == "csp":
        return {"mcpServers": {"csp": {
            "command": CSP_BIN, "args": ["mcp"], "cwd": str(repo_path)}}}
    if tool == "ttsc":
        return {"mcpServers": {"ttsc-graph": {
            "command": "ttsc-graph", "args": [f"--cwd={repo_path}"]}}}
    raise ValueError(tool)


def _parse_stream_json(stdout: str, baseline: bool) -> dict:
    tool_calls: dict[str, int] = {}
    usage = {"input": 0, "output": 0, "cost_usd": 0.0, "duration_ms": 0, "turns": 0}
    turnsum = 0
    web_used = source_touched = False
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
            msg = ev.get("message", {})
            # per-turn token summing (ttsc agent-ab methodology): capture the
            # full context cost across turns, not just the final result event.
            turnsum += (msg.get("usage") or {}).get("output_tokens", 0)
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    tool_calls[name] = tool_calls.get(name, 0) + 1
                    low = name.lower()
                    if "websearch" in low or "webfetch" in low:
                        web_used = True
                    if low in ("read", "grep", "glob", "bash") or "mcp" in low:
                        source_touched = True
        elif t == "result":
            u = ev.get("usage", {})
            usage["input"] = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                              + u.get("cache_creation_input_tokens", 0))
            usage["output"] = u.get("output_tokens", 0)
            usage["cost_usd"] = ev.get("total_cost_usd", 0.0)
            usage["duration_ms"] = ev.get("duration_ms", 0)
            usage["turns"] = ev.get("num_turns", 0)
    # trace gate (ttsc agent-ab methodology): a baseline answer produced
    # without reading any source is invalid; any web use is invalid.
    valid = not web_used and (source_touched or not baseline)
    return {"mcp_tools_exposed": exposed, "tool_calls": tool_calls,
            "total_tool_calls": sum(tool_calls.values()),
            "tokens_turnsum": turnsum, "web_used": web_used,
            "source_touched": source_touched, "valid": valid, **usage}


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
    parsed = _parse_stream_json(proc.stdout, baseline=(tool == "none"))
    parsed["wall_s"] = wall
    parsed["arm"] = tool
    return parsed


def run_arm_d(repos: list[str] | None = None, tools: list[str] | None = None,
              confirm: bool = False, budget: float = 0.0, model: str = "sonnet",
              runs: int = 1, lanes: tuple[str, ...] = ("dedicated", "common")) -> dict:
    if not confirm or budget <= 0:
        console.print("[yellow]Arm D is guarded (spends Claude API credits).[/]\n"
                      "Run with: [bold]cibench run d --confirm --budget <usd>[/] "
                      "(e.g. --budget 2). See README §Arm D.")
        return {"arm": "d_agent", "skipped": True}

    corpus = load_corpus()
    specs = [corpus.get(r) for r in (repos or [])] if repos else corpus.with_graph()
    arms = ["none"] + (tools or ["crg", "codegraph", "csp"])

    rows: list[dict] = []
    for spec in specs:
        fetch_repo(spec)
        repo_path = checkout_path(spec.name, spec.graph_sha)
        for lane in lanes:
            question = (COMMON_QUESTION if lane == "common"
                        else QUESTIONS.get(spec.name)
                        or f"How does {spec.name} work end to end?")
            per_arm = {}
            for tool in arms:
                console.print(f"[cyan]Arm D[/] {lane}/{tool} on {spec.name} (×{runs})…")
                samples = [_run_arm(tool, repo_path, question, budget, model)
                           for _ in range(runs)]
                invalid = [s for s in samples if not s.get("valid", True)]
                if invalid:
                    console.print(f"[yellow]  {len(invalid)}/{len(samples)} samples "
                                  f"failed the trace gate (excluded)[/]")
                per_arm[tool] = _median([s for s in samples if s.get("valid", True)]
                                        or samples)
                per_arm[tool]["n_invalid"] = len(invalid)
            rows.append({"repo": spec.name, "lane": lane, "question": question,
                         "arms": per_arm, "deltas": _deltas(per_arm)})

    out = {"arm": "d_agent", "date": str(date.today()), "model": model, "results": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"arm_d-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    console.print(f"\n[green]wrote[/] {path}")
    _print(rows)
    return out


def _median(samples: list[dict]) -> dict:
    import statistics
    keys = ["input", "output", "tokens_turnsum", "cost_usd", "duration_ms",
            "total_tool_calls", "wall_s"]
    return {k: statistics.median([s.get(k, 0) for s in samples]) for k in keys}


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
    for c in ("repo", "lane", "tool", "tokens↓", "cost↓", "time↓", "tool-calls↓"):
        t.add_column(c)
    for r in rows:
        for tool, d in r.get("deltas", {}).items():
            t.add_row(r["repo"], r.get("lane", "dedicated"), tool,
                      *[f'{d[k]*100:.0f}%' if d.get(k) is not None else "-"
                        for k in ("input", "cost_usd", "duration_ms", "total_tool_calls")])
    console.print(t)
