from __future__ import annotations

import json
from pathlib import Path

from .memory import MemoryStore

SUPPORTED = {".md", ".txt", ".json", ".csv"}
MAX_FILE_BYTES = 5_000_000


def ingest_path(store: MemoryStore, path: Path) -> list[int]:
    path = path.expanduser().resolve()
    files = sorted(path.rglob("*")) if path.is_dir() else [path]
    imported: list[int] = []
    for file in files:
        if not file.is_file() or file.is_symlink() or file.suffix.lower() not in SUPPORTED:
            continue
        if file.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"File is too large: {file}")
        body = file.read_text(errors="replace")
        if file.suffix.lower() == ".json":
            try:
                body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON: {file}") from error
        imported.append(store.add_source("file", file.name, body, str(file)))
    return imported
