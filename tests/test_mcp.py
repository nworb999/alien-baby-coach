from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

from alien_baby.mcp import McpStdioClient

ROOT = Path(__file__).resolve().parent.parent


class McpTests(unittest.TestCase):
    def test_full_stdio_lifecycle(self) -> None:
        old_openai = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "must-not-reach-child"
        os.environ["TEST_MCP_TOKEN"] = "allowed-token"
        try:
            with McpStdioClient(
                [sys.executable, str(ROOT / "tests" / "fake_mcp_server.py")],
                timeout=2,
                allow_env={"TEST_MCP_TOKEN"},
            ) as client:
                self.assertIn("echo", client.list_tools())
                result = client.call("echo", {"hello": "world"})
                self.assertEqual(json.loads(result), {"hello": "world"})
                child_env = json.loads(client.call("env", {}))
                self.assertEqual(child_env, {"openai": False, "allowed": "allowed-token"})
        finally:
            os.environ.pop("TEST_MCP_TOKEN", None)
            if old_openai is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_openai


if __name__ == "__main__":
    unittest.main()
