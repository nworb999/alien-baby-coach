from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Persona:
    name: str
    prompt: str


class PersonaRegistry:
    def __init__(self, directory: Path):
        self._personas = {
            path.stem: Persona(path.stem, path.read_text())
            for path in sorted(directory.glob("*.md"))
        }
        if not self._personas:
            raise ValueError(f"No personas found in {directory}")

    def names(self) -> list[str]:
        return list(self._personas)

    def get(self, name: str) -> Persona:
        try:
            return self._personas[name]
        except KeyError as error:
            available = ", ".join(self.names())
            raise ValueError(f"Unknown persona {name!r}. Available: {available}") from error
