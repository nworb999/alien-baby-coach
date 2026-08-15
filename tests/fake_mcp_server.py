from __future__ import annotations

import json
import os
import sys

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}, {"name": "env", "inputSchema": {"type": "object"}}]}
    elif method == "tools/call":
        if message["params"]["name"] == "env":
            value = {"openai": bool(os.getenv("OPENAI_API_KEY")), "allowed": os.getenv("TEST_MCP_TOKEN")}
        else:
            value = message["params"]["arguments"]
        result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
