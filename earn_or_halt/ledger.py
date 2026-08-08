"""
SQLite ledger.

Append-only audit log of every receipt and deposit the wallet has ever
seen. The ledger is the source of truth for `earned_profit` recomputa-
tion: any third party with read access to the SQLite file (or its
mirrored on-chain anchor) can recompute the agent's state from scratch
and verify it matches the wallet's claimed state.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .types import Deposit, EarnedReceipt, ExpenseReceipt, Receipt, Version
from .constants import LEDGER_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id   TEXT PRIMARY KEY,
    issuer       TEXT NOT NULL,
    subject      TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    ts           INTEGER NOT NULL,
    ttl_seconds  INTEGER NOT NULL,
    signature    TEXT NOT NULL,
    job_id       TEXT NOT NULL,
    kind         TEXT NOT NULL,           -- 'earned' or 'expense'
    canonical_hash TEXT NOT NULL,
    ingested_ts  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deposits (
    deposit_id TEXT PRIMARY KEY,
    sender     TEXT NOT NULL,
    subject    TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    note       TEXT,
    ingested_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS versions_seen (
    version_id  TEXT PRIMARY KEY,
    code_hash   TEXT NOT NULL,
    first_seen  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_subject_ts
    ON receipts(subject, ts);

CREATE INDEX IF NOT EXISTS idx_receipts_issuer_job
    ON receipts(issuer, job_id);
"""


class Ledger:
    """Append-only SQLite ledger."""

    def __init__(self, path: str | Path = LEDGER_PATH) -> None:
        self.path = str(path)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Writes ─────────────────────────────────────────────────────────

    def ingest_receipt(self, r: Receipt) -> bool:
        """
        Insert a receipt. Returns True if inserted, False if duplicate
        (by receipt_id). Duplicates are silently dropped: idempotent
        ingest is the foundation of no-double-count.
        """
        with self._conn() as c:
            try:
                c.execute(
                    """INSERT INTO receipts
                       (receipt_id, issuer, subject, amount, ts, ttl_seconds,
                        signature, job_id, kind, canonical_hash, ingested_ts)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r.receipt_id, r.issuer, r.subject, r.amount, r.ts,
                        r.ttl_seconds, r.signature, r.job_id, r.kind,
                        r.canonical_hash(), int(time.time()),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def ingest_deposit(self, d: Deposit) -> bool:
        with self._conn() as c:
            try:
                c.execute(
                    """INSERT INTO deposits
                       (deposit_id, sender, subject, amount, ts, note, ingested_ts)
                       VALUES (?,?,?,?,?,?,?)""",
                    (d.deposit_id, d.sender, d.subject, d.amount, d.ts,
                     d.note, int(time.time())),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def record_version(self, v: Version) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO versions_seen
                   (version_id, code_hash, first_seen) VALUES (?,?,?)""",
                (v.version_id, v.code_hash, int(time.time())),
            )

    # ── Reads ─────────────────────────────────────────────────────────

    def receipts_for(
        self,
        version_id: str,
        kind: Optional[str] = None,
        since_ts: Optional[int] = None,
    ) -> list[Receipt]:
        """All receipts for a version, optionally filtered by kind/since."""
        q = "SELECT * FROM receipts WHERE subject = ?"
        params: list = [version_id]
        if kind:
            q += " AND kind = ?"
            params.append(kind)
        if since_ts is not None:
            q += " AND ts >= ?"
            params.append(since_ts)
        q += " ORDER BY ts ASC"

        with self._conn() as c:
            rows = c.execute(q, params).fetchall()

        out: list[Receipt] = []
        for row in rows:
            if row["kind"] == "earned":
                out.append(EarnedReceipt(
                    receipt_id=row["receipt_id"], issuer=row["issuer"],
                    subject=row["subject"], amount=row["amount"],
                    ts=row["ts"], ttl_seconds=row["ttl_seconds"],
                    signature=row["signature"], job_id=row["job_id"],
                ))
            else:
                out.append(ExpenseReceipt(
                    receipt_id=row["receipt_id"], issuer=row["issuer"],
                    subject=row["subject"], amount=row["amount"],
                    ts=row["ts"], ttl_seconds=row["ttl_seconds"],
                    signature=row["signature"], job_id=row["job_id"],
                ))
        return out

    def has_receipt(self, issuer: str, job_id: str) -> bool:
        """Double-count check: same (issuer, job_id) cannot appear twice."""
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM receipts WHERE issuer = ? AND job_id = ? LIMIT 1",
                (issuer, job_id),
            ).fetchone()
        return row is not None

    def all_versions(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM versions_seen"
            ).fetchall()]
