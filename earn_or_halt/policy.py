"""
Economic policy.

Decides, before every paid action, whether the agent can afford it
and whether the next cycle is still worth running. Returns halt
decisions when not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .types import HaltReason, HaltRecord, Version
from .wallet import Wallet, InsufficientBalanceError
from .constants import SURVIVAL_WINDOW, HALT_TIMEOUT


@dataclass
class PolicyDecision:
    """Outcome of a single policy check."""

    allow: bool
    reason: str
    halt: Optional[HaltRecord] = None


class EconomicPolicy:
    """Stateless decisions over a Wallet snapshot."""

    def can_afford(self, wallet: Wallet, next_cost: int) -> PolicyDecision:
        """Check whether the next paid action is affordable."""
        if next_cost <= 0:
            return PolicyDecision(allow=True, reason="zero cost")
        if wallet.total_balance < next_cost:
            return PolicyDecision(
                allow=False,
                reason=f"balance {wallet.total_balance} < next_cost {next_cost}",
            )
        return PolicyDecision(allow=True, reason="ok")

    def should_halt(
        self,
        version: Version,
        wallet: Wallet,
        last_positive_earned_ts: int,
        now_ts: Optional[int] = None,
    ) -> PolicyDecision:
        """
        Decide whether to halt.

        Conditions (any one triggers halt):

        - INSUFFICIENT_BALANCE: balance < 1 unit AND earned_profit <= 0
          (we are out of money AND not earning).
        - NEGATIVE_MARGIN: cumulative cost > cumulative earned_revenue
          AND balance < some threshold of next operational cost.
        - OUTSIDE_TOP_TIMEOUT: last_positive_earned_ts older than
          HALT_TIMEOUT. (This is checked even though selection logic
          also enforces it, because the agent should self-halt before
          being ejected — preserves dignity.)
        """
        now = now_ts if now_ts is not None else int(time.time())

        # 1. No money and not earning
        if wallet.total_balance <= 0 and wallet.earned_profit <= 0:
            return PolicyDecision(
                allow=False,
                reason="balance=0 and earned_profit<=0",
                halt=HaltRecord(
                    version=version, ts=now,
                    reason=HaltReason.INSUFFICIENT_BALANCE,
                    final_balance=0,
                ),
            )

        # 2. Sustained negative margin with low runway
        if (
            wallet.earned_profit < 0
            and wallet.total_balance < abs(wallet.earned_profit)
        ):
            return PolicyDecision(
                allow=False,
                reason=f"negative margin {wallet.earned_profit} exceeds runway",
                halt=HaltRecord(
                    version=version, ts=now,
                    reason=HaltReason.NEGATIVE_MARGIN,
                    final_balance=wallet.total_balance,
                ),
            )

        # 3. Halt timeout
        if now - last_positive_earned_ts > int(HALT_TIMEOUT.total_seconds()):
            return PolicyDecision(
                allow=False,
                reason=f"no positive earned for >{HALT_TIMEOUT}",
                halt=HaltRecord(
                    version=version, ts=now,
                    reason=HaltReason.OUTSIDE_TOP_TIMEOUT,
                    final_balance=wallet.total_balance,
                ),
            )

        return PolicyDecision(allow=True, reason="ok")
