from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from .config import load_env
from .context import build_case_file
from .ingest import ingest_path
from .integrations import SLACK_URL, import_granola, import_slack
from .mcp import McpError
from .memory import MemoryStore
from .model import FakeModel, Model, OpenAIModel
from .personas import PersonaRegistry
from .service import CoachService

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
VIOLET = "\033[38;5;141m"
CYAN = "\033[38;5;117m"
GREEN = "\033[38;5;114m"
YELLOW = "\033[38;5;221m"
RED = "\033[38;5;203m"

PERSONA_BLURBS = {
    "coach": "influence · leverage · leadership",
    "skeptic": "incentives · systems · counterpoint",
    "strategist": "diagnosis · tradeoffs · coherent action",
}


class Theme:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def paint(self, color: str, text: str) -> str:
        return f"{color}{text}{RESET}" if self.enabled else text


def color_enabled(stdout: object) -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR") == "1":
        return True
    return bool(getattr(stdout, "isatty", lambda: False)()) and os.getenv("TERM") != "dumb"


def banner(active: str, theme: Theme) -> str:
    title = theme.paint(BOLD + VIOLET, f"{'ALIEN BABY COACH':<40}")
    active_name = theme.paint(CYAN, f"{active:<35}")
    memory = theme.paint(DIM, f"{'local and private':<35}")
    return f"""╭────────────────────────────────────────────╮
│  ◉ {title}│
│  voice  {active_name}│
│  memory {memory}│
╰────────────────────────────────────────────╯"""


def show_personas(registry: PersonaRegistry, theme: Theme, stdout: object) -> None:
    print(theme.paint(BOLD, "Choose your counsel"), file=stdout)
    for index, name in enumerate(registry.names(), 1):
        blurb = PERSONA_BLURBS.get(name, "a different point of view")
        number = theme.paint(VIOLET, str(index))
        print(f"  {number}  {theme.paint(CYAN, f'{name:<12}')}  {theme.paint(DIM, blurb)}", file=stdout)


def choose_persona(registry: PersonaRegistry, theme: Theme, stdin: object, stdout: object) -> str | None:
    show_personas(registry, theme, stdout)
    print(theme.paint(DIM, "Pick 1–3, or press Enter for coach."), file=stdout)
    print(f"{theme.paint(GREEN, 'choice')}> ", end="", flush=True, file=stdout)
    line = stdin.readline()
    if not line:
        return None
    choice = line.strip()
    if not choice:
        return "coach" if "coach" in registry.names() else registry.names()[0]
    if choice.isdigit() and 1 <= int(choice) <= len(registry.names()):
        return registry.names()[int(choice) - 1]
    try:
        return registry.get(choice).name
    except ValueError:
        print(theme.paint(YELLOW, "That path is not open; beginning with coach."), file=stdout)
        return "coach" if "coach" in registry.names() else registry.names()[0]


HELP = """Commands
  /choose                    choose a different voice
  /ask NAME                  switch directly
  /panel QUESTION            hear every voice, then a moderator
  /debate A B QUESTION       run one bounded debate
  /remember TEXT             save a confirmed memory
  /forget ID                 delete a memory
  /ingest PATH               import local text, Markdown, JSON, or CSV
  /context QUERY             inspect retrieved context
  /sources                   list imported sources
  /slack URL                 import a Slack thread
  /slack #CHANNEL TOPIC      search a Slack channel
  /granola QUERY             import meeting context
  /experiment A | B | C | D  track situation, hypothesis, action, signal
  /outcome ID TEXT           close an experiment
  /experiments               list leadership experiments
  /personas                  list voices
  /help                      show this guide
  /quit                      leave
"""


