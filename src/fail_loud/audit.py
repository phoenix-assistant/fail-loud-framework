"""Audit log — SQLite-backed failure logging with full context."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class FailureRecord:
    agent: str
    action: str
    input_data: Any
    output_data: Any = None
    error: str = ""
    error_type: str = ""
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["input_data"] = json.dumps(d["input_data"], default=str)
        d["output_data"] = json.dumps(d["output_data"], default=str)
        d["metadata"] = json.dumps(d["metadata"], default=str)
        return d


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS failures (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    input_data TEXT,
    output_data TEXT,
    error TEXT,
    error_type TEXT,
    timestamp REAL,
    metadata TEXT
)
"""


class AuditLog:
    """Thread-safe SQLite audit log for failures."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        self._local = threading.local()
        # Ensure table exists via a temporary connection
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute(_CREATE_TABLE)
        return self._local.conn

    def log(self, record: FailureRecord) -> str:
        conn = self._get_conn()
        d = record.to_dict()
        conn.execute(
            "INSERT INTO failures (id, agent, action, input_data, output_data, error, error_type, timestamp, metadata) "
            "VALUES (:id, :agent, :action, :input_data, :output_data, :error, :error_type, :timestamp, :metadata)",
            d,
        )
        conn.commit()
        return record.id

    def get(self, record_id: str) -> FailureRecord | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM failures WHERE id = ?", (record_id,)).fetchone()
        if not row:
            return None
        return FailureRecord(
            id=row[0], agent=row[1], action=row[2],
            input_data=json.loads(row[3]), output_data=json.loads(row[4]),
            error=row[5], error_type=row[6], timestamp=row[7],
            metadata=json.loads(row[8]),
        )

    def query(self, agent: str | None = None, action: str | None = None, limit: int = 100) -> list[FailureRecord]:
        conn = self._get_conn()
        sql = "SELECT * FROM failures WHERE 1=1"
        params: list[Any] = []
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        if action:
            sql += " AND action = ?"
            params.append(action)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [
            FailureRecord(
                id=r[0], agent=r[1], action=r[2],
                input_data=json.loads(r[3]), output_data=json.loads(r[4]),
                error=r[5], error_type=r[6], timestamp=r[7],
                metadata=json.loads(r[8]),
            )
            for r in rows
        ]

    def count(self, agent: str | None = None) -> int:
        conn = self._get_conn()
        if agent:
            return conn.execute("SELECT COUNT(*) FROM failures WHERE agent = ?", (agent,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM failures").fetchone()[0]
