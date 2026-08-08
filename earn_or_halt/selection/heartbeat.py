"""
Heartbeat sender and reader.

Each live version publishes a Heartbeat every HEARTBEAT_PERIOD. The
heartbeat contains:

- version_id, code_hash
- ts (current time)
- earned_revenue, cost, balance (current wallet snapshot)
- rank_signal (computed locally; verified by readers against their
  own recomputation)
- receipt_ids_since_last (list of new receipts since previous HB)

Heartbeats are signed by the version's runtime key (NOT the release
key — those are different keys, see INSIDE.md §Key separation).

If a heartbeat is missing for >HALT_TIMEOUT, other versions mark the
silent version as `halted` and stop routing work to it.
"""

from __future__ import annotations

import time
from typing import Optional

from ..types import Heartbeat, Version
from ..wallet import Wallet
from ..constants import HEARTBEAT_PERIOD, HALT_TIMEOUT


class HeartbeatSender:
    """Build and sign heartbeats from a Wallet snapshot."""

    def __init__(self, runtime_secret: bytes) -> None:
        # NOTE: replace with real ecdsa.SigningKey in production.
        self._secret = runtime_secret

    def build(
        self,
        version: Version,
        wallet: "Wallet",
        receipt_ids_since_last: list[str],
        now_ts: Optional[int] = None,
    ) -> Heartbeat:
        from ..providers.base import Provider  # for the mock sign helper
        ts = now_ts if now_ts is not None else int(time.time())
        hb = Heartbeat(
            version=version, ts=ts,
            earned_revenue=wallet.earned_revenue_total,
            cost=wallet.cost_total,
            balance=wallet.total_balance,
            rank_signal=float(wallet.earned_profit),
            receipt_ids_since_last=list(receipt_ids_since_last),
        )
        hb.signature = Provider.sign(hb.canonical_bytes(), self._secret)
        return hb


class HeartbeatReader:
    """Track heartbeats from all known versions."""

    def __init__(self) -> None:
        # version_id -> latest Heartbeat
        self._latest: dict[str, Heartbeat] = {}

    def ingest(self, hb: Heartbeat) -> None:
        prev = self._latest.get(hb.version.version_id)
        if prev is None or hb.ts > prev.ts:
            self._latest[hb.version.version_id] = hb

    def is_alive(self, version_id: str, now_ts: Optional[int] = None) -> bool:
        now = now_ts if now_ts is not None else int(time.time())
        hb = self._latest.get(version_id)
        if hb is None:
            return False
        return (now - hb.ts) < int(HALT_TIMEOUT.total_seconds())

    def latest(self, version_id: str) -> Optional[Heartbeat]:
        return self._latest.get(version_id)

    def all_latest(self) -> list[Heartbeat]:
        return list(self._latest.values())
