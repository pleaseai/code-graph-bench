"""Gold-set schema and loaders.

Retrieval labels are sourced from MinishLab/semble (MIT), graph/impact labels
from tirth8205/code-review-graph (MIT). See bench/goldset/SOURCES.md.
"""

from bench.goldset.schema import (
    Corpus,
    GraphConfig,
    MultiHopTask,
    RepoSpec,
    RetrievalTask,
    SearchQuery,
    Target,
    TestCommit,
    load_corpus,
    load_graph_config,
    load_retrieval_tasks,
)

__all__ = [
    "Corpus",
    "GraphConfig",
    "MultiHopTask",
    "RepoSpec",
    "RetrievalTask",
    "SearchQuery",
    "Target",
    "TestCommit",
    "load_corpus",
    "load_graph_config",
    "load_retrieval_tasks",
]
