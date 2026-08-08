"""
Test the economic cycle: wallet, ledger, policy, providers.
"""

import time

import pytest

from earn_or_halt.wallet import Wallet, InsufficientBalanceError
from earn_or_halt.ledger import Ledger
from earn_or_halt.policy import EconomicPolicy
from earn_or_halt.providers import MockLLMProvider, MockComputeProvider
from earn_or_halt.receipts.verify import ReceiptVerifier
from earn_or_halt.receipts.store import ReceiptStore
from earn_or_halt.types import (
    EarnedReceipt, ExpenseReceipt, Version, HaltReason,
)
from earn_or_halt.constants import RECEIPT_TTL, HALT_TIMEOUT


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "test.db"))


@pytest.fixture
def version():
    return Version(
        version_id="v_test",
        code_hash="a" * 64,
        release_sig="b" * 64,
        release_pubkey="c" * 64,
    )


def test_llm_provider_quote_and_execute():
    p = MockLLMProvider(secret=b"test_secret_32_bytes_long__________")
    q = p.quote(subject="v1", job_id="job1", description="hello", max_tokens=1000)
    assert q.amount > 0
    assert q.issuer == "mock_llm_v1"

    result, receipt = p.execute(q)
    assert result  # non-empty
    assert receipt.kind == "expense"
    assert receipt.amount == q.amount
    assert receipt.issuer == q.issuer
    assert receipt.subject == q.subject
    assert receipt.job_id == q.job_id


def test_compute_provider_quote_and_execute():
    p = MockComputeProvider(secret=b"test_secret_32_bytes_long__________")
    q = p.quote(subject="v1", job_id="job1", description="run task", estimated_ms=10000)
    assert q.amount > 0

    result, receipt = p.execute(q)
    assert result
    assert receipt.kind == "expense"


def test_policy_can_afford_zero_cost():
    w = Wallet(version_id="v1")
    p = EconomicPolicy()
    d = p.can_afford(w, 0)
    assert d.allow


def test_policy_cannot_afford_insufficient_balance():
    w = Wallet(version_id="v1")
    p = EconomicPolicy()
    d = p.can_afford(w, 100)
    assert not d.allow


def test_policy_should_halt_when_balance_zero_and_no_earnings(version):
    w = Wallet(version_id="v_test")
    p = EconomicPolicy()
    d = p.should_halt(version, w, last_positive_earned_ts=int(time.time()))
    assert d.halt is not None
    assert d.halt.reason == HaltReason.INSUFFICIENT_BALANCE


def test_policy_should_halt_on_sustained_negative_margin(version):
    w = Wallet(version_id="v_test")
    # Simulate: spent 200 earned 100 (negative margin of -100)
    # but still have balance (e.g. from deposits)
    w.earned_revenue_total = 100
    w.cost_total = 200
    w.balance_earned = 0
    w.balance_deposits = 50
    p = EconomicPolicy()
    d = p.should_halt(version, w, last_positive_earned_ts=int(time.time()))
    assert d.halt is not None
    assert d.halt.reason == HaltReason.NEGATIVE_MARGIN


def test_policy_should_halt_on_timeout(version):
    w = Wallet(version_id="v_test")
    w.earned_revenue_total = 100
    w.cost_total = 0
    w.balance_earned = 100

    # last positive earned was 31 days ago
    old_ts = int(time.time()) - int(HALT_TIMEOUT.total_seconds()) - 1
    p = EconomicPolicy()
    d = p.should_halt(version, w, last_positive_earned_ts=old_ts)
    assert d.halt is not None
    assert d.halt.reason == HaltReason.OUTSIDE_TOP_TIMEOUT


def test_policy_allows_when_healthy(version):
    w = Wallet(version_id="v_test")
    w.earned_revenue_total = 1000
    w.cost_total = 500
    w.balance_earned = 500

    p = EconomicPolicy()
    d = p.should_halt(version, w, last_positive_earned_ts=int(time.time()))
    assert d.halt is None


def test_ledger_idempotent_ingest(ledger):
    """Double-ingest of the same receipt_id must not duplicate."""
    r = EarnedReceipt(
        receipt_id="e_test_dup",
        issuer="client1", subject="v1", amount=100,
        ts=int(time.time()),
        ttl_seconds=int(RECEIPT_TTL.total_seconds()),
        signature="deadbeef", job_id="j1",
    )
    assert ledger.ingest_receipt(r) is True
    assert ledger.ingest_receipt(r) is False  # duplicate


def test_receipt_store_aggregates(ledger):
    store = ReceiptStore(ledger)

    # Earned 100 + 200 = 300
    for i, amt in enumerate([100, 200]):
        r = EarnedReceipt(
            receipt_id=f"e_{i}",
            issuer="client1", subject="v1", amount=amt,
            ts=int(time.time()), ttl_seconds=int(RECEIPT_TTL.total_seconds()),
            signature="deadbeef", job_id=f"j_{i}",
        )
        ledger.ingest_receipt(r)

    # Expense 50 + 75 = 125
    for i, amt in enumerate([50, 75]):
        r = ExpenseReceipt(
            receipt_id=f"x_{i}",
            issuer="provider1", subject="v1", amount=amt,
            ts=int(time.time()), ttl_seconds=int(RECEIPT_TTL.total_seconds()),
            signature="deadbeef", job_id=f"px_{i}",
        )
        ledger.ingest_receipt(r)

    assert store.earned_revenue("v1") == 300
    assert store.cost("v1") == 125
    assert store.earned_profit("v1") == 175
