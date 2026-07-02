"""Minimal MCP (Model Context Protocol) stdio client.

Speaks newline-delimited JSON-RPC 2.0 to an MCP server subprocess — just
enough to initialize and issue tools/call. Used to drive @ttsc/graph's
resident server with its real typed-request logic instead of re-implementing
graph queries client-side.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, cmd: list[str], cwd: str | None = None,
                 env: dict | None = None, timeout: float = 120.0):
        self.timeout = timeout
        self._proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        self._id = 0
        self._responses: dict[int, dict] = {}
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self) -> None:
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                self._responses[msg["id"]] = msg

    def _send(self, msg: dict) -> None:
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if rid in self._responses:
                msg = self._responses.pop(rid)
                if "error" in msg:
                    raise McpError(f"{method}: {msg['error']}")
                return msg.get("result") or {}
            if self._proc.poll() is not None:
                raise McpError(f"server exited (rc={self._proc.returncode}) during {method}")
            time.sleep(0.01)
        raise McpError(f"timeout waiting for {method}")

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "cibench", "version": "0"},
        })
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def call_tool(self, name: str, arguments: dict) -> dict | list:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except json.JSONDecodeError:
                    return {"text": item["text"]}
        return result

    def close(self) -> None:
        self._proc.kill()
