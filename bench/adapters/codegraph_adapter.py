"""codegraph adapter — native CLI (bundled Node runtime).

codegraph is FTS5-only (lexical) by design. Indexing creates `.codegraph/` in
the repo; we wipe and rebuild for determinism. Query latency is measured as CLI
wall time and therefore INCLUDES Node process startup — unlike semble/crg whose
latency is in-process. This is flagged in the report; quality metrics are
unaffected.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from bench.adapters.base import Hit, QueryResult, SearchRun
from bench.config import CODEGRAPH_BIN


class CodegraphAdapter:
    name = "codegraph"

    def version(self) -> str:
        try:
            out = subprocess.run([CODEGRAPH_BIN, "--version"], capture_output=True, text=True)
            return f"codegraph {out.stdout.strip()}" if out.returncode == 0 else "codegraph"
        except FileNotFoundError:
            return "codegraph (not found)"

    def search_modality(self) -> str:
        return "lexical (FTS5)"

    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run([CODEGRAPH_BIN, *args], cwd=str(cwd),
                              capture_output=True, text=True)

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun:
        cg_dir = repo_path / ".codegraph"
        if cg_dir.exists():
            shutil.rmtree(cg_dir)

        t0 = time.perf_counter()
        init = self._run(["init", "-i"], repo_path)
        index_ms = (time.perf_counter() - t0) * 1000.0
        if init.returncode != 0:
            raise RuntimeError(f"codegraph init failed:\n{init.stderr[-2000:]}")

        qrs = []
        for q in queries:
            latencies = []
            hits_payload = None
            for i in range(max(1, runs)):
                s = time.perf_counter()
                res = self._run(["query", q, "--json", "-l", str(k)], repo_path)
                latencies.append((time.perf_counter() - s) * 1000.0)
                if i == 0:
                    hits_payload = _parse_hits(res.stdout)
            qrs.append(QueryResult(query=q, hits=hits_payload or [], latencies_ms=latencies))

        stats = _stats(self._run(["status", "--json"], repo_path).stdout)
        db = cg_dir / "codegraph.db"
        return SearchRun(
            tool=self.name, repo=repo, index_ms=index_ms, queries=qrs,
            stats=stats, db_bytes=db.stat().st_size if db.exists() else None,
        )


def _parse_hits(stdout: str) -> list[Hit]:
    try:
        rows = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    hits = []
    for r in rows:
        n = r.get("node", r)
        sig = " ".join(str(n.get(k) or "") for k in ("name", "signature"))
        fp = n.get("filePath") or n.get("file_path")
        qn = n.get("qualifiedName") or n.get("qualified_name")
        hits.append(
            Hit(
                file_path=fp, start_line=n.get("startLine"), end_line=n.get("endLine"),
                symbol=qn, score=float(r.get("score", 0.0)),
                n_chars=len(f"{fp} {qn} {sig}"),
                name=n.get("name"), kind=n.get("kind"),
            )
        )
    return hits


def _stats(stdout: str) -> dict:
    try:
        d = json.loads(stdout)
        return {
            "files_count": d.get("fileCount") or d.get("files"),
            "total_nodes": d.get("nodeCount") or d.get("nodes"),
            "total_edges": d.get("edgeCount") or d.get("edges"),
        }
    except json.JSONDecodeError:
        return {}
