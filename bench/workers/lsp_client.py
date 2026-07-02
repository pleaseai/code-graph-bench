"""Minimal LSP JSON-RPC client over a stdio server pipe.

Speaks Content-Length-framed JSON-RPC 2.0 to a language server spawned via
pleaseai/code-intelligence's `code lsp-server <id> --project=<repo>` (a
transparent byte pipe to pyright-langserver / typescript-language-server /
gopls). Implements only what the bench needs: initialize, didOpen,
documentSymbol, workspace/symbol, and the callHierarchy family.

LSP servers index in the background after `initialize` returns, so callers
must treat early empty responses as "not ready yet" (see LspAdapter's retry).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

LANGUAGE_IDS = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go"}


class LspError(RuntimeError):
    pass


class LspClient:
    """One language server bound to one repo checkout."""

    def __init__(self, server_cmd: list[str], repo_path: Path, timeout: float = 60.0):
        self.repo = repo_path.resolve()
        self.timeout = timeout
        self._proc = subprocess.Popen(
            server_cmd, cwd=str(self.repo),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, dict] = {}
        self._progress: set = set()  # active workDoneProgress tokens
        self._last_progress = time.monotonic()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._opened: set[str] = set()

    # ----- framing -----
    def _read_loop(self) -> None:
        out = self._proc.stdout
        while True:
            headers = {}
            line = out.readline()
            if not line:
                return
            while line and line.strip():
                key, _, val = line.decode("ascii", "replace").partition(":")
                headers[key.strip().lower()] = val.strip()
                line = out.readline()
            n = int(headers.get("content-length", 0))
            if n <= 0:
                continue
            body = out.read(n)
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                self._responses[msg["id"]] = msg
            # server->client requests (registerCapability, workDoneProgress/create…)
            elif "id" in msg and "method" in msg:
                if msg["method"] == "window/workDoneProgress/create":
                    self._progress.add(msg.get("params", {}).get("token"))
                    self._last_progress = time.monotonic()
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
            elif msg.get("method") == "$/progress":
                p = msg.get("params", {})
                self._last_progress = time.monotonic()
                if p.get("value", {}).get("kind") == "end":
                    self._progress.discard(p.get("token"))

    def _send(self, msg: dict) -> None:
        data = json.dumps(msg).encode()
        frame = b"Content-Length: %d\r\n\r\n%s" % (len(data), data)
        with self._lock:
            self._proc.stdin.write(frame)
            self._proc.stdin.flush()

    def request(self, method: str, params: dict | None) -> dict | list | None:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if rid in self._responses:
                msg = self._responses.pop(rid)
                if "error" in msg:
                    raise LspError(f"{method}: {msg['error']}")
                return msg.get("result")
            if self._proc.poll() is not None:
                raise LspError(f"server exited (rc={self._proc.returncode}) during {method}")
            time.sleep(0.01)
        raise LspError(f"timeout waiting for {method}")

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ----- protocol -----
    def initialize(self, initialization_options: dict | None = None) -> dict | list | None:
        uri = self.repo.as_uri()
        params = {
            "processId": None,
            "rootUri": uri,
            "workspaceFolders": [{"uri": uri, "name": self.repo.name}],
            "capabilities": {
                "textDocument": {
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "callHierarchy": {},
                },
                "workspace": {"symbol": {}},
            },
        }
        if initialization_options:
            params["initializationOptions"] = initialization_options
        result = self.request("initialize", params)
        self.notify("initialized", {})
        return result

    def did_open(self, rel_file: str) -> None:
        if rel_file in self._opened:
            return
        p = self.repo / rel_file
        lang = LANGUAGE_IDS.get(p.suffix, "plaintext")
        self.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": p.as_uri(), "languageId": lang, "version": 1,
                "text": p.read_text(errors="replace"),
            },
        })
        self._opened.add(rel_file)

    def document_symbols(self, rel_file: str) -> list[dict]:
        """Flat list: {name, start_line, end_line, sel_line, sel_char} (1-based lines)."""
        self.did_open(rel_file)
        res = self.request("textDocument/documentSymbol",
                           {"textDocument": {"uri": (self.repo / rel_file).as_uri()}})
        out: list[dict] = []

        def walk(sym: dict, container: str) -> None:
            if "range" in sym:  # DocumentSymbol (hierarchical)
                r, sel = sym["range"], sym.get("selectionRange", sym["range"])
                qualified = f"{container}.{sym['name']}" if container else sym["name"]
                out.append({
                    "name": sym["name"], "qualified_name": qualified,
                    "kind": sym.get("kind"),
                    "start_line": r["start"]["line"] + 1, "end_line": r["end"]["line"] + 1,
                    "sel_line": sel["start"]["line"], "sel_char": sel["start"]["character"],
                })
                for ch in sym.get("children") or []:
                    walk(ch, qualified)
            else:  # SymbolInformation (flat)
                r = sym["location"]["range"]
                out.append({
                    "name": sym["name"],
                    "qualified_name": (f'{sym["containerName"]}.{sym["name"]}'
                                       if sym.get("containerName") else sym["name"]),
                    "kind": sym.get("kind"),
                    "start_line": r["start"]["line"] + 1, "end_line": r["end"]["line"] + 1,
                    "sel_line": r["start"]["line"], "sel_char": r["start"]["character"],
                })

        for s in res or []:
            walk(s, "")
        return out

    def workspace_symbols(self, query: str) -> list[dict]:
        res = self.request("workspace/symbol", {"query": query}) or []
        out = []
        for s in res:
            loc = s.get("location", {})
            uri = loc.get("uri", "")
            rel = _rel(uri, self.repo)
            r = loc.get("range") or {"start": {"line": 0}, "end": {"line": 0}}
            out.append({
                "name": s.get("name"), "container": s.get("containerName"),
                "kind": s.get("kind"), "file_path": rel,
                "start_line": r["start"]["line"] + 1, "end_line": r["end"]["line"] + 1,
                "sel_line": r["start"]["line"],
                "sel_char": r["start"].get("character", 0),
            })
        return out

    def call_hierarchy(self, rel_file: str, line0: int, char0: int,
                       direction: str) -> list[str]:
        """Names of incoming callers / outgoing callees at a 0-based position."""
        self.did_open(rel_file)
        items = self.request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": (self.repo / rel_file).as_uri()},
            "position": {"line": line0, "character": char0},
        }) or []
        names: list[str] = []
        method = ("callHierarchy/incomingCalls" if direction == "incoming"
                  else "callHierarchy/outgoingCalls")
        key = "from" if direction == "incoming" else "to"
        for item in items:
            calls = self.request(method, {"item": item}) or []
            names.extend(c[key]["name"] for c in calls if c.get(key))
        return names

    def wait_quiet(self, idle_s: float = 2.0, timeout: float = 60.0) -> None:
        """Block until the server has no active progress work and has been
        quiet for `idle_s` (language servers index in the background after
        `initialize`; callHierarchy/references are incomplete until done)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            quiet_for = time.monotonic() - self._last_progress
            if not self._progress and quiet_for >= idle_s:
                return
            time.sleep(0.2)

    def close(self) -> None:
        try:
            self.request("shutdown", None)
            self.notify("exit", {})
        except LspError:
            pass
        finally:
            self._proc.kill()


def _rel(uri: str, repo: Path) -> str | None:
    prefix = repo.as_uri().rstrip("/") + "/"
    return uri[len(prefix):] if uri.startswith(prefix) else None
