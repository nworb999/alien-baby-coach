from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_cli(input_text: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "coach.py", *args],
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


class CliEndToEndTests(unittest.TestCase):
    def test_help_chat_and_quit_with_fake_model(self) -> None:
        result = run_cli("1\n/help\nhello\n/quit\n", "--fake-model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ALIEN BABY COACH", result.stdout)
        self.assertIn("/ask NAME", result.stdout)
        self.assertIn("coach\n[Staff Leadership Coach] I heard: hello", result.stdout)

    def test_color_can_be_forced_for_terminal_rendering(self) -> None:
        env = os.environ.copy()
        env["FORCE_COLOR"] = "1"
        result = run_cli("1\n/quit\n", "--fake-model", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\033[", result.stdout)

    def test_memory_ingestion_and_panel_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "org.md"
            document.write_text("Morgan owns the platform roadmap.")
            result = run_cli(
                f"1\n/remember Morgan prefers pre-reads\n/ingest {document}\n/context platform roadmap\n/panel What now?\n/sources\n/quit\n",
                "--fake-model", "--db", str(root / "coach.db"),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Remembered as M-1", result.stdout)
        self.assertIn("Imported 1 source", result.stdout)
        self.assertIn("Morgan owns the platform roadmap", result.stdout)
        self.assertIn("moderator", result.stdout)
        self.assertIn("S-1", result.stdout)

    def test_switching_persona_changes_the_real_prompt(self) -> None:
        received: list[dict[str, object]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                received.append(json.loads(self.rfile.read(length)))
                body = json.dumps({"output_text": "strategy reply"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env.update({
                "OPENAI_API_KEY": "test-secret-never-print",
                "OPENAI_MODEL": "test-model",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            })
            result = run_cli("1\n/personas\n/ask strategist\nReview my roadmap.\n/quit\n", env=env)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("The strategist takes the chair.", result.stdout)
        self.assertIn("strategist\nstrategy reply", result.stdout)
        self.assertNotIn("test-secret-never-print", result.stdout + result.stderr)
        self.assertEqual(len(received), 1)
        request = received[0]
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["input"], "Review my roadmap.")
        self.assertIn("diagnosis", str(request["instructions"]))
        self.assertNotIn("heroic execution", str(request["instructions"]))

    def test_http_error_is_sanitized(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.send_response(401)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env.update({
                "OPENAI_API_KEY": "test-secret-never-print",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            })
            result = run_cli("1\nhello\n/quit\n", env=env)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(result.returncode, 0)
        self.assertIn("OpenAI request failed with HTTP 401", result.stdout)
        self.assertNotIn("test-secret-never-print", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
