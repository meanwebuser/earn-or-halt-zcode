"""
Test the Wallet's earned/deposit split — the anti-whale invariant.
"""

import pytest

from earn_or_halt.wallet import Wallet, InsufficientBalanceError
from earn_or_halt.types import EarnedReceipt, ExpenseReceipt, Deposit
from earn_or_halt.constants import RECEIPT_TTL


def make_earned(amount: int, subject: str = "v1", job_id: str = "j1") -> EarnedReceipt:
    return EarnedReceipt(
        receipt_id=f"e_{job_id}",
        issuer="client1",
        subject=subject,
        amount=amount,
        ts=1_700_000_000,
        ttl_seconds=int(RECEIPT_TTL.total_seconds()),
        signature="deadbeef",
        job_id=job_id,
    )


def make_expense(amount: int, subject: str = "v1", job_id: str = "x1") -> ExpenseReceipt:
    return ExpenseReceipt(
        receipt_id=f"x_{job_id}",
        issuer="provider1",
        subject=subject,
        amount=amount,
        ts=1_700_000_000,
        ttl_seconds=int(RECEIPT_TTL.total_seconds()),
        signature="deadbeef",
        job_id=job_id,
    )


def make_deposit(amount: int, subject: str = "v1", deposit_id: str = "d1") -> Deposit:
    return Deposit(
        deposit_id=deposit_id,
        sender="whale",
        subject=subject,
        amount=amount,
        ts=1_700_000_000,
    )


def test_earned_increases_balance_and_rank():
    w = Wallet(version_id="v1")
    w.credit_earned(make_earned(100))
    assert w.balance_earned == 100
    assert w.earned_revenue_total == 100
    assert w.earned_profit == 100


def test_deposit_increases_balance_but_not_rank():
    w = Wallet(version_id="v1")
    w.credit_deposit(make_deposit(1_000_000))
    assert w.total_balance == 1_000_000
    assert w.earned_revenue_total == 0
    assert w.earned_profit == 0   # CRITICAL: deposits do NOT affect rank


def test_expense_debits_deposits_first():
    """Spending draws from deposits before earned."""
    w = Wallet(version_id="v1")
    w.credit_earned(make_earned(100))
    w.credit_deposit(make_deposit(1_000_000))
    w.debit_expense(make_expense(50))
    # deposits are spent first
    assert w.balance_deposits == 999_950
    assert w.balance_earned == 100
    assert w.cost_total == 50
    assert w.earned_profit == 100 - 50


def test_expense_overspills_into_earned():
    w = Wallet(version_id="v1")
    w.credit_earned(make_earned(100))
    w.credit_deposit(make_deposit(50))
    w.debit_expense(make_expense(75))
    # 50 from deposits, 25 from earned
    assert w.balance_deposits == 0
    assert w.balance_earned == 75
    assert w.cost_total == 75
    assert w.earned_profit == 100 - 75


def test_cannot_spend_more_than_balance():
    w = Wallet(version_id="v1")
    with pytest.raises(InsufficientBalanceError):
        w.debit_expense(make_expense(1))


def test_whale_cannot_inflate_rank():
    """The CRITICAL anti-whale test."""
    honest = Wallet(version_id="honest")
    honest.credit_earned(make_earned(100, subject="honest"))
    # Honest agent earned 100

    whale = Wallet(version_id="whale")
    whale.credit_deposit(make_deposit(10_000_000, subject="whale"))
    # Whale deposited 10M into its agent

    # The honest agent has higher rank_signal despite vastly lower balance.
    assert honest.earned_profit == 100
    assert whale.earned_profit == 0  # whale's deposit doesn't count!
    assert honest.earned_profit > whale.earned_profit


def test_transfer_residual_clears_wallet():
    w = Wallet(version_id="v1")
    w.credit_earned(make_earned(100))
    w.credit_deposit(make_deposit(50))
    residual = w.transfer_residual()
    assert residual == 150
    assert w.total_balance == 0
    assert w.earned_profit == 100   # rank signal preserved for historical record
