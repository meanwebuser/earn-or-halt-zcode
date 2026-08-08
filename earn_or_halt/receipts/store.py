"""
Receipt store — thin wrapper around the Ledger for receipt queries.

The Ledger is append-only; this module adds higher-level queries:
- compute_earned_profit(version_id, since_ts)
- list_receipts_in_window(version_id, window_seconds)
- receipt_count_by_issuer
"""

from __future__ import annotations

import time
from typing import Optional

from ..ledger import Ledger
from ..types import Receipt


class ReceiptStore:
    """Query layer over Ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def earned_revenue(
        self, version_id: str, since_ts: Optional[int] = None
    ) -> int:
        """Sum of EarnedReceipt amounts."""
        return sum(
            r.amount for r in self.ledger.receipts_for(
                version_id, kind="earned", since_ts=since_ts
            )
        )

    def cost(self, version_id: str, since_ts: Optional[int] = None) -> int:
        """Sum of ExpenseReceipt amounts."""
        return sum(
            r.amount for r in self.ledger.receipts_for(
                version_id, kind="expense", since_ts=since_ts
            )
        )

    def earned_profit(
        self, version_id: str, since_ts: Optional[int] = None
    ) -> int:
        """rank_signal input."""
        return self.earned_revenue(version_id, since_ts) - self.cost(version_id, since_ts)

    def last_earned_ts(self, version_id: str) -> int:
        """Timestamp of the most recent EarnedReceipt, or 0 if none."""
        rs = self.ledger.receipts_for(version_id, kind="earned")
        return max((r.ts for r in rs), default=0)

    def receipts_in_window(
        self, version_id: str, window_seconds: int
    ) -> list[Receipt]:
        cutoff = int(time.time()) - window_seconds
        return self.ledger.receipts_for(version_id, since_ts=cutoff)
