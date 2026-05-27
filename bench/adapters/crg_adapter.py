"""code-review-graph adapter — runs the worker in its isolated venv (native).

Faithful to crg's own eval: build + post-process + lexical hybrid_search
(no embeddings), which is offline and matches the tool's published numbers.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from pathlib import Path

from bench.adapters.base import Hit, QueryResult, SearchRun
from bench.config import CRG_VENV_PYTHON, CRG_WORKER, SCRATCH_DIR


class CrgAdapter:
    name = "crg"

    def version(self) -> str:
        try:
            out = subprocess.run(
                [str(CRG_VENV_PYTHON), "-c",
                 "import importlib.metadata as m;print(m.version('code-review-graph'))"],
                capture_output=True, text=True,
            )
            if out.returncode == 0:
                return f"code-review-graph {out.stdout.strip()}"
        except FileNotFoundError:
            pass
        return "code-review-graph"

    def search_modality(self) -> str:
        return "lexical (FTS5 + keyword, no embeddings)"

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun:
        db_path = SCRATCH_DIR / "crg" / f"{repo_path.name}.db"
        job = {
            "op": "search",
            "repo_path": str(repo_path.resolve()),
            "db_path": str(db_path),
            "queries": queries,
            "k": k,
            "runs": runs,
        }
        proc = subprocess.run(
            [str(CRG_VENV_PYTHON), str(CRG_WORKER)],
            input=json.dumps(job), capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"crg worker failed:\n{proc.stderr[-2000:]}")
        data = json.loads(proc.stdout)

        qrs = []
        for r in data["results"]:
            hits = [
                Hit(
                    file_path=h["file_path"], start_line=h["start_line"],
                    end_line=h["end_line"], symbol=h["symbol"], score=h["score"],
                    n_chars=h["n_chars"], name=h.get("name"), kind=h.get("kind"),
                )
                for h in r["hits"]
            ]
            qrs.append(QueryResult(query=r["query"], hits=hits, latencies_ms=r["latencies_ms"]))

        return SearchRun(
            tool=self.name, repo=repo, index_ms=data["index_ms"],
            build_ms=data.get("build_ms"), post_ms=data.get("post_ms"),
            queries=qrs, stats=data.get("stats", {}), db_bytes=data.get("db_bytes"),
        )
