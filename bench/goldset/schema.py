"""Canonical gold-set schema + loaders.

The retrieval schema is semble's annotation format
(``{query, relevant, secondary, category}``) with one extension: a relevant
entry may be a plain path string (semble's published form) *or* an object
``{path, start_line?, end_line?, symbol?}`` so that line spans and symbol names
can be attached for graph tools that match at symbol granularity.

The graph schema mirrors code-review-graph's eval YAML
(``test_commits``, ``search_queries``, ``multi_hop_tasks``, ``entry_points``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bench.paths import CORPUS_FILE, GRAPH_DIR, RETRIEVAL_DIR


# --------------------------------------------------------------------------- #
# Retrieval gold (semble-derived)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Target:
    """A relevant code location for a query."""

    path: str
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None

    @property
    def has_span(self) -> bool:
        return self.start_line is not None and self.end_line is not None

    @classmethod
    def parse(cls, raw: str | dict) -> "Target":
        if isinstance(raw, str):
            return cls(path=raw)
        return cls(
            path=raw["path"],
            start_line=raw.get("start_line"),
            end_line=raw.get("end_line"),
            symbol=raw.get("symbol"),
        )


@dataclass(frozen=True)
class RetrievalTask:
    repo: str
    query: str
    relevant: tuple[Target, ...]
    secondary: tuple[Target, ...]
    category: str  # "semantic" | "architecture" | "symbol"

    @property
    def all_relevant(self) -> tuple[Target, ...]:
        return self.relevant + self.secondary


def load_retrieval_tasks(repo: str) -> list[RetrievalTask]:
    path = RETRIEVAL_DIR / f"{repo}.json"
    raw = json.loads(path.read_text())
    tasks: list[RetrievalTask] = []
    for item in raw:
        tasks.append(
            RetrievalTask(
                repo=repo,
                query=item["query"],
                relevant=tuple(Target.parse(t) for t in item.get("relevant", [])),
                secondary=tuple(Target.parse(t) for t in item.get("secondary", [])),
                category=item.get("category", "unknown"),
            )
        )
    return tasks


# --------------------------------------------------------------------------- #
# Graph / impact gold (code-review-graph-derived)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TestCommit:
    sha: str
    description: str = ""
    changed_files: int | None = None


@dataclass(frozen=True)
class SearchQuery:
    query: str
    expected: str  # qualified name, e.g. "src/flask/app.py::Flask"


@dataclass(frozen=True)
class MultiHopTask:
    id: str
    nl_query: str
    anchor_qualified_suffix: str
    traversal_pattern: str  # e.g. "callers_of"
    expected_neighbor_names: tuple[str, ...]
    k: int = 10


@dataclass(frozen=True)
class GraphConfig:
    repo: str
    url: str
    commit: str
    language: str
    test_commits: tuple[TestCommit, ...]
    search_queries: tuple[SearchQuery, ...]
    multi_hop_tasks: tuple[MultiHopTask, ...]
    entry_points: tuple[str, ...]


def load_graph_config(repo: str) -> GraphConfig:
    path = GRAPH_DIR / f"{repo}.yaml"
    d = yaml.safe_load(path.read_text())
    return GraphConfig(
        repo=d["name"],
        url=d["url"],
        commit=d["commit"],
        language=d.get("language", "unknown"),
        test_commits=tuple(
            TestCommit(sha=tc["sha"], description=tc.get("description", ""),
                       changed_files=tc.get("changed_files"))
            for tc in d.get("test_commits", [])
        ),
        search_queries=tuple(
            SearchQuery(query=sq["query"], expected=sq["expected"])
            for sq in d.get("search_queries", [])
        ),
        multi_hop_tasks=tuple(
            MultiHopTask(
                id=mh["id"],
                nl_query=mh["nl_query"],
                anchor_qualified_suffix=mh["anchor_qualified_suffix"],
                traversal_pattern=mh["traversal_pattern"],
                expected_neighbor_names=tuple(mh.get("expected_neighbor_names", [])),
                k=mh.get("k", 10),
            )
            for mh in d.get("multi_hop_tasks", [])
        ),
        entry_points=tuple(d.get("entry_points", [])),
    )


# --------------------------------------------------------------------------- #
# Corpus (repo registry with pinned SHAs)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RepoSpec:
    name: str
    language: str
    url: str
    tier: str  # "core" | "ext"
    retrieval_sha: str
    retrieval_root: str | None
    graph_sha: str | None
    graph_test_commits: tuple[TestCommit, ...] = field(default_factory=tuple)

    @property
    def has_graph(self) -> bool:
        return self.graph_sha is not None


@dataclass(frozen=True)
class Corpus:
    repos: tuple[RepoSpec, ...]

    def get(self, name: str) -> RepoSpec:
        for r in self.repos:
            if r.name == name:
                return r
        raise KeyError(f"repo {name!r} not in corpus")

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.repos]

    def with_graph(self) -> list[RepoSpec]:
        return [r for r in self.repos if r.has_graph]


def load_corpus(path: Path = CORPUS_FILE) -> Corpus:
    d = json.loads(path.read_text())
    repos: list[RepoSpec] = []
    for e in d["repos"]:
        g = e.get("graph")
        repos.append(
            RepoSpec(
                name=e["name"],
                language=e["language"],
                url=e["url"],
                tier=e.get("tier", "core"),
                retrieval_sha=e["retrieval"]["sha"],
                retrieval_root=e["retrieval"].get("root"),
                graph_sha=g["sha"] if g else None,
                graph_test_commits=tuple(
                    TestCommit(sha=tc["sha"], description=tc.get("description", ""),
                               changed_files=tc.get("changed_files"))
                    for tc in (g.get("test_commits", []) if g else [])
                ),
            )
        )
    return Corpus(repos=tuple(repos))
