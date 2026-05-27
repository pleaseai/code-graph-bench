"""Match retrieved hits against gold targets.

A hit matches a target when their normalized paths agree (exact, or one a path
suffix of the other to tolerate sub-root differences) and — if the target pins a
line span — the hit's span overlaps it. For symbol-pinned targets, a matching
symbol/name also counts (used by graph tools that return symbols, not spans).
Ported from semble's ``target_matches_location`` / ``path_matches``.
"""

from __future__ import annotations

from bench.adapters.base import Hit
from bench.goldset.schema import Target


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


def path_matches(hit_path: str | None, target_path: str) -> bool:
    if not hit_path:
        return False
    a, b = _norm(hit_path), _norm(target_path)
    if a == b:
        return True
    # tolerate sub-root vs repo-root relative paths
    return a.endswith("/" + b) or b.endswith("/" + a)


def hit_matches_target(hit: Hit, target: Target) -> bool:
    # symbol-level match (graph tools)
    if target.symbol and (hit.symbol or hit.name):
        sym = (hit.symbol or "").lower()
        nm = (hit.name or "").lower()
        t = target.symbol.lower()
        if t == nm or sym.endswith("::" + t) or sym.endswith(t):
            if not target.has_span or _span_ok(hit, target):
                return True
    if not path_matches(hit.file_path, target.path):
        return False
    if not target.has_span:
        return True
    return _span_ok(hit, target)


def _span_ok(hit: Hit, target: Target) -> bool:
    if hit.start_line is None or hit.end_line is None:
        return True  # tool didn't report a span; path match is enough
    return not (hit.end_line < target.start_line or hit.start_line > target.end_line)


def target_rank(hits: list[Hit], target: Target) -> int | None:
    """1-based rank of the first hit matching `target`, or None."""
    for i, h in enumerate(hits, 1):
        if hit_matches_target(h, target):
            return i
    return None
