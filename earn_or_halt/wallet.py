"""
Wallet accounting.

Two buckets, NEVER mixed:

- balance_earned:   sum of EarnedReceipt.amount  (counts toward rank)
- balance_deposits: sum of Deposit.amount       (does NOT count)

When the agent spends money, it draws from `balance_deposits` first
(this is the whale's money, spend it before touching earned revenue).
This makes whale-funding strictly worse than earned funding: a whale-
funded version runs out of operational runway without climbing the
ranking, while an earned-funded version climbs and keeps runway.

The `total_balance` is the sum of both buckets and is what `can_afford`
checks against. The `rank_signal` only sees `earned_revenue - cost`,
where `cost` is the sum of ExpenseReceipts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .types import Deposit, EarnedReceipt, ExpenseReceipt


@dataclass
class Wallet:
    """Local wallet state for a single version."""

    version_id: str
    balance_earned: int = 0      # from EarnedReceipts, minus spent earned
    balance_deposits: int = 0    # from Deposits, minus spent deposits
    earned_revenue_total: int = 0  # cumulative Σ EarnedReceipt.amount
    cost_total: int = 0           # cumulative Σ ExpenseReceipt.amount

    @property
    def total_balance(self) -> int:
        return self.balance_earned + self.balance_deposits

    @property
    def earned_profit(self) -> int:
        """The ONLY signal that enters rank_signal."""
        return self.earned_revenue_total - self.cost_total

    # ── Mutators ──────────────────────────────────────────────────────

    def credit_earned(self, r: EarnedReceipt) -> None:
        if r.subject != self.version_id:
            raise ValueError(
                f"EarnedReceipt for {r.subject} credited to {self.version_id}"
            )
        self.balance_earned += r.amount
        self.earned_revenue_total += r.amount

    def credit_deposit(self, d: Deposit) -> None:
        if d.subject != self.version_id:
            raise ValueError(
                f"Deposit for {d.subject} credited to {self.version_id}"
            )
        self.balance_deposits += d.amount

    def debit_expense(self, r: ExpenseReceipt) -> None:
        if r.subject != self.version_id:
            raise ValueError(
                f"ExpenseReceipt for {r.subject} debited from {self.version_id}"
            )
        if r.amount > self.total_balance:
            raise InsufficientBalanceError(
                f"cannot spend {r.amount} with balance {self.total_balance}"
            )

        # Spend from deposits first (whale money), then from earned.
        # This is the anti-whale mechanic: spending whale money does
        # not preserve earned runway.
        from_deposit = min(self.balance_deposits, r.amount)
        from_earned = r.amount - from_deposit
        self.balance_deposits -= from_deposit
        self.balance_earned -= from_earned
        self.cost_total += r.amount

    def transfer_residual(self, destination: str = "commons_pool") -> int:
        """Move all residual balance out. Used at halt."""
        residual = self.total_balance
        self.balance_earned = 0
        self.balance_deposits = 0
        return residual


class InsufficientBalanceError(Exception):
    """Raised when an agent attempts to spend more than its balance."""
