"""@ttsc/graph adapter — TypeScript-compiler-resolved code graph (MCP).

ttsc-graph builds a compiler-exact graph from a real tsc Program and serves
one MCP tool (`inspect_typescript_graph`) with typed requests (lookup, trace,
…). The adapter drives the resident MCP stdio server with the tool's real
query logic: `lookup` for the anchor step, `trace` (reverse=callers /
forward=callees) for traversal. Arm C/H anchor resolution reads the tool's
own `ttscgraph dump` (full graph JSON) to map file+line spans to node ids.

**Scope caveat:** ttsc-graph is TypeScript-only by design ("a compiler-exact
graph is bound to one compiler"). This corpus has no TS repo; the only
JS-family graph repo (express) is plain CommonJS, which the adapter indexes
via an injected `allowJs` tsconfig — an UNSUPPORTED path upstream. Expect a
near-empty edge set there (compiler can't resolve prototype-mutation calls);
the numbers are a compatibility floor, not representative of ttsc-graph on
real TS projects. A TS corpus repo with gold labels is the fair-arena
roadmap item.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from bench.goldset import load_corpus
from bench.workers.mcp_client import McpClient, McpError

SUPPORTED_LANGUAGES = {"typescript", "javascript"}
NEAR_MARGIN = 80

TSCONFIG_ALLOWJS = {
    "compilerOptions": {
        "allowJs": True, "checkJs": False, "noEmit": True,
        "module": "commonjs", "target": "es2020", "moduleResolution": "node",
    },
    "include": ["**/*.js", "**/*.ts"],
    "exclude": ["node_modules", "test", "tests", "examples", "benchmarks"],
}


def _graph_binary() -> str | None:
    """The native ttscgraph binary (ttsc's platform package)."""
    if os.environ.get("TTSC_GRAPH_BINARY"):
        return os.environ["TTSC_GRAPH_BINARY"]
    found = shutil.which("ttscgraph")
    if found:
        return found
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True,
                              text=True).stdout.strip()
    except FileNotFoundError:
        return None
    plat = "win32" if sys.platform == "win32" else sys.platform  # darwin | linux
    arch = {"x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine(), "x64")
    p = Path(root) / "ttsc" / "node_modules" / "@ttsc" / f"{plat}-{arch}" / "bin" / "ttscgraph"
    return str(p) if p.exists() else None


class TtscAdapter:
    name = "ttsc"

    def version(self) -> str:
        binpath = _graph_binary()
        if not binpath:
            return "ttsc-graph (not found)"
        try:
            out = subprocess.run([binpath, "--version"], capture_output=True, text=True)
            v = out.stdout.strip() or out.stderr.strip()
            return f"ttsc-graph {v}" if v else "ttsc-graph"
        except OSError:
            return "ttsc-graph"

    def search_modality(self) -> str:
        return "compiler graph (tsc-exact, lexical lookup)"

    # ----- setup -----
    def _check_repo(self, repo: str) -> None:
        lang = load_corpus().get(repo).language
        if lang not in SUPPORTED_LANGUAGES:
            raise RuntimeError(
                f"ttsc-graph is TypeScript-only; {repo} is {lang} — skipping")

    def _ensure_tsconfig(self, repo_path: Path) -> bool:
        """Inject an allowJs tsconfig if the repo has none. Returns True if created."""
        cfg = repo_path / "tsconfig.json"
        if cfg.exists():
            return False
        cfg.write_text(json.dumps(TSCONFIG_ALLOWJS, indent=2))
        return True

    def _open(self, repo_path: Path) -> McpClient:
        binpath = _graph_binary()
        if not binpath:
            raise RuntimeError("ttscgraph binary not found; npm i -g ttsc @ttsc/graph")
        env = {**os.environ, "TTSC_GRAPH_BINARY": binpath}
        client = McpClient(["ttsc-graph", f"--cwd={repo_path.resolve()}"], env=env)
        client.initialize()
        return client

    @staticmethod
    def _inspect(client: McpClient, request: dict) -> dict:
        res = client.call_tool("inspect_typescript_graph", {
            "question": "benchmark structural query",
            "draft": {"reason": "benchmark structural query", "type": request["type"]},
            "review": "ok",
            "request": request,
        })
        return res.get("result", res) if isinstance(res, dict) else {}

    @staticmethod
    def _trace_names(client: McpClient, node_id: str, pattern: str) -> set[str]:
        direction = {"callers_of": "reverse", "callees_of": "forward"}.get(pattern)
        if direction is None:
            return set()
        try:
            res = TtscAdapter._inspect(client, {
                "type": "trace", "from": node_id, "direction": direction,
                "maxDepth": 1, "maxNodes": 16,
            })
        except McpError:
            return set()
        names: set[str] = set()
        for n in res.get("reached") or []:
            if n.get("name"):
                names.add(n["name"].lower())
        for hop in res.get("hops") or []:
            for key in ("from", "to"):
                v = hop.get(key)
                if isinstance(v, dict) and v.get("name"):
                    names.add(v["name"].lower())
        return names

    @staticmethod
    def _row(task, found: bool, rank: int, names: set[str], expected: list[str]) -> dict:
        matched = sum(1 for e in expected if e in names)
        recall = matched / len(expected) if expected else 0.0
        return {"task_id": task.id, "anchor_found": found, "anchor_rank": rank,
                "neighbor_count": len(names), "expected_count": len(expected),
                "matched_count": matched, "neighbor_recall": round(recall, 3),
                "score": round(recall, 3) if found else 0.0,
                "neighbor_names": sorted(names)}

    # ----- Arm B: own search -> anchor -> traverse -----
    def multihop(self, repo: str, repo_path: Path, tasks: list) -> list[dict]:
        self._check_repo(repo)
        created = self._ensure_tsconfig(repo_path)
        client = self._open(repo_path)
        try:
            out = []
            for t in tasks:
                suffix = t.anchor_qualified_suffix.lower()
                bare = suffix.split("::")[-1].split(".")[-1]
                expected = [e.lower() for e in t.expected_neighbor_names]
                try:
                    res = self._inspect(client, {"type": "lookup",
                                                 "query": t.nl_query, "limit": t.k})
                except McpError:
                    res = {}
                hits = res.get("hits") or []
                anchor, rank = None, -1
                for i, h in enumerate(hits[: t.k]):
                    qn = f'{h.get("file", "")}::{h.get("name", "")}'.lower()
                    if (h.get("name", "").lower() == bare or qn.endswith(suffix)):
                        anchor, rank = h, i
                        break
                if anchor is None:
                    out.append(self._row(t, False, -1, set(), expected))
                    continue
                names = self._trace_names(client, anchor["id"], t.traversal_pattern)
                out.append(self._row(t, True, rank, names, expected))
            return out
        finally:
            client.close()
            if created:
                (repo_path / "tsconfig.json").unlink(missing_ok=True)

    # ----- Arm C/H: external anchor hits -> resolve via dump -> traverse -----
    def combined(self, repo: str, repo_path: Path, tasks: list,
                 anchor_hits: dict) -> list[dict]:
        self._check_repo(repo)
        created = self._ensure_tsconfig(repo_path)
        binpath = _graph_binary()
        if not binpath:
            raise RuntimeError("ttscgraph binary not found; npm i -g ttsc @ttsc/graph")
        try:
            dump = subprocess.run(
                [binpath, "dump", f"--cwd={repo_path.resolve()}"],
                capture_output=True, text=True)
            if dump.returncode != 0:
                raise RuntimeError(f"ttscgraph dump failed:\n{dump.stderr[-1500:]}")
            nodes = [n for n in json.loads(dump.stdout).get("nodes", [])
                     if not n.get("external")]
            client = self._open(repo_path)
            try:
                out = []
                for t in tasks:
                    suffix = t.anchor_qualified_suffix.lower()
                    bare = suffix.split("::")[-1].split(".")[-1]
                    expected = [e.lower() for e in t.expected_neighbor_names]
                    candidates, seen = [], set()
                    for hit in anchor_hits.get(t.id, []):
                        for n in _near_nodes(nodes, hit["file"],
                                             hit.get("start_line"), hit.get("end_line")):
                            if n["id"] not in seen:
                                seen.add(n["id"])
                                candidates.append(n)
                        if len(candidates) >= t.k:
                            break
                    anchor, rank = None, -1
                    for i, c in enumerate(candidates[: t.k]):
                        qn = f'{c.get("file", "")}::{c.get("name", "")}'.lower()
                        if (c.get("name", "").lower() == bare or qn.endswith(suffix)):
                            anchor, rank = c, i
                            break
                    if anchor is None and candidates:
                        anchor = candidates[0]
                    if anchor is None:
                        out.append(self._row(t, False, -1, set(), expected))
                        continue
                    names = self._trace_names(client, anchor["id"], t.traversal_pattern)
                    out.append(self._row(t, rank >= 0, rank, names, expected))
                return out
            finally:
                client.close()
        finally:
            if created:
                (repo_path / "tsconfig.json").unlink(missing_ok=True)


def _near_nodes(nodes: list[dict], file: str, lo, hi) -> list[dict]:
    """Dump nodes in `file` overlapping/within NEAR_MARGIN of [lo, hi], closest first."""
    out = []
    for n in nodes:
        if n.get("file") != file:
            continue
        span = n.get("sourceSpan") or {}
        s, e = span.get("startLine", n.get("line")), span.get("endLine", n.get("line"))
        if s is None or e is None:
            continue
        if lo is None or hi is None:
            gap = 0
        elif e < lo:
            gap = lo - e
        elif s > hi:
            gap = s - hi
        else:
            gap = 0
        if gap > NEAR_MARGIN:
            continue
        out.append({**n, "gap": gap, "span": e - s})
    out.sort(key=lambda d: (d["gap"], d["span"]))
    return out
