"""Human review queue — SQLite-backed queue for low-confidence or ambiguous outputs."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal


@dataclass
class ReviewItem:
    agent: str
    action: str
    input_data: Any
    output_data: Any
    reason: str
    confidence: float | None = None
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer_notes: str = ""
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    input_data TEXT,
    output_data TEXT,
    reason TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',
    reviewer_notes TEXT DEFAULT '',
    created_at REAL,
    resolved_at REAL
)
"""


class HumanReviewQueue:
    """Thread-safe SQLite-backed human review queue."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        self._local = threading.local()
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.execute(_CREATE_TABLE)
        return self._local.conn

    def submit(self, item: ReviewItem) -> str:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO review_queue (id, agent, action, input_data, output_data, reason, confidence, status, reviewer_notes, created_at, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.agent, item.action, json.dumps(item.input_data, default=str),
             json.dumps(item.output_data, default=str), item.reason, item.confidence,
             item.status, item.reviewer_notes, item.created_at, item.resolved_at),
        )
        conn.commit()
        return item.id

    def pending(self, limit: int = 50) -> list[ReviewItem]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM review_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def resolve(self, item_id: str, status: Literal["approved", "rejected"], notes: str = "") -> bool:
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE review_queue SET status = ?, reviewer_notes = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (status, notes, time.time(), item_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def get(self, item_id: str) -> ReviewItem | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def count_pending(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM review_queue WHERE status = 'pending'").fetchone()[0]

    @staticmethod
    def _row_to_item(row) -> ReviewItem:
        return ReviewItem(
            id=row[0], agent=row[1], action=row[2],
            input_data=json.loads(row[3]), output_data=json.loads(row[4]),
            reason=row[5], confidence=row[6], status=row[7],
            reviewer_notes=row[8], created_at=row[9], resolved_at=row[10],
        )
