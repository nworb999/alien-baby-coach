from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alien_baby.context import build_case_file
from alien_baby.ingest import ingest_path
from alien_baby.memory import MemoryStore
from alien_baby.personas import PersonaRegistry
from alien_baby.service import CoachService

ROOT = Path(__file__).resolve().parent.parent


class RecordingModel:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def respond(self, instructions: str, message: str) -> str:
        self.calls.append((instructions, message))
        return f"reply-{len(self.calls)}"


class MemoryAndOrchestrationTests(unittest.TestCase):
    def test_memory_and_ingested_source_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "org.md"
            document.write_text("Morgan owns platform prioritization.")
            store = MemoryStore(root / "memory" / "coach.db")
            memory_id = store.remember("Written proposals work best with Morgan")
            source_ids = ingest_path(store, document)
            store.close()

            reopened = MemoryStore(root / "memory" / "coach.db")
            case = build_case_file(reopened, "Morgan platform")
            self.assertIn("Morgan owns platform prioritization", case)
            self.assertTrue(reopened.forget(memory_id))
            self.assertTrue(reopened.delete_source(source_ids[0]))
            self.assertEqual(reopened.list_sources(), [])
            reopened.close()

    def test_panel_is_independent_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = RecordingModel()
            store = MemoryStore(Path(directory) / "coach.db")
            service = CoachService(model, PersonaRegistry(ROOT / "personas"), store)
            opinions, synthesis = service.panel("What should I do?")
            self.assertEqual([name for name, _ in opinions], ["coach", "skeptic", "strategist"])
            self.assertEqual(len(model.calls), 4)
            self.assertNotIn("reply-1", model.calls[1][0])
            self.assertEqual(synthesis, "reply-4")
            store.close()

    def test_debate_has_one_critique_round_and_synthesis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = RecordingModel()
            store = MemoryStore(Path(directory) / "coach.db")
            service = CoachService(model, PersonaRegistry(ROOT / "personas"), store)
            critiques, synthesis = service.debate("Roadmap?", "coach", "strategist")
            self.assertEqual(len(critiques), 2)
            self.assertEqual(len(model.calls), 5)
            self.assertEqual(synthesis, "reply-5")
            store.close()


if __name__ == "__main__":
    unittest.main()
