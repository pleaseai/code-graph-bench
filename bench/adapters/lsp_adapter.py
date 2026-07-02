"""LSP adapter — compiler/type-checker code intelligence over stdio.

Uses pleaseai/code-intelligence's `code lsp-server <id> --project=<repo>`
(a transparent pipe to the real language server) with a minimal Python LSP
client (bench/workers/lsp_client.py). Server per corpus language:
pyright (python), typescript-language-server (javascript), gopls (go).

LSP is a *structural* tool with no NL retrieval: its "own search" for the
Arm B anchor step is `workspace/symbol` over the verbose NL query, which is
fuzzy symbol-name matching — expected to fail like crg's FTS-AND (that IS
the finding; Arm C/H then supplies the anchor). Traversal is the LSP
callHierarchy family: incomingCalls (callers_of) / outgoingCalls (callees_of).

Language servers index in the background after `initialize`, so each session
warms up by polling workspace/symbol until the index answers (readiness
probe, excluded from any timing).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from bench.goldset import load_corpus
from bench.paths import REPO_ROOT
from bench.workers.lsp_client import LspClient, LspError

SERVER_IDS = {"python": "pyright", "javascript": "typescript", "go": "gopls"}

# typescript-language-server needs a classic tsserver.js; the bench keeps a
# stable TypeScript in .toolchain/ (npm install --prefix .toolchain typescript@5).
TSSERVER = REPO_ROOT / ".toolchain" / "node_modules" / "typescript" / "lib"

NEAR_MARGIN = 80  # lines: chunk-based anchor hits may sit beside the symbol
WARMUP_S = 45.0

# LSP SymbolKind values that can anchor a call-hierarchy traversal
# (Class, Method, Constructor, Interface, Function).
CALLABLE_KINDS = {5, 6, 9, 11, 12}


def _norm(sym: str) -> str:
    """Normalize symbol names across servers: gopls renders methods as
    '(*Engine).ServeHTTP' — strip receiver decoration so matching sees
    'engine.servehttp'."""
    return sym.replace("(*", "").replace("(", "").replace(")", "").lower()


def _bare(sym: str) -> str:
    return _norm(sym).split(".")[-1]


INVOCABLE_KINDS = {6, 9, 12}  # Method, Constructor, Function


def _pick_anchor(candidates: list[dict], bare: str, suffix_tail: str) -> tuple[dict | None, int]:
    """Staged anchor pick: exact qualified tail first (so Client.request is not
    shadowed by AsyncClient.request via a bare-name hit), then bare name on an
    invocable symbol (so a `Request` *class* does not shadow a `.request`
    *method*), then bare name on anything."""
    for i, c in enumerate(candidates):
        qn = _norm(c["qualified_name"])
        if qn == suffix_tail or qn.endswith("." + suffix_tail):
            return c, i
    for i, c in enumerate(candidates):
        if _bare(c["name"]) == bare and c.get("kind") in INVOCABLE_KINDS:
            return c, i
    for i, c in enumerate(candidates):
        if _bare(c["name"]) == bare:
            return c, i
    return None, -1


class LspAdapter:
    name = "lsp"

    def version(self) -> str:
        try:
            out = subprocess.run(["code", "--version"], capture_output=True, text=True)
            base = out.stdout.strip().splitlines()[-1] if out.returncode == 0 else "code"
        except FileNotFoundError:
            base = "code (not found)"
        return f"{base} (pyright/tsls/gopls)"

    def search_modality(self) -> str:
        return "structural (LSP workspace/symbol + callHierarchy)"

    # ----- session -----
    def _server_id(self, repo: str) -> str:
        lang = load_corpus().get(repo).language
        if lang not in SERVER_IDS:
            raise RuntimeError(f"lsp: no language server mapping for {lang!r} ({repo})")
        return SERVER_IDS[lang]

    def _open(self, repo: str, repo_path: Path, probe: str) -> LspClient:
        server_id = self._server_id(repo)
        if server_id == "gopls" and (repo_path / "go.mod").exists():
            # An untidy go.mod (common in older pinned snapshots) makes gopls
            # fail package loading silently — cross-file references and
            # callHierarchy return empty. Tidy is idempotent and touches only
            # go.mod/go.sum (same artifact category as codegraph's .codegraph/).
            subprocess.run(["go", "mod", "tidy"], cwd=str(repo_path),
                           capture_output=True, text=True)
        client = LspClient(
            ["code", "lsp-server", server_id, f"--project={repo_path.resolve()}"],
            repo_path,
        )
        init_opts = None
        if server_id == "typescript" and TSSERVER.exists():
            init_opts = {"tsserver": {"path": str(TSSERVER)}}
        client.initialize(init_opts)
        deadline = time.monotonic() + WARMUP_S
        while time.monotonic() < deadline:
            try:
                if client.workspace_symbols(probe):
                    break
            except LspError:
                break
            time.sleep(1.0)
        # background indexers (gopls package loads, pyright program analysis)
        # keep running after the first symbol answer — wait until quiet.
        client.wait_quiet(idle_s=2.0, timeout=WARMUP_S)
        return client

    # ----- shared traversal -----
    @staticmethod
    def _neighbors(client: LspClient, file: str, sel_line: int, sel_char: int,
                   pattern: str) -> set[str]:
        direction = {"callers_of": "incoming", "callees_of": "outgoing"}.get(pattern)
        if direction is None:
            return set()
        # gopls answers documentSymbol before its package loader finishes and
        # rejects callHierarchy with "no package metadata" until then — retry.
        deadline = time.monotonic() + WARMUP_S
        while True:
            try:
                names = client.call_hierarchy(file, sel_line, sel_char, direction)
                return {_bare(n) for n in names}
            except LspError as e:
                if "no package metadata" not in str(e) or time.monotonic() > deadline:
                    return set()
                time.sleep(3.0)

    @staticmethod
    def _row(task, found: bool, rank: int, names: set[str], expected: list[str]) -> dict:
        matched = sum(1 for e in expected if e in names)
        recall = matched / len(expected) if expected else 0.0
        return {"task_id": task.id, "anchor_found": found, "anchor_rank": rank,
                "neighbor_count": len(names), "expected_count": len(expected),
                "matched_count": matched, "neighbor_recall": round(recall, 3),
                "score": round(recall, 3) if found else 0.0,
                "neighbor_names": sorted(names)}

    # ----- Arm B: own search -> anchor -> traverse -----
    def multihop(self, repo: str, repo_path: Path, tasks: list) -> list[dict]:
        probe = tasks[0].anchor_qualified_suffix.split("::")[-1].split(".")[-1]
        client = self._open(repo, repo_path, probe)
        try:
            out = []
            for t in tasks:
                suffix = t.anchor_qualified_suffix.lower()
                tail = suffix.split("::")[-1]
                bare = tail.split(".")[-1]
                expected = [e.lower() for e in t.expected_neighbor_names]
                try:
                    raw_hits = client.workspace_symbols(t.nl_query)[: t.k]
                except LspError:
                    # e.g. tsserver's navto errors on verbose NL strings —
                    # that IS the own-search result: no anchor.
                    raw_hits = []
                hits = [
                    {**h, "qualified_name":
                        f'{h.get("container") or ""}.{h["name"]}'.lstrip(".")}
                    for h in raw_hits
                ]
                anchor, rank = _pick_anchor(hits, bare, tail)
                if anchor is None or anchor.get("file_path") is None:
                    out.append(self._row(t, False, -1, set(), expected))
                    continue
                names = self._neighbors(client, anchor["file_path"], anchor["sel_line"],
                                        anchor["sel_char"], t.traversal_pattern)
                out.append(self._row(t, True, rank, names, expected))
            return out
        finally:
            client.close()

    # ----- Arm C/H: external anchor hits -> resolve symbol -> traverse -----
    def combined(self, repo: str, repo_path: Path, tasks: list,
                 anchor_hits: dict) -> list[dict]:
        probe = tasks[0].anchor_qualified_suffix.split("::")[-1].split(".")[-1]
        client = self._open(repo, repo_path, probe)
        try:
            out = []
            for t in tasks:
                suffix = t.anchor_qualified_suffix.lower()
                tail = suffix.split("::")[-1]
                bare = tail.split(".")[-1]
                expected = [e.lower() for e in t.expected_neighbor_names]
                candidates, seen = [], set()
                for hit in anchor_hits.get(t.id, []):
                    try:
                        syms = client.document_symbols(hit["file"])
                    except (LspError, OSError):
                        continue
                    syms = [s for s in syms if s.get("kind") in CALLABLE_KINDS]
                    for s in _near(syms, hit.get("start_line"), hit.get("end_line")):
                        key = (hit["file"], s["qualified_name"])
                        if key not in seen:
                            seen.add(key)
                            candidates.append({**s, "file": hit["file"]})
                    if len(candidates) >= t.k:
                        break
                anchor, rank = _pick_anchor(candidates[: t.k], bare, tail)
                if anchor is None and candidates:
                    anchor = candidates[0]
                if anchor is None:
                    out.append(self._row(t, False, -1, set(), expected))
                    continue
                names = self._neighbors(client, anchor["file"], anchor["sel_line"],
                                        anchor["sel_char"], t.traversal_pattern)
                out.append(self._row(t, rank >= 0, rank, names, expected))
            return out
        finally:
            client.close()


def _near(syms: list[dict], lo, hi) -> list[dict]:
    """Symbols overlapping or within NEAR_MARGIN lines of [lo, hi], closest first."""
    out = []
    for s in syms:
        if lo is None or hi is None:
            gap = 0
        elif s["end_line"] < lo:
            gap = lo - s["end_line"]
        elif s["start_line"] > hi:
            gap = s["start_line"] - hi
        else:
            gap = 0
        if gap > NEAR_MARGIN:
            continue
        out.append({**s, "gap": gap, "span": s["end_line"] - s["start_line"]})
    out.sort(key=lambda d: (d["gap"], d["span"]))
    return out
