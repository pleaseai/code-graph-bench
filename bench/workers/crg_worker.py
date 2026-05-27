#!/usr/bin/env python
"""Standalone code-review-graph worker (runs inside .venv-crg).

Faithful to code-review-graph's own eval sequence (eval/runner.py):
``GraphStore`` -> ``full_build`` -> ``run_post_processing`` -> ``hybrid_search``.
No embeddings are computed (crg's published eval is lexical FTS/keyword), which
also keeps it offline and avoids torch — matching how the tool is benchmarked
upstream.

Stdin: a JSON job. Stdout: a JSON result. No dependency on the `bench` package.

Job (op="search"):
    {"op":"search","repo_path":str,"db_path":str,"queries":[str],"k":int,"runs":int}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _build(repo_path: Path, db_path: Path):
    from code_review_graph.graph import GraphStore
    from code_review_graph.incremental import full_build
    from code_review_graph.postprocessing import run_post_processing

    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = GraphStore(str(db_path))
    t0 = time.perf_counter()
    full_build(repo_path, store)
    build_ms = (time.perf_counter() - t0) * 1000.0
    t1 = time.perf_counter()
    run_post_processing(store)
    post_ms = (time.perf_counter() - t1) * 1000.0
    return store, build_ms, post_ms


def _rel(path: str | None, repo_path: Path) -> str | None:
    if not path:
        return path
    try:
        return str(Path(path).resolve().relative_to(repo_path.resolve()))
    except ValueError:
        return path


def _hit(d: dict, repo_path: Path) -> dict:
    sig = " ".join(str(d.get(k) or "") for k in ("name", "signature", "params", "return_type"))
    return {
        "file_path": _rel(d.get("file_path"), repo_path),
        "start_line": d.get("line_start"),
        "end_line": d.get("line_end"),
        "symbol": d.get("qualified_name"),
        "name": d.get("name"),
        "kind": d.get("kind"),
        "score": float(d.get("score", 0.0)),
        # crg returns a node reference, not code body: payload to locate the symbol.
        "n_chars": len(f"{_rel(d.get('file_path'), repo_path)} {d.get('qualified_name','')} {sig}"),
    }


def _op_multihop(store, repo: Path, tasks: list[dict]) -> list[dict]:
    """Faithful port of crg's eval multi_hop_retrieval: search -> anchor -> traverse."""
    from code_review_graph.search import hybrid_search
    from code_review_graph.tools.query import query_graph

    out = []
    for task in tasks:
        nl = task["nl_query"]
        suffix = task["anchor_qualified_suffix"].lower()
        bare = suffix.split("::")[-1].split(".")[-1]
        pattern = task.get("traversal_pattern", "callers_of")
        expected = [e.lower() for e in task.get("expected_neighbor_names", [])]
        k = int(task.get("k", 10))
        try:
            hits = hybrid_search(store, nl, limit=k)
        except Exception:  # noqa: BLE001
            hits = []
        anchor, rank = None, -1
        for i, h in enumerate(hits):
            qn = (h.get("qualified_name") or "").lower()
            nm = (h.get("name") or "").lower()
            if qn.endswith(suffix) or nm == bare:
                anchor, rank = h, i
                break
        if anchor is None:
            out.append({"task_id": task["id"], "anchor_found": False, "anchor_rank": -1,
                        "neighbor_count": 0, "expected_count": len(expected),
                        "matched_count": 0, "neighbor_recall": 0.0, "score": 0.0})
            continue
        try:
            trav = query_graph(pattern=pattern, target=anchor["qualified_name"],
                               repo_root=str(repo), detail_level="standard")
        except Exception:  # noqa: BLE001
            trav = {}
        rows = trav.get("data") or trav.get("results") or []
        names = {(r.get("name") or "").lower() for r in rows if isinstance(r, dict)}
        matched = sum(1 for e in expected if e in names)
        recall = matched / len(expected) if expected else 0.0
        out.append({"task_id": task["id"], "anchor_found": True, "anchor_rank": rank,
                    "neighbor_count": len(rows), "expected_count": len(expected),
                    "matched_count": matched, "neighbor_recall": round(recall, 3),
                    "score": round(recall, 3)})
    return out


def _op_impact(store, repo: Path, test_commits: list[dict]) -> list[dict]:
    """Faithful port of crg's eval impact_accuracy.

    predicted = changed files + analyze_changes-affected files;
    actual = changed files + reverse CALLS/IMPORTS_FROM neighbors (crg graph).
    """
    import subprocess

    from code_review_graph.changes import analyze_changes

    def changed_files(sha: str) -> list[str]:
        r = subprocess.run(["git", "diff", "--name-only", f"{sha}~1", sha],
                           cwd=str(repo), capture_output=True, text=True)
        return [x for x in r.stdout.splitlines() if x.strip()]

    out = []
    for tc in test_commits:
        sha = tc["sha"]
        changed = changed_files(sha)
        try:
            analysis = analyze_changes(store, changed, repo_root=str(repo), base=f"{sha}~1")
        except Exception:  # noqa: BLE001
            analysis = {}
        predicted = set(changed)
        for f in analysis.get("changed_functions", []):
            if isinstance(f, dict) and f.get("file_path"):
                predicted.add(_rel(f["file_path"], repo))
        for flow in analysis.get("affected_flows", []):
            for node in flow.get("nodes", []):
                if isinstance(node, dict) and node.get("file_path"):
                    predicted.add(_rel(node["file_path"], repo))
        actual = set(changed)
        for f in changed:
            try:
                nodes = store.get_nodes_by_file(str((repo / f).resolve()))
            except Exception:  # noqa: BLE001
                nodes = []
            for node in nodes:
                try:
                    edges = store.get_edges_by_target(node.qualified_name)
                except Exception:  # noqa: BLE001
                    edges = []
                for edge in edges:
                    if getattr(edge, "kind", None) in ("CALLS", "IMPORTS_FROM"):
                        src = getattr(edge, "source_qualified", "") or ""
                        sf = src.split("::")[0]
                        if sf:
                            actual.add(_rel(sf, repo))
        out.append({"sha": sha, "predicted": sorted(predicted), "actual": sorted(actual)})
    return out


