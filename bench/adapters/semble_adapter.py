"""semble adapter — runs the worker in a linux/amd64 Docker container.

semble requires tree-sitter-language-pack <1.8.0, which has no x86_64-macOS
wheel or sdist, so it cannot run natively on Intel Macs. The container provides
a linux/amd64 environment with the correct wheels and the embedding model baked
in (offline). semble indexes the whole repo root (same input as the other tools)
so its hit paths are repo-root-relative and directly comparable to the gold set.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bench.adapters.base import Hit, QueryResult, SearchRun
from bench.config import SEMBLE_DOCKER_IMAGE
from bench.paths import CHECKOUTS_DIR


class SembleAdapter:
    name = "semble"

    def version(self) -> str:
        return _image_label() or "semble (docker)"

    def search_modality(self) -> str:
        return "semantic+lexical (static embeddings + BM25 + RRF)"

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun:
        # Map the host checkout path to its location inside the mounted volume.
        rel = repo_path.resolve().relative_to(CHECKOUTS_DIR.resolve())
        container_repo = f"/checkouts/{rel}"
        job = {
            "op": "search",
            "repo_path": container_repo,
            "root": None,  # whole repo, for parity with crg/codegraph
            "queries": queries,
            "k": k,
            "runs": runs,
        }
        cmd = [
            "docker", "run", "--rm", "-i", "--platform", "linux/amd64",
            "-v", f"{CHECKOUTS_DIR.resolve()}:/checkouts:ro",
            SEMBLE_DOCKER_IMAGE,
        ]
        proc = subprocess.run(cmd, input=json.dumps(job), capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"semble worker failed:\n{proc.stderr[-2000:]}")
        data = json.loads(proc.stdout)

        qrs = []
        for r in data["results"]:
            hits = [
                Hit(
                    file_path=h["file_path"], start_line=h["start_line"],
                    end_line=h["end_line"], symbol=h["symbol"],
                    score=h["score"], n_chars=h["n_chars"],
                )
                for h in r["hits"]
            ]
            qrs.append(QueryResult(query=r["query"], hits=hits, latencies_ms=r["latencies_ms"]))

        return SearchRun(
            tool=self.name, repo=repo, index_ms=data["index_ms"],
            queries=qrs, stats=data.get("stats", {}),
        )


def _image_label() -> str | None:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", SEMBLE_DOCKER_IMAGE, "--format", "{{.Id}}"],
            capture_output=True, text=True,
        )
        if out.returncode == 0:
            return f"semble (docker {out.stdout.strip()[:19]})"
    except FileNotFoundError:
        pass
    return None
