from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Source:
    id: int
    provider: str
    title: str
    body: str
    external_id: str


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT,
                content TEXT NOT NULL, epistemic_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                external_id TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(provider, external_id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS source_search USING fts5(
                title, body, content='sources', content_rowid='id'
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                role TEXT NOT NULL, persona TEXT, content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS opinions (
                id INTEGER PRIMARY KEY, deliberation_id TEXT NOT NULL,
                persona TEXT NOT NULL, kind TEXT NOT NULL,
                content TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY, situation TEXT NOT NULL,
                hypothesis TEXT NOT NULL, action TEXT NOT NULL,
                expected_signal TEXT, outcome TEXT, lesson TEXT,
                status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
            );
        """)
        self.connection.execute("INSERT INTO source_search(source_search) VALUES ('rebuild')")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def remember(self, content: str, kind: str = "explicit", subject: str | None = None) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO memories(kind, subject, content, epistemic_status, created_at) VALUES (?, ?, ?, 'user-confirmed', ?)",
                (kind, subject, content, now()),
            )
        return int(cursor.lastrowid)

    def forget(self, memory_id: int) -> bool:
        with self.connection:
            cursor = self.connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cursor.rowcount > 0

    def add_message(self, session_id: str, role: str, persona: str | None, content: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(session_id, role, persona, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, persona, content, now()),
            )

    def add_source(self, provider: str, title: str, body: str, external_id: str | None = None, metadata: dict | None = None) -> int:
        external_id = external_id or hashlib.sha256(body.encode()).hexdigest()
        with self.connection:
            old = self.connection.execute(
                "SELECT id FROM sources WHERE provider = ? AND external_id = ?", (provider, external_id)
            ).fetchone()
            if old:
                self.connection.execute("DELETE FROM source_search WHERE rowid = ?", (old["id"],))
                self.connection.execute(
                    "UPDATE sources SET title = ?, body = ?, metadata_json = ?, created_at = ? WHERE id = ?",
                    (title, body, json.dumps(metadata or {}), now(), old["id"]),
                )
                source_id = int(old["id"])
            else:
                cursor = self.connection.execute(
                    "INSERT INTO sources(provider, external_id, title, body, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (provider, external_id, title, body, json.dumps(metadata or {}), now()),
                )
                source_id = int(cursor.lastrowid)
            self.connection.execute(
                "INSERT INTO source_search(rowid, title, body) VALUES (?, ?, ?)", (source_id, title, body)
            )
        return source_id

    def delete_source(self, source_id: int) -> bool:
        with self.connection:
            self.connection.execute("DELETE FROM source_search WHERE rowid = ?", (source_id,))
            cursor = self.connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        return cursor.rowcount > 0

    def search(self, query: str, limit: int = 5) -> list[Source]:
        terms = [token.strip('"\'():*+-') for token in query.split() if len(token.strip('"\'():*+-')) > 2][:12]
        rows: list[sqlite3.Row] = []
        if terms:
            expression = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
            try:
                rows = self.connection.execute(
                    "SELECT s.* FROM source_search f JOIN sources s ON s.id=f.rowid WHERE source_search MATCH ? ORDER BY bm25(source_search) LIMIT ?",
                    (expression, max(1, limit - 2)),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        memories: list[sqlite3.Row] = []
        if terms:
            clauses = " OR ".join("content LIKE ?" for _ in terms)
            memories = self.connection.execute(
                f"SELECT id, 'memory' provider, 'Explicit memory' title, content body, CAST(id AS TEXT) external_id FROM memories WHERE {clauses} ORDER BY id DESC LIMIT 2",
                tuple(f"%{term}%" for term in terms),
            ).fetchall()
        combined = list(memories) + list(rows)
        return [Source(int(row["id"]), row["provider"], row["title"], row["body"], row["external_id"]) for row in combined[:limit]]

    def list_sources(self, limit: int = 50) -> list[Source]:
        rows = self.connection.execute("SELECT * FROM sources ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Source(int(row["id"]), row["provider"], row["title"], row["body"], row["external_id"]) for row in rows]

    def add_opinion(self, deliberation_id: str, persona: str, kind: str, content: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO opinions(deliberation_id, persona, kind, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (deliberation_id, persona, kind, content, now()),
            )

    def add_experiment(self, situation: str, hypothesis: str, action: str, expected_signal: str = "") -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO experiments(situation, hypothesis, action, expected_signal, created_at) VALUES (?, ?, ?, ?, ?)",
                (situation, hypothesis, action, expected_signal, now()),
            )
        return int(cursor.lastrowid)

    def finish_experiment(self, experiment_id: int, outcome: str) -> bool:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE experiments SET outcome = ?, status = 'complete' WHERE id = ?", (outcome, experiment_id)
            )
        return cursor.rowcount > 0

    def list_experiments(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
