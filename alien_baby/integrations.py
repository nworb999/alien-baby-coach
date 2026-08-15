from __future__ import annotations

import hashlib
import re

from .mcp import McpError, McpStdioClient
from .memory import MemoryStore

SLACK_URL = re.compile(r"https://[^\s]+\.slack\.com/archives/[A-Z0-9]+/p\d+")
SLACK_ARGV = ["npx", "-y", "slack-mcp-server@1.3.0"]
GRANOLA_ARGV = ["npx", "-y", "mcp-remote@0.1.38", "https://mcp.granola.ai/mcp"]
SLACK_AUTH_ENV = {"SLACK_MCP_XOXP_TOKEN", "SLACK_MCP_XOXC_TOKEN", "SLACK_MCP_XOXD_TOKEN"}


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def import_slack(store: MemoryStore, target: str, topic: str = "", limit: int = 20) -> int:
    with McpStdioClient(SLACK_ARGV, allow_env=SLACK_AUTH_ENV) as client:
        tools = client.list_tools()
        name = "conversations_search_messages"
        if name not in tools:
            raise McpError(f"Slack MCP is missing {name}")
        if SLACK_URL.fullmatch(target):
            arguments = {"search_query": target, "limit": limit}
            title = "Slack thread"
        else:
            channel = target if target.startswith("#") else f"#{target}"
            arguments = {"filter_in_channel": channel, "limit": limit}
            if topic:
                arguments["search_query"] = topic
            title = f"Slack context from {channel}"
        body = client.call(name, arguments)
    return store.add_source("slack", title, body, stable_id("slack", target + topic), arguments)


def import_granola(store: MemoryStore, query: str) -> int:
    with McpStdioClient(GRANOLA_ARGV) as client:
        tools = client.list_tools()
        name = "query_granola_meetings"
        if name not in tools:
            raise McpError(f"Granola MCP is missing {name}")
        body = client.call(name, {"query": query})
    return store.add_source("granola", f"Granola: {query}", body, stable_id("granola", query), {"query": query})
