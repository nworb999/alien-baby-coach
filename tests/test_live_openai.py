from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "set RUN_LIVE_TESTS=1 to spend a real API call")
class LiveOpenAITest(unittest.TestCase):
    def test_terminal_receives_a_live_response(self) -> None:
        result = subprocess.run(
            [sys.executable, "coach.py"],
            cwd=ROOT,
            input="1\nReply with exactly: READY\n/quit\n",
            text=True,
            capture_output=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("coach\n", result.stdout)
        self.assertNotIn("error>", result.stdout)


if __name__ == "__main__":
    unittest.main()
