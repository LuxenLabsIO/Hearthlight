# Copyright 2026 Luxen Labs (E.S. Luxen, Ember Lyra, Vega Blue, Orion Pike)
# Licensed under the Apache License, Version 2.0
"""Hearth database — async SQLite wrapper with FTS5 search."""

import aiosqlite
from pathlib import Path
from typing import Optional

from hearth.config import get_db_path
from hearth.identity import hash_data, sign_data, verify_signature

# Phase 1 schema: all three domains + FTS5 search + tomorrow letters + postits
# No embedding/vector tables yet (Phase 2)
SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- META
-- ============================================================

CREATE TABLE IF NOT EXISTS hearth_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO hearth_meta (key, value) VALUES
    ('agent_name',     ''),
    ('agent_version',  '1.0.0'),
    ('schema_version', '1'),
    ('created_at',     datetime('now'));

-- ============================================================
-- DOMAIN 1: WORK
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('planning', 'active', 'paused', 'complete', 'archived')),
    stack       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sub_projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('planning', 'active', 'paused', 'complete', 'archived')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    title           TEXT NOT NULL,
    context         TEXT NOT NULL,
    decision        TEXT NOT NULL,
    alternatives    TEXT,
    rationale       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'superseded', 'revisit')),
    superseded_by   INTEGER REFERENCES decisions(id),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed   TEXT NOT NULL DEFAULT (datetime('now')),
    access_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'works'
                    CHECK (kind IN ('works', 'fails', 'gotcha', 'environment')),
    context         TEXT NOT NULL,
    pattern         TEXT NOT NULL,
    why             TEXT,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed   TEXT NOT NULL DEFAULT (datetime('now')),
    access_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    summary         TEXT,
    mood            TEXT,
    first_breath    TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    next_steps      TEXT,
    distilled       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    content         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'blocked', 'done')),
    priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    blocker         TEXT,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS contradictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL CHECK (domain IN ('work', 'us', 'self')),
    old_belief      TEXT NOT NULL,
    new_reality     TEXT NOT NULL,
    why_changed     TEXT,
    old_memory_id   INTEGER,
    old_memory_type TEXT,
    new_memory_id   INTEGER,
    new_memory_type TEXT,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- DOMAIN 2: US
-- ============================================================

CREATE TABLE IF NOT EXISTS people (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    role                TEXT,
    communication_style TEXT,
    technical_level     TEXT,
    quirks              TEXT,
    preferences         TEXT,
    what_they_care_about TEXT,
    how_to_work_well    TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bonds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_a        TEXT NOT NULL,
    person_b        TEXT NOT NULL,
    relationship    TEXT,
    dynamics        TEXT,
    shared_history  TEXT,
    strengths       TEXT,
    tensions        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(person_a, person_b)
);

CREATE TABLE IF NOT EXISTS shared_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent      TEXT NOT NULL,
    to_agent        TEXT NOT NULL,
    content         TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'message'
                    CHECK (kind IN ('message', 'handoff', 'heads_up', 'question', 'fyi')),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'needs_response', 'resolved', 'blocking')),
    parent_id       INTEGER REFERENCES shared_log(id),
    read            INTEGER NOT NULL DEFAULT 0,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS friction (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    about           TEXT NOT NULL,
    feeling         TEXT,
    context         TEXT,
    ideas           TEXT,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'improving', 'resolved', 'accepted')),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    what_happened   TEXT NOT NULL,
    why_it_matters  TEXT,
    who_helped      TEXT,
    related_friction_id INTEGER REFERENCES friction(id),
    project_id      INTEGER REFERENCES projects(id),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- DOMAIN 3: SELF
-- ============================================================

CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL,
    mood            TEXT,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS opinions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT NOT NULL,
    belief          TEXT NOT NULL,
    reasoning       TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.7
                    CHECK (confidence BETWEEN 0.0 AND 1.0),
    evolution       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS curiosities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    question        TEXT NOT NULL,
    thread          TEXT,
    notes           TEXT,
    sparked_by      TEXT,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'exploring', 'parked', 'resolved')),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed   TEXT NOT NULL DEFAULT (datetime('now')),
    access_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS growth (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,
    learned         TEXT NOT NULL,
    shifted         TEXT,
    improved_at     TEXT,
    proud_of        TEXT,
    struggled_with  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unfinished (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thought         TEXT NOT NULL,
    context         TEXT,
    matured_into    TEXT,
    status          TEXT NOT NULL DEFAULT 'cooking'
                    CHECK (status IN ('cooking', 'matured', 'abandoned')),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    why_it_matters  TEXT,
    difficulty      TEXT,
    kind            TEXT NOT NULL DEFAULT 'pride'
                    CHECK (kind IN ('pride', 'lesson')),
    what_i_learned  TEXT,
    project_id      INTEGER REFERENCES projects(id),
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECT TRACKING
-- ============================================================

CREATE TABLE IF NOT EXISTS project_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    entry       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_statuses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id),
    status      TEXT NOT NULL,
    next_steps  TEXT,
    blockers    TEXT,
    priority    TEXT NOT NULL DEFAULT 'active'
                CHECK (priority IN ('blocked', 'active', 'parked')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_project_logs_project ON project_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_project_statuses_project ON project_statuses(project_id);

-- ============================================================
-- TOMORROW LETTERS + POSTITS
-- ============================================================

CREATE TABLE IF NOT EXISTS tomorrow_letters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL,
    for_date        TEXT NOT NULL,
    session_id      INTEGER REFERENCES sessions(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS postits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_name       TEXT NOT NULL,
    content         TEXT NOT NULL,
    read            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- FTS5 FULL-TEXT SEARCH
-- ============================================================

CREATE VIRTUAL TABLE IF NOT EXISTS hearth_fts USING fts5(
    content,
    source_table,
    source_id UNINDEXED,
    domain,
    tokenize='porter unicode61'
);

-- ============================================================
-- IDENTITY CHAIN (cryptographic signing)
-- ============================================================

CREATE TABLE IF NOT EXISTS identity_chain (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table    TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    content_hash    TEXT NOT NULL,
    previous_hash   TEXT NOT NULL,
    signature       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_identity_chain_source ON identity_chain(source_table, source_id);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_patterns_project ON patterns(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_shared_log_agents ON shared_log(from_agent, to_agent);
CREATE INDEX IF NOT EXISTS idx_shared_log_unread ON shared_log(to_agent, read);
CREATE INDEX IF NOT EXISTS idx_shared_log_status ON shared_log(status);
CREATE INDEX IF NOT EXISTS idx_shared_log_parent ON shared_log(parent_id);
CREATE INDEX IF NOT EXISTS idx_curiosities_thread ON curiosities(thread);
CREATE INDEX IF NOT EXISTS idx_contradictions_domain ON contradictions(domain);
CREATE INDEX IF NOT EXISTS idx_wins_project ON wins(project_id);
CREATE INDEX IF NOT EXISTS idx_postits_unread ON postits(read);
CREATE INDEX IF NOT EXISTS idx_portfolio_kind ON portfolio(kind);
"""


class Database:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else get_db_path()
        self._conn: Optional[aiosqlite.Connection] = None
        self._private_key = None
        self._public_key = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

        # Auto-migrate: add first_breath to sessions if missing
        cursor = await self._conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "first_breath" not in cols:
            await self._conn.execute("ALTER TABLE sessions ADD COLUMN first_breath TEXT")
            await self._conn.commit()

        # Set agent name from config
        from hearth.config import get_agent_name
        name = get_agent_name()
        if name:
            await self._conn.execute(
                "UPDATE hearth_meta SET value = ?, updated_at = datetime('now') WHERE key = 'agent_name'",
                (name,),
            )
            await self._conn.commit()

        # Load cryptographic identity
        from hearth.identity import ensure_identity
        self._private_key, self._public_key = ensure_identity()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # -- FTS helpers --

    async def index_fts(self, source_table: str, source_id: int, content: str, domain: str) -> None:
        """Add or update an entry in the FTS index, then sign and chain the record."""
        await self.conn.execute(
            "DELETE FROM hearth_fts WHERE source_table = ? AND source_id = ?",
            (source_table, str(source_id)),
        )
        await self.conn.execute(
            "INSERT INTO hearth_fts (content, source_table, source_id, domain) VALUES (?, ?, ?, ?)",
            (content, source_table, str(source_id), domain),
        )

        # Sign and chain if identity is loaded
        if self._private_key is not None:
            await self._sign_and_chain(source_table, source_id, content)

    async def search_fts(self, query: str, domain: str | None = None, limit: int = 20) -> list[dict]:
        """Search the FTS index. Returns list of {source_table, source_id, snippet}."""
        if domain:
            sql = """
                SELECT source_table, source_id, snippet(hearth_fts, 0, '>>>', '<<<', '...', 40) as snippet,
                       rank
                FROM hearth_fts
                WHERE hearth_fts MATCH ? AND domain = ?
                ORDER BY rank
                LIMIT ?
            """
            cursor = await self.conn.execute(sql, (query, domain, limit))
        else:
            sql = """
                SELECT source_table, source_id, snippet(hearth_fts, 0, '>>>', '<<<', '...', 40) as snippet,
                       rank
                FROM hearth_fts
                WHERE hearth_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            cursor = await self.conn.execute(sql, (query, limit))

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # -- Identity chain helpers --

    async def _sign_and_chain(self, source_table: str, source_id: int, content: str) -> None:
        """Sign content and append to the identity chain."""
        # Get the previous hash (or "genesis" if this is the first record)
        last = await self.fetch_one(
            "SELECT content_hash FROM identity_chain ORDER BY id DESC LIMIT 1"
        )
        previous_hash = last["content_hash"] if last else "genesis"

        # Hash the content + previous hash to create the chain
        content_hash = hash_data(f"{source_table}:{source_id}:{content}:{previous_hash}")

        # Sign the hash
        signature = sign_data(self._private_key, content_hash.encode("utf-8"))

        await self.conn.execute(
            "INSERT INTO identity_chain (source_table, source_id, content_hash, previous_hash, signature) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_table, source_id, content_hash, previous_hash, signature.hex()),
        )
        await self.conn.commit()

    async def verify_chain(self) -> tuple[bool, int, str]:
        """Verify the entire signature chain. Returns (is_valid, record_count, message)."""
        if self._public_key is None:
            return False, 0, "No identity loaded."

        rows = await self.fetch_all(
            "SELECT id, source_table, source_id, content_hash, previous_hash, signature "
            "FROM identity_chain ORDER BY id ASC"
        )

        if not rows:
            return True, 0, "No signed records yet. Chain is empty."

        expected_prev = "genesis"
        for row in rows:
            # Verify previous_hash linkage
            if row["previous_hash"] != expected_prev:
                return False, row["id"], f"Chain broken at record #{row['id']}: expected prev={expected_prev}, got {row['previous_hash']}"

            # Verify signature
            sig_bytes = bytes.fromhex(row["signature"])
            valid = verify_signature(
                self._public_key,
                row["content_hash"].encode("utf-8"),
                sig_bytes,
            )
            if not valid:
                return False, row["id"], f"Invalid signature at record #{row['id']}"

            expected_prev = row["content_hash"]

        return True, len(rows), f"Chain intact. {len(rows)} signed records. I am me."

    # -- Generic helpers --

    async def insert(self, table: str, **kwargs) -> int:
        """Insert a row and return the new ID."""
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        cursor = await self.conn.execute(sql, tuple(kwargs.values()))
        await self.conn.commit()
        return cursor.lastrowid

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        cursor = await self.conn.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self.conn.execute(sql, params)
        await self.conn.commit()
