"""soop (Repository Planning Graph) adapter — linux/amd64 Docker, run under Node.

soop's native tree-sitter backend has no x86_64-macOS build, and its SemanticCache
requires better-sqlite3 (unsupported by Bun), so the worker runs under Node in a
container. Benchmarks the published `@pleaseai/soop` in free/deterministic no-LLM
mode (heuristic features), i.e. soop's no-LLM floor — its full LLM-feature mode is
a paid/non-deterministic extension (roadmap), analogous to crg's embeddings mode.

soop is both a retriever (Arm A: soop_search) and a graph (Arm B: explore for
multi-hop), so it participates in both.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bench.adapters.base import Hit, QueryResult, SearchRun
from bench.config import SOOP_DOCKER_IMAGE
from bench.paths import CHECKOUTS_DIR

_SENTINEL = "__CGBENCH_JSON__"


class SoopAdapter:
    name = "soop"

    def version(self) -> str:
        return _image_label() or "soop (docker)"

    def search_modality(self) -> str:
        return "RPG features (heuristic, no-LLM)"

    def _container_repo(self, repo_path: Path) -> str:
        rel = repo_path.resolve().relative_to(CHECKOUTS_DIR.resolve())
        return f"/checkouts/{rel}"

    def _run(self, job: dict) -> dict:
        cmd = [
            "docker", "run", "--rm", "-i", "--platform", "linux/amd64",
            "-v", f"{CHECKOUTS_DIR.resolve()}:/checkouts:ro",
            SOOP_DOCKER_IMAGE,
        ]
        proc = subprocess.run(cmd, input=json.dumps(job), capture_output=True, text=True)
        if _SENTINEL not in proc.stdout:
            raise RuntimeError(
                f"soop worker produced no payload (rc={proc.returncode}):\n"
                f"{proc.stderr[-1500:] or proc.stdout[-1500:]}"
            )
        return json.loads(proc.stdout.split(_SENTINEL)[-1])

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun:
        data = self._run({
            "op": "search", "repo_path": self._container_repo(repo_path),
            "queries": queries, "k": k, "runs": runs,
        })
        qrs = []
        for r in data["results"]:
            hits = [
                Hit(file_path=h["file_path"], start_line=h["start_line"],
                    end_line=h["end_line"], symbol=h["symbol"], score=h["score"],
                    n_chars=h["n_chars"], name=h.get("name"))
                for h in r["hits"]
            ]
            qrs.append(QueryResult(query=r["query"], hits=hits, latencies_ms=r["latencies_ms"]))
        return SearchRun(tool=self.name, repo=repo, index_ms=data["index_ms"],
                         queries=qrs, stats=data.get("stats", {}))

    def multihop(self, repo: str, repo_path: Path, tasks: list) -> list[dict]:
        data = self._run({
            "op": "multihop", "repo_path": self._container_repo(repo_path),
            "tasks": [
                {"id": t.id, "nl_query": t.nl_query,
                 "anchor_qualified_suffix": t.anchor_qualified_suffix,
                 "traversal_pattern": t.traversal_pattern,
                 "expected_neighbor_names": list(t.expected_neighbor_names), "k": t.k}
                for t in tasks
            ],
        })
        return data["rows"]


def _image_label() -> str | None:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", SOOP_DOCKER_IMAGE, "--format", "{{.Id}}"],
            capture_output=True, text=True,
        )
        if out.returncode == 0:
            return f"soop (docker {out.stdout.strip()[:19]})"
    except FileNotFoundError:
        pass
    return None