def run(model: Model, registry: PersonaRegistry, memory: MemoryStore, stdin=sys.stdin, stdout=sys.stdout) -> int:
    theme = Theme(color_enabled(stdout))
    service = CoachService(model, registry, memory)
    active = choose_persona(registry, theme, stdin, stdout)
    if active is None:
        print(file=stdout)
        return 0
    print("\n" + banner(active, theme), file=stdout)
    print(theme.paint(DIM, "Tell me what happened. I will listen—and push back when it helps."), file=stdout)

    while True:
        print(f"\n{theme.paint(GREEN, 'you')} {theme.paint(DIM, f'› {active}')}\n{theme.paint(GREEN, '❯')} ", end="", flush=True, file=stdout)
        line = stdin.readline()
        if not line:
            print(file=stdout)
            return 0
        text = line.strip()
        if not text:
            continue
        if text in {"/quit", "/exit"}:
            print(theme.paint(DIM, "Until next time."), file=stdout)
            return 0
        if text == "/help":
            print(HELP, end="", file=stdout)
            continue
        if text == "/personas":
            show_personas(registry, theme, stdout)
            continue
        if text == "/choose":
            chosen = choose_persona(registry, theme, stdin, stdout)
            if chosen is None:
                return 0
            active = chosen
            print(theme.paint(CYAN, f"The {active} takes the chair."), file=stdout)
            continue
        if text.startswith("/ask "):
            requested = text.removeprefix("/ask ").strip()
            try:
                registry.get(requested)
            except ValueError as error:
                print(theme.paint(YELLOW, f"error › {error}"), file=stdout)
            else:
                active = requested
                print(theme.paint(CYAN, f"The {active} takes the chair."), file=stdout)
            continue
        try:
            if text.startswith("/remember "):
                memory_id = memory.remember(text.removeprefix("/remember ").strip())
                print(theme.paint(CYAN, f"Remembered as M-{memory_id}."), file=stdout)
                continue
            if text.startswith("/forget "):
                memory_id = int(text.removeprefix("/forget ").removeprefix("M-").strip())
                print("Forgotten." if memory.forget(memory_id) else "Memory not found.", file=stdout)
                continue
            if text.startswith("/ingest "):
                ids = ingest_path(memory, Path(text.removeprefix("/ingest ").strip()))
                print(theme.paint(CYAN, f"Imported {len(ids)} source(s)."), file=stdout)
                continue
            if text.startswith("/context "):
                case = build_case_file(memory, text.removeprefix("/context ").strip())
                print(case or "No relevant context found.", file=stdout)
                continue
            if text == "/sources":
                sources = memory.list_sources()
                print("\n".join(f"S-{s.id}  {s.provider:<8} {s.title}" for s in sources) or "No sources yet.", file=stdout)
                continue
            if text.startswith("/slack "):
                parts = shlex.split(text.removeprefix("/slack "))
                if not parts:
                    raise ValueError("Usage: /slack URL or /slack #channel topic")
                source_id = import_slack(memory, parts[0], " ".join(parts[1:]))
                print(theme.paint(CYAN, f"Imported Slack context as S-{source_id}."), file=stdout)
                continue
            if text.startswith("/granola "):
                source_id = import_granola(memory, text.removeprefix("/granola ").strip())
                print(theme.paint(CYAN, f"Imported Granola context as S-{source_id}."), file=stdout)
                continue
            if text.startswith("/experiment "):
                parts = [part.strip() for part in text.removeprefix("/experiment ").split("|")]
                if len(parts) not in {3, 4}:
                    raise ValueError("Usage: /experiment SITUATION | HYPOTHESIS | ACTION | EXPECTED SIGNAL")
                experiment_id = memory.add_experiment(*parts)
                print(theme.paint(CYAN, f"Experiment E-{experiment_id} is open."), file=stdout)
                continue
            if text.startswith("/outcome "):
                identifier, outcome = text.removeprefix("/outcome ").split(maxsplit=1)
                experiment_id = int(identifier.removeprefix("E-"))
                print("Experiment closed." if memory.finish_experiment(experiment_id, outcome) else "Experiment not found.", file=stdout)
                continue
            if text == "/experiments":
                rows = memory.list_experiments()
                print("\n".join(f"E-{row['id']}  {row['status']:<8} {row['situation']}" for row in rows) or "No experiments yet.", file=stdout)
                continue
            if text.startswith("/panel "):
                question = text.removeprefix("/panel ").strip()
                opinions, synthesis = service.panel(question)
                for name, opinion in opinions:
                    print(f"\n{theme.paint(BOLD + VIOLET, name)}\n{opinion}", file=stdout)
                print(f"\n{theme.paint(BOLD + CYAN, 'moderator')}\n{synthesis}", file=stdout)
                continue
            if text.startswith("/debate "):
                parts = shlex.split(text.removeprefix("/debate "))
                if len(parts) < 3:
                    raise ValueError("Usage: /debate PERSONA PERSONA QUESTION")
                registry.get(parts[0]); registry.get(parts[1])
                critiques, synthesis = service.debate(" ".join(parts[2:]), parts[0], parts[1])
                for name, critique in critiques:
                    print(f"\n{theme.paint(BOLD + VIOLET, name)}\n{critique}", file=stdout)
                print(f"\n{theme.paint(BOLD + CYAN, 'moderator')}\n{synthesis}", file=stdout)
                continue
            if text.startswith("/"):
                print(theme.paint(YELLOW, "Unknown path. Type /help."), file=stdout)
                continue

            if match := SLACK_URL.search(text):
                source_id = import_slack(memory, match.group(0))
                print(theme.paint(CYAN, f"Loaded linked Slack thread as S-{source_id}."), file=stdout)

            print(f"\n{theme.paint(VIOLET, active)} {theme.paint(DIM, 'is thinking…')}", file=stdout)
            answer = service.answer(active, text)
        except (RuntimeError, McpError, ValueError, OSError) as error:
            print(theme.paint(RED, f"error › {error}"), file=stdout)
        else:
            print(f"\n{theme.paint(BOLD + VIOLET, active)}\n{answer}", file=stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A candid engineering leadership coach")
    parser.add_argument("--fake-model", action="store_true", help="use deterministic local replies")
    parser.add_argument("--db", type=Path, help="override the local memory database")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    load_env(root / ".env")
    registry = PersonaRegistry(root / "personas")
    try:
        model: Model = FakeModel() if args.fake_model else OpenAIModel()
    except ValueError as error:
        parser.error(str(error))
    db_path = args.db or root / ".alien-baby" / "coach.db"
    memory = MemoryStore(db_path)
    try:
        return run(model, registry, memory)
    finally:
        memory.close()
