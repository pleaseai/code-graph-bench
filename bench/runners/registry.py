"""Adapter registry."""

from __future__ import annotations

from bench.adapters.codegraph_adapter import CodegraphAdapter
from bench.adapters.crg_adapter import CrgAdapter
from bench.adapters.csp_adapter import CspAdapter
from bench.adapters.semble_adapter import SembleAdapter
from bench.adapters.soop_adapter import SoopAdapter

ADAPTERS = {
    "semble": SembleAdapter,
    "crg": CrgAdapter,
    "codegraph": CodegraphAdapter,
    "soop": SoopAdapter,
    "csp": CspAdapter,
}

# soop is both a retriever and a graph, so it appears in both lists.
SEARCH_TOOLS = ["semble", "crg", "codegraph", "soop", "csp"]
GRAPH_TOOLS = ["crg", "codegraph", "soop"]


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise KeyError(f"unknown tool {name!r}; choose from {list(ADAPTERS)}")
    return ADAPTERS[name]()
