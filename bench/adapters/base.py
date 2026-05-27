"""Uniform adapter interface.

Every tool, however it is invoked (Docker, isolated venv, or native CLI),
exposes one method for retrieval: ``run_search`` builds an index over a repo
checkout and answers a batch of queries, returning a `SearchRun` that carries
everything both Arm A (quality) and Perf (timing/footprint) need.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Hit:
    """One retrieved result, normalized across tools.

    ``file_path`` is always repo-root-relative. ``symbol`` is a qualified name
    when the tool returns symbols (graph tools); None for chunk-based tools.
    ``n_chars`` is the size of the payload the tool returns for this hit (code
    body for semble; node reference for graph tools) — used for token estimates.
    """

    file_path: str
    start_line: int | None
    end_line: int | None
    symbol: str | None
    score: float
    n_chars: int
    name: str | None = None
    kind: str | None = None


@dataclass
class QueryResult:
    query: str
    hits: list[Hit]
    latencies_ms: list[float]


@dataclass
class SearchRun:
    tool: str
    repo: str
    index_ms: float
    queries: list[QueryResult]
    stats: dict = field(default_factory=dict)
    db_bytes: int | None = None
    # Optional build breakdown (graph tools): parsing vs post-processing.
    build_ms: float | None = None
    post_ms: float | None = None
    extra: dict = field(default_factory=dict)


class SearchAdapter(Protocol):
    name: str

    def version(self) -> str: ...

    def search_modality(self) -> str:
        """e.g. 'semantic+lexical' | 'lexical (FTS5+keyword)' | 'lexical (FTS5)'."""
        ...

    def run_search(
        self, repo: str, repo_path: Path, queries: list[str], k: int, runs: int
    ) -> SearchRun: ...
