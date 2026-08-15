from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, argv: list[str], timeout: float = 60, allow_env: set[str] | None = None):
        self.argv = argv
        self.timeout = timeout
        self.allow_env = allow_env or set()
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[str | None] = queue.Queue()
        self.pending: dict[int, dict[str, Any]] = {}
        self.counter = 0

    def __enter__(self) -> "McpStdioClient":
        base_env = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "NODE_EXTRA_CA_CERTS", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"}
        env = {key: value for key, value in os.environ.items() if key in base_env | self.allow_env}
        self.process = subprocess.Popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env, shell=False,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        try:
            self.request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "alien-baby-coach", "version": "0.1"},
            })
            self.notify("notifications/initialized", {})
            return self
        except Exception:
            self._close()
            raise

    def __exit__(self, *_: object) -> None:
        self._close()

    def _close(self) -> None:
        if not self.process:
            return
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process.stdout and not self.process.stdout.closed:
            self.process.stdout.close()
        if self.process.stderr and not self.process.stderr.closed:
            self.process.stderr.close()

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self.messages.put(line)
        self.messages.put(None)

    def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        for _ in self.process.stderr:
            pass

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise McpError("MCP server is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        request_id = self.counter
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if request_id in self.pending:
            return self._result(self.pending.pop(request_id))
        while True:
            try:
                line = self.messages.get(timeout=self.timeout)
            except queue.Empty as error:
                raise McpError("MCP request timed out") from error
            if line is None:
                raise McpError("MCP server closed unexpectedly")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise McpError("MCP server returned invalid data") from error
            if "method" in message and "id" in message:
                self._send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not found"}})
                continue
            if message.get("id") != request_id:
                if isinstance(message.get("id"), int):
                    self.pending[message["id"]] = message
                continue
            return self._result(message)

    def _result(self, message: dict[str, Any]) -> dict[str, Any]:
        if "error" in message:
            code = message["error"].get("code", "unknown")
            raise McpError(f"MCP request failed ({code})")
        return message.get("result", {})

    def list_tools(self) -> dict[str, dict[str, Any]]:
        tools: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.update({tool["name"]: tool for tool in result.get("tools", [])})
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpError("MCP tool reported an error")
        texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
        if not texts and result.get("structuredContent"):
            return json.dumps(result["structuredContent"], ensure_ascii=False)
        if not texts:
            raise McpError("MCP tool returned no supported content")
        return "\n".join(texts)
