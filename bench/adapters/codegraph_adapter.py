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


    # ----- graph traversal (Arm B/C) -----
    def ensure_indexed(self, repo_path: Path) -> None:
        if not (repo_path / ".codegraph").exists():
            r = self._run(["init", "-i"], repo_path)
            if r.returncode != 0:
                raise RuntimeError(f"codegraph init failed:\n{r.stderr[-1500:]}")

    def search_symbols(self, repo_path: Path, query: str, k: int) -> list[Hit]:
        res = self._run(["query", query, "--json", "-l", str(k)], repo_path)
        return _parse_hits(res.stdout)

    def neighbors(self, repo_path: Path, symbol: str, pattern: str) -> list[str]:
        sub = {"callers_of": "callers", "callees_of": "callees"}.get(pattern)
        if sub is None:
            return []
        res = self._run([sub, symbol, "--json"], repo_path)
        try:
            d = json.loads(res.stdout)
        except json.JSONDecodeError:
            return []
        rows = d.get(sub, d.get("results", []))
        return [(r.get("name") or "").lower() for r in rows if isinstance(r, dict)]

    NEAR_MARGIN = 80  # lines: chunk-based semble hits may sit beside the symbol

    def symbols_in_file(self, repo_path: Path, file: str, lo, hi) -> list[dict]:
        """Symbols in `file` overlapping or within NEAR_MARGIN of [lo, hi].

        Ranked by distance then specificity (reads codegraph's own .codegraph db).
        """
        import sqlite3

        db = repo_path / ".codegraph" / "codegraph.db"
        if not db.exists():
            return []
        con = sqlite3.connect(str(db))
        try:
            rows = con.execute(
                "SELECT name, qualified_name, start_line, end_line FROM nodes "
                "WHERE file_path = ? AND kind != 'file'", (file,),
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()
        out = []
        for name, qn, ls, le in rows:
            if ls is None or le is None:
                continue
            if lo is None or hi is None:
                gap = 0
            elif le < lo:
                gap = lo - le
            elif ls > hi:
                gap = ls - hi
            else:
                gap = 0
            if gap > self.NEAR_MARGIN:
                continue
            out.append({"name": name, "qualified_name": qn, "gap": gap, "span": le - ls})
        out.sort(key=lambda d: (d["gap"], d["span"]))
        return out

    def combined(self, repo: str, repo_path: Path, tasks: list, semble_hits: dict) -> list[dict]:
        """Arm C: resolve anchor from semble hits (via codegraph's own index), then traverse."""
        self.ensure_indexed(repo_path)
        out = []
        for t in tasks:
            suffix = t.anchor_qualified_suffix.lower()
            bare = suffix.split("::")[-1].split(".")[-1]
            expected = [e.lower() for e in t.expected_neighbor_names]
            candidates, seen = [], set()
            for hit in semble_hits.get(t.id, []):
                for s in self.symbols_in_file(repo_path, hit["file"],
                                              hit.get("start_line"), hit.get("end_line")):
                    if s["qualified_name"] not in seen:
                        seen.add(s["qualified_name"])
                        candidates.append(s)
                if len(candidates) >= t.k:
                    break
            anchor, rank = None, -1
            for i, c in enumerate(candidates[: t.k]):
                if c["name"].lower() == bare or c["qualified_name"].lower().endswith(suffix):
                    anchor, rank = c, i
                    break
            if anchor is None and candidates:
                anchor = candidates[0]
            if anchor is None:
                out.append({"task_id": t.id, "anchor_found": False, "anchor_rank": -1,
                            "neighbor_count": 0, "expected_count": len(expected),
                            "matched_count": 0, "neighbor_recall": 0.0, "score": 0.0})
                continue
            names = set(self.neighbors(repo_path, anchor["name"], t.traversal_pattern))
            matched = sum(1 for e in expected if e in names)
            recall = matched / len(expected) if expected else 0.0
            found = rank >= 0
            out.append({"task_id": t.id, "anchor_found": found, "anchor_rank": rank,
                        "neighbor_count": len(names), "expected_count": len(expected),
                        "matched_count": matched, "neighbor_recall": round(recall, 3),
                        "score": round(recall, 3) if found else 0.0})
        return out

    def multihop(self, repo: str, repo_path: Path, tasks: list) -> list[dict]:
        """search -> anchor (by bare symbol name) -> traverse -> neighbor recall."""
        self.ensure_indexed(repo_path)
        out = []
        for task in tasks:
            suffix = task.anchor_qualified_suffix.lower()
            bare = suffix.split("::")[-1].split(".")[-1]
            expected = [e.lower() for e in task.expected_neighbor_names]
            hits = self.search_symbols(repo_path, task.nl_query, task.k)
            anchor, rank = None, -1
            for i, h in enumerate(hits):
                if (h.name or "").lower() == bare or (h.symbol or "").lower().endswith(suffix):
                    anchor, rank = h, i
                    break
            if anchor is None:
                out.append({"task_id": task.id, "anchor_found": False, "anchor_rank": -1,
                            "neighbor_count": 0, "expected_count": len(expected),
                            "matched_count": 0, "neighbor_recall": 0.0, "score": 0.0})
                continue
            names = set(self.neighbors(repo_path, anchor.name or bare, task.traversal_pattern))
            matched = sum(1 for e in expected if e in names)
            recall = matched / len(expected) if expected else 0.0
            out.append({"task_id": task.id, "anchor_found": True, "anchor_rank": rank,
                        "neighbor_count": len(names), "expected_count": len(expected),
                        "matched_count": matched, "neighbor_recall": round(recall, 3),
                        "score": round(recall, 3)})
        return out


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
