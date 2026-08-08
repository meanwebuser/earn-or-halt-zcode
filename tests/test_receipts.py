"""
Test the receipt verifier: expiry, whitelist, double-count, amount sanity.
"""

import time

import pytest

from earn_or_halt.types import EarnedReceipt, ExpenseReceipt
from earn_or_halt.ledger import Ledger
from earn_or_halt.receipts.verify import ReceiptVerifier
from earn_or_halt.constants import RECEIPT_TTL


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "test.db"))


@pytest.fixture
def verifier(ledger):
    return ReceiptVerifier(
        ledger=ledger,
        provider_whitelist={"provider1"},
        client_whitelist={"client1"},
    )


def make_earned(amount=100, issuer="client1", subject="v1", job_id="j1",
                ts=None, ttl=None, sig="deadbeef"):
    return EarnedReceipt(
        receipt_id=f"e_{issuer}_{job_id}",
        issuer=issuer, subject=subject, amount=amount,
        ts=ts or int(time.time()),
        ttl_seconds=ttl or int(RECEIPT_TTL.total_seconds()),
        signature=sig, job_id=job_id,
    )


def make_expense(amount=100, issuer="provider1", subject="v1", job_id="x1",
                 ts=None, ttl=None, sig="deadbeef"):
    return ExpenseReceipt(
        receipt_id=f"x_{issuer}_{job_id}",
        issuer=issuer, subject=subject, amount=amount,
        ts=ts or int(time.time()),
        ttl_seconds=ttl or int(RECEIPT_TTL.total_seconds()),
        signature=sig, job_id=job_id,
    )


def test_valid_earned_receipt(verifier):
    r = make_earned()
    ok, _ = verifier.verify(r)
    assert ok


def test_expired_receipt_rejected(verifier):
    r = make_earned(ts=int(time.time()) - int(RECEIPT_TTL.total_seconds()) - 1)
    ok, reason = verifier.verify(r)
    assert not ok
    assert reason == "expired"


def test_zero_amount_rejected(verifier):
    r = make_earned(amount=0)
    ok, reason = verifier.verify(r)
    assert not ok
    assert "amount" in reason


def test_non_whitelisted_client_rejected(verifier):
    r = make_earned(issuer="unknown_client")
    ok, reason = verifier.verify(r)
    assert not ok
    assert "not whitelisted" in reason


def test_non_whitelisted_provider_rejected(verifier):
    r = make_expense(issuer="unknown_provider")
    ok, reason = verifier.verify(r)
    assert not ok
    assert "not whitelisted" in reason


def test_double_count_rejected(verifier):
    r = make_earned(job_id="dup1")
    ok1, _ = verifier.verify_and_store(r)
    assert ok1

    # Same issuer + job_id, different receipt_id (attacker tries to double count)
    r2 = make_earned(job_id="dup1")
    # Override the receipt_id to bypass primary key collision
    r2 = EarnedReceipt(
        receipt_id="e_other_id", issuer="client1", subject="v1",
        amount=200, ts=r.ts, ttl_seconds=r.ttl_seconds,
        signature=r.signature, job_id="dup1",
    )
    ok2, reason = verifier.verify_and_store(r2)
    assert not ok2
    assert "duplicate" in reason or "duplicate receipt_id" in reason


def test_missing_signature_rejected(verifier):
    r = make_earned(sig="")
    ok, reason = verifier.verify(r)
    assert not ok
    assert "signature" in reason
