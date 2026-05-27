"""Unit tests for metrics and hit/target matching against known values."""

from __future__ import annotations

import math

from bench.adapters.base import Hit
from bench.goldset.schema import Target
from bench.matching import hit_matches_target, target_rank
from bench.metrics import mrr, ndcg_at_k, precision_recall_f1, recall_at_k


def test_ndcg_perfect_single():
    # relevant item at rank 1, one relevant total -> NDCG = 1.0
    assert ndcg_at_k([1], 1, 10) == 1.0


def test_ndcg_rank_two():
    # single relevant at rank 2: DCG = 1/log2(3); IDCG = 1/log2(2)=1
    assert math.isclose(ndcg_at_k([2], 1, 10), 1 / math.log2(3), rel_tol=1e-9)


def test_ndcg_miss():
    assert ndcg_at_k([], 1, 10) == 0.0
    assert ndcg_at_k([11], 1, 10) == 0.0  # beyond k


def test_recall_at_k():
    assert recall_at_k([1, 3], 4, 10) == 0.5
    assert recall_at_k([1, 11], 2, 10) == 0.5  # rank 11 excluded at k=10
    assert recall_at_k([], 0, 10) == 0.0


def test_mrr():
    assert mrr([3, 5]) == 1 / 3
    assert mrr([]) == 0.0


def test_precision_recall_f1():
    m = precision_recall_f1({"a", "b", "c"}, {"a", "b"})
    assert m["tp"] == 2
    assert math.isclose(m["precision"], 2 / 3)
    assert m["recall"] == 1.0
    assert math.isclose(m["f1"], 2 * (2 / 3) * 1 / ((2 / 3) + 1))


def _hit(path, sl=None, el=None, symbol=None, name=None):
    return Hit(file_path=path, start_line=sl, end_line=el, symbol=symbol,
               score=1.0, n_chars=10, name=name)


def test_path_match_exact_and_suffix():
    t = Target(path="src/flask/app.py")
    assert hit_matches_target(_hit("src/flask/app.py"), t)
    assert hit_matches_target(_hit("app.py"), t)          # sub-root relative
    assert not hit_matches_target(_hit("src/flask/cli.py"), t)


def test_span_overlap():
    t = Target(path="a.py", start_line=10, end_line=20)
    assert hit_matches_target(_hit("a.py", 15, 25), t)     # overlap
    assert not hit_matches_target(_hit("a.py", 1, 5), t)   # before
    assert hit_matches_target(_hit("a.py"), t)             # no span -> path enough


def test_symbol_match():
    t = Target(path="x.py", symbol="dispatch_request")
    h = _hit("other.py", symbol="src/flask/app.py::Flask.dispatch_request",
             name="dispatch_request")
    assert hit_matches_target(h, t)


def test_target_rank():
    hits = [_hit("a.py"), _hit("b.py"), _hit("c.py")]
    assert target_rank(hits, Target(path="c.py")) == 3
    assert target_rank(hits, Target(path="z.py")) is None
