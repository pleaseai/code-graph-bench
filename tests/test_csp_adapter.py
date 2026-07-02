"""Unit tests for csp output parsing (no csp binary required)."""

from __future__ import annotations

import json

from bench.adapters.csp_adapter import _parse_hits

CSP_OUTPUT = json.dumps({
    "query": "how are routes registered",
    "results": [
        {
            "chunk": {
                "content": "def add_url_rule(self, rule): ...",
                "file_path": "src/flask/app.py",
                "start_line": 82,
                "end_line": 176,
                "language": "python",
                "location": "src/flask/app.py:82-176",
            },
            "score": 0.0223,
        }
    ],
})


def test_parse_hits():
    hits = _parse_hits(CSP_OUTPUT)
    assert len(hits) == 1
    h = hits[0]
    assert h.file_path == "src/flask/app.py"
    assert h.start_line == 82 and h.end_line == 176
    assert h.symbol is None  # chunk-based tool
    assert h.score == 0.0223
    assert h.n_chars == len("def add_url_rule(self, rule): ...")


def test_parse_hits_no_results():
    # csp emits {"error": "No results found."} instead of an empty results list
    assert _parse_hits(json.dumps({"error": "No results found."})) == []


def test_parse_hits_bad_json():
    assert _parse_hits("not json") == []
