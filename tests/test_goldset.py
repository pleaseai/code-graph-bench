"""Gold-set integrity: schema loads, labels are well-formed, corpus is consistent."""

from __future__ import annotations

import pytest

from bench.goldset import load_corpus, load_graph_config, load_retrieval_tasks

CORPUS = load_corpus()


def test_corpus_nonempty():
    assert CORPUS.repos
    assert {"flask", "fastapi", "httpx", "express", "gin"} <= set(CORPUS.names)


@pytest.mark.parametrize("spec", CORPUS.repos, ids=lambda s: s.name)
def test_retrieval_gold_wellformed(spec):
    tasks = load_retrieval_tasks(spec.name)
    assert tasks, f"{spec.name} has no retrieval queries"
    for t in tasks:
        assert t.query.strip(), "empty query"
        assert t.relevant, f"{spec.name}: query has no relevant targets: {t.query!r}"
        assert t.category in {"semantic", "architecture", "symbol", "unknown"}
        for tgt in t.all_relevant:
            assert tgt.path.strip()


@pytest.mark.parametrize(
    "spec", CORPUS.with_graph(), ids=lambda s: s.name
)
def test_graph_gold_wellformed(spec):
    g = load_graph_config(spec.name)
    assert g.commit == spec.graph_sha
    assert g.test_commits, f"{spec.name}: no test_commits"
    for mh in g.multi_hop_tasks:
        assert mh.expected_neighbor_names, f"{mh.id}: no expected neighbors"
        assert mh.traversal_pattern
    for sq in g.search_queries:
        assert "::" in sq.expected or sq.expected


def test_two_shas_when_graph_differs():
    # Sanity: at least one core repo pins retrieval and graph at different SHAs,
    # which is the reason we clone per-SHA.
    differing = [s for s in CORPUS.with_graph() if s.retrieval_sha != s.graph_sha]
    assert differing, "expected retrieval/graph SHA divergence somewhere"
