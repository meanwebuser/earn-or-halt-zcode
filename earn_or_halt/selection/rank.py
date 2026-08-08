"""
Ranking computation.

The rank_signal is computed from the wallet's earned_profit over the
last SURVIVAL_WINDOW. Hardcoded N=3 routing: the top-3 versions by
rank_signal get all new incoming work routed to them.

CRITICAL INVARIANT (I1 in PROOFS.md):

    rank_signal(V) = f(earned_profit(V))

NO function of `deposits` enters this computation. A whale that
deposits $1M into version V's wallet does not move V up the ranking.
This is the sole anti-whale defense; all other mechanics (top-N,
heartbeat, timeout) are second-order.

Emergent survival: every version with positive earned_profit in the
last window stays alive. N=3 only decides who gets new work; it does
not decide who dies. Death is decided by HALT_TIMEOUT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from ..types import Version
from ..constants import N_TOP, SURVIVAL_WINDOW
from ..receipts.store import ReceiptStore


@dataclass(frozen=True)
class RankEntry:
    """Single entry in the ranking table."""

    version: Version
    rank_signal: float       # = earned_profit over the window
    earned_revenue: int
    cost: int
    balance: int
    rank: int                # 1-indexed; 0 if outside top
    alive: bool              # positive earned_profit in window


class Ranker:
    """Compute the global ranking across all known versions."""

    def __init__(self, store: ReceiptStore) -> None:
        self.store = store

    def rank(
        self,
        versions: Iterable[Version],
        wallet_balances: dict[str, int],   # version_id -> balance
        now_ts: int | None = None,
    ) -> list[RankEntry]:
        now = now_ts if now_ts is not None else int(time.time())
        window_s = int(SURVIVAL_WINDOW.total_seconds())
        since = now - window_s

        rows: list[RankEntry] = []
        for v in versions:
            earned = self.store.earned_revenue(v.version_id, since_ts=since)
            cost = self.store.cost(v.version_id, since_ts=since)
            profit = earned - cost
            balance = wallet_balances.get(v.version_id, 0)
            rows.append(RankEntry(
                version=v,
                rank_signal=float(profit),
                earned_revenue=earned,
                cost=cost,
                balance=balance,
                rank=0,
                alive=profit > 0,
            ))

        # Sort by rank_signal descending
        rows.sort(key=lambda r: r.rank_signal, reverse=True)

        # Assign rank: 1..N_TOP, 0 for the rest
        for i, r in enumerate(rows[:N_TOP], start=1):
            rows[i - 1] = RankEntry(
                version=r.version, rank_signal=r.rank_signal,
                earned_revenue=r.earned_revenue, cost=r.cost,
                balance=r.balance, rank=i, alive=r.alive,
            )

        return rows

    @staticmethod
    def top_n(rows: list[RankEntry]) -> list[RankEntry]:
        """Return only the top-N entries (rank >= 1)."""
        return [r for r in rows if r.rank >= 1]

    @staticmethod
    def alive_versions(rows: list[RankEntry]) -> list[RankEntry]:
        """All versions with positive earned_profit in the window,
        regardless of rank. This is the 'emergent biodiversity' set."""
        return [r for r in rows if r.alive]
