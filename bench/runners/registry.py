"""Adapter registry."""

from __future__ import annotations

from bench.adapters.codegraph_adapter import CodegraphAdapter
from bench.adapters.crg_adapter import CrgAdapter
from bench.adapters.semble_adapter import SembleAdapter

ADAPTERS = {
    "semble": SembleAdapter,
    "crg": CrgAdapter,
    "codegraph": CodegraphAdapter,
}

SEARCH_TOOLS = ["semble", "crg", "codegraph"]
GRAPH_TOOLS = ["crg", "codegraph"]


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise KeyError(f"unknown tool {name!r}; choose from {list(ADAPTERS)}")
    return ADAPTERS[name]()