_NEAR_MARGIN = 80  # lines: a chunk-based hit may sit just beside the symbol


def _gap(ls, le, lo, hi) -> int:
    if lo is None or hi is None:
        return 0
    if le < lo:
        return lo - le
    if ls > hi:
        return ls - hi
    return 0  # overlap


def _symbols_near(store, repo: Path, file: str, lo, hi) -> list[dict]:
    """Symbols in `file` overlapping or within _NEAR_MARGIN of [lo, hi].

    semble returns chunk spans that may sit just beside the target symbol
    (e.g. it surfaced the caller region), so rank by distance, then specificity.
    """
    abs_path = str((repo / file).resolve())
    try:
        nodes = store.get_nodes_by_file(abs_path)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for n in nodes:
        if getattr(n, "kind", None) == "File":
            continue
        ls, le = getattr(n, "line_start", None), getattr(n, "line_end", None)
        if ls is None or le is None:
            continue
        gap = _gap(ls, le, lo, hi)
        if gap > _NEAR_MARGIN:
            continue
        out.append({"name": n.name, "qualified_name": n.qualified_name,
                    "gap": gap, "span": le - ls})
    out.sort(key=lambda d: (d["gap"], d["span"]))
    return out


def _op_combined(store, repo: Path, tasks: list[dict]) -> list[dict]:
    """semble -> anchor: resolve anchor symbol from semble hits, then traverse."""
    from code_review_graph.tools.query import query_graph

    out = []
    for task in tasks:
        suffix = task["anchor_qualified_suffix"].lower()
        bare = suffix.split("::")[-1].split(".")[-1]
        expected = [e.lower() for e in task.get("expected_neighbor_names", [])]
        pattern = task.get("traversal_pattern", "callers_of")
        k = int(task.get("k", 10))

        candidates: list[dict] = []
        seen = set()
        for hit in task.get("semble_hits", []):
            for s in _symbols_near(store, repo, hit["file"],
                                   hit.get("start_line"), hit.get("end_line")):
                key = s["qualified_name"]
                if key not in seen:
                    seen.add(key)
                    candidates.append(s)
            if len(candidates) >= k:
                break

        anchor, rank = None, -1
        for i, c in enumerate(candidates[:k]):
            if c["name"].lower() == bare or c["qualified_name"].lower().endswith(suffix):
                anchor, rank = c, i
                break
        if anchor is None and candidates:
            anchor = candidates[0]  # still traverse from best guess

        if anchor is None:
            out.append({"task_id": task["id"], "anchor_found": False, "anchor_rank": -1,
                        "neighbor_count": 0, "expected_count": len(expected),
                        "matched_count": 0, "neighbor_recall": 0.0, "score": 0.0})
            continue
        try:
            trav = query_graph(pattern=pattern, target=anchor["qualified_name"],
                               repo_root=str(repo), detail_level="standard")
        except Exception:  # noqa: BLE001
            trav = {}
        rows = trav.get("data") or trav.get("results") or []
        names = {(r.get("name") or "").lower() for r in rows if isinstance(r, dict)}
        matched = sum(1 for e in expected if e in names)
        recall = matched / len(expected) if expected else 0.0
        found = rank >= 0
        out.append({"task_id": task["id"], "anchor_found": found,
                    "anchor_rank": rank, "neighbor_count": len(rows),
                    "expected_count": len(expected), "matched_count": matched,
                    "neighbor_recall": round(recall, 3),
                    "score": round(recall, 3) if found else 0.0})
    return out


def main() -> None:
    job = json.load(sys.stdin)

    repo = Path(job["repo_path"])
    db_path = Path(job["db_path"])
    op = job.get("op", "search")
    k = int(job.get("k", 10))
    runs = int(job.get("runs", 5))

    store, build_ms, post_ms = _build(repo, db_path)

    if op == "multihop":
        json.dump({"build_ms": build_ms, "post_ms": post_ms,
                   "rows": _op_multihop(store, repo, job["tasks"])}, sys.stdout)
        return
    if op == "impact":
        json.dump({"build_ms": build_ms, "post_ms": post_ms,
                   "rows": _op_impact(store, repo, job["test_commits"])}, sys.stdout)
        return
    if op == "combined":
        json.dump({"build_ms": build_ms, "post_ms": post_ms,
                   "rows": _op_combined(store, repo, job["tasks"])}, sys.stdout)
        return

    from code_review_graph.search import hybrid_search
    stats = store.get_stats()
    out_stats = {
        "total_nodes": getattr(stats, "total_nodes", None),
        "total_edges": getattr(stats, "total_edges", None),
        "files_count": getattr(stats, "files_count", None),
    }

    results = []
    for q in job["queries"]:
        latencies = []
        hits_payload = None
        for i in range(max(1, runs)):
            s = time.perf_counter()
            rows = hybrid_search(store, q, limit=k)
            latencies.append((time.perf_counter() - s) * 1000.0)
            if i == 0:
                hits_payload = [_hit(r, repo) for r in rows]
        results.append({"query": q, "latencies_ms": latencies, "hits": hits_payload})

    json.dump(
        {
            "index_ms": build_ms + post_ms,
            "build_ms": build_ms,
            "post_ms": post_ms,
            "stats": out_stats,
            "db_bytes": db_path.stat().st_size if db_path.exists() else None,
            "results": results,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
