"""Adapter registry."""

from __future__ import annotations

from bench.adapters.codegraph_adapter import CodegraphAdapter
from bench.adapters.crg_adapter import CrgAdapter
from bench.adapters.csp_adapter import CspAdapter
from bench.adapters.lsp_adapter import LspAdapter
from bench.adapters.semble_adapter import SembleAdapter
from bench.adapters.soop_adapter import SoopAdapter
from bench.adapters.ttsc_adapter import TtscAdapter

ADAPTERS = {
    "semble": SembleAdapter,
    "crg": CrgAdapter,
    "codegraph": CodegraphAdapter,
    "soop": SoopAdapter,
    "csp": CspAdapter,
    "lsp": LspAdapter,
    "ttsc": TtscAdapter,
}

# soop is both a retriever and a graph, so it appears in both lists.
# lsp is structural-only (no NL retrieval), so it is graph-only.
# ttsc is TypeScript-only: it fails fast (with a clear message) on non-JS/TS repos.
SEARCH_TOOLS = ["semble", "crg", "codegraph", "soop", "csp"]
GRAPH_TOOLS = ["crg", "codegraph", "soop", "lsp", "ttsc"]


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise KeyError(f"unknown tool {name!r}; choose from {list(ADAPTERS)}")
    return ADAPTERS[name]()
