"""Memory system with tiered SQLite storage."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TIERS = ("episodic", "semantic", "procedural")
SCOPES = ("project", "file", "symbol", "global")

DEFAULT_TTL = {
    "episodic": 7,
    "semantic": None,
    "procedural": None,
}


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: str
    tier: str
    scope: str
    key: str
    value: str
    confidence: float = 1.0
    source_trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    is_valid: bool = True


@dataclass
class MemoryConfig:
    """Configuration for memory system."""

    db_path: str | Path = str(Path.home() / ".noman" / "memory.db")
    default_ttl_days: int = 7
    max_memories: int = 10000


class MemoryStore:
    """SQLite-backed memory storage."""

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._cfg = config or MemoryConfig()
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    def _require_conn(self) -> sqlite3.Connection:
        """Ensure the database connection is available."""
        if self._conn is None:
            raise RuntimeError("Database is closed")
        return self._conn

    def _ensure_db(self) -> None:
        """Ensure database and tables exist."""
        db_path = Path(self._cfg.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row

        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS memories ("
            "id TEXT PRIMARY KEY,"
            "tier TEXT NOT NULL,"
            "scope TEXT NOT NULL,"
            "key TEXT NOT NULL,"
            "value TEXT NOT NULL,"
            "confidence REAL DEFAULT 1.0,"
            "source_trace_id TEXT,"
            "created_at TEXT,"
            "updated_at TEXT,"
            "expires_at TEXT,"
            "is_valid INTEGER DEFAULT 1,"
            "UNIQUE(tier, scope, key))"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)"
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def remember(
        self,
        tier: str,
        scope: str,
        key: str,
        value: str,
        source_trace_id: str | None = None,
    ) -> str:
        """Store a memory (INSERT or UPDATE)."""
        now = datetime.utcnow()
        entry_id = str(uuid.uuid4())

        ttl_days = DEFAULT_TTL.get(tier, self._cfg.default_ttl_days)
        expires_at = (now + timedelta(days=ttl_days)) if ttl_days else None

        vals = (
            entry_id, tier, scope, key, value, source_trace_id,
            now.isoformat(), now.isoformat(),
            expires_at.isoformat() if expires_at else None,
        )

        try:
            conn = self._require_conn()
            conn.execute(
                "INSERT INTO memories (id, tier, scope, key, value, source_trace_id,"
                " created_at, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                vals,
            )
        except sqlite3.IntegrityError:
            conn = self._require_conn()
            conn.execute(
                "UPDATE memories SET value = ?, updated_at = ?, expires_at = ?,"
                " is_valid = 1 WHERE tier = ? AND scope = ? AND key = ?",
                (value, now.isoformat(),
                 expires_at.isoformat() if expires_at else None, tier, scope, key),
            )
            entry_id = f"updated:{tier}:{scope}:{key}"

        self._require_conn().commit()
        logger.debug(f"Remembered: {tier}/{scope}/{key}")
        return entry_id

    def recall(
        self,
        query: str | None = None,
        tier: str | None = None,
        scope: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Recall memories matching criteria."""
        sql = "SELECT * FROM memories WHERE is_valid = 1"
        params: list[Any] = []

        if tier:
            sql += " AND tier = ?"
            params.append(tier)
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if query:
            sql += " AND (key LIKE ? OR value LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        conn = self._require_conn()
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

        return [
            MemoryEntry(
                id=row["id"],
                tier=row["tier"],
                scope=row["scope"],
                key=row["key"],
                value=row["value"],
                confidence=row["confidence"],
                source_trace_id=row["source_trace_id"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
                is_valid=bool(row["is_valid"]),
            )
            for row in rows
        ]

    def forget(self, tier: str, scope: str, key: str) -> bool:
        """Soft-delete a memory."""
        conn = self._require_conn()
        cursor = conn.execute(
            "UPDATE memories SET is_valid = 0 WHERE tier = ? AND scope = ? AND key = ?",
            (tier, scope, key),
        )
        conn.commit()
        return cursor.rowcount > 0

    def cleanup_expired(self) -> int:
        """Remove expired memories. Returns count removed."""
        now = datetime.utcnow().isoformat()
        conn = self._require_conn()
        cursor = conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        conn.commit()
        return cursor.rowcount

    def count(self, tier: str | None = None) -> int:
        """Count memories."""
        conn = self._require_conn()
        if tier:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE tier = ? AND is_valid = 1",
                (tier,),
            )
        else:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE is_valid = 1"
            )
        return cursor.fetchone()[0]


class MemorySystem:
    """High-level memory interface."""

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self._store = MemoryStore(config)

    def close(self) -> None:
        self._store.close()

    def remember(
        self,
        fact: str,
        tier: str = "semantic",
        scope: str = "project",
    ) -> str:
        """Remember a fact."""
        return self._store.remember(tier, scope, fact, fact)

    def recall(
        self,
        query: str,
        tier: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Recall facts matching query."""
        entries = self._store.recall(query=query, tier=tier, limit=limit)
        return [e.value for e in entries]

    def get_skill(self, skill_name: str) -> str | None:
        """Get a procedural skill."""
        entries = self._store.recall(
            tier="procedural",
            scope="global",
            limit=1,
        )
        for e in entries:
            if skill_name in e.key:
                return e.value
        return None

    def add_skill(self, name: str, content: str) -> str:
        """Add a procedural skill."""
        return self._store.remember("procedural", "global", name, content)

    def cleanup(self) -> int:
        """Run cleanup tasks. Returns count of cleaned."""
        return self._store.cleanup_expired()
