from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class Model(Protocol):
    def respond(self, instructions: str, message: str) -> str: ...


class FakeModel:
    def respond(self, instructions: str, message: str) -> str:
        heading = next((line.removeprefix("# ") for line in instructions.splitlines() if line.startswith("# ")), "Coach")
        return f"[{heading}] I heard: {message}"


class OpenAIModel:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured; add it to .env or use --fake-model")

    def respond(self, instructions: str, message: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "instructions": instructions,
            "input": message,
        }).encode()
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"OpenAI request failed with HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenAI request failed") from error

        if text := body.get("output_text"):
            return text
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return content["text"]
        raise RuntimeError("OpenAI returned no text response")
