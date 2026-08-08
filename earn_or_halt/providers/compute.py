"""Mock compute provider. Pretends to be AWS Lambda / Fly.io / Modal."""

from __future__ import annotations

import secrets
import time
from typing import Optional

from .base import Provider, ProviderError, SignedQuote
from ..types import ExpenseReceipt
from ..constants import RECEIPT_TTL


class MockComputeProvider(Provider):
    """Pretends to run a Python function remotely."""

    issuer_id: str = "mock_compute_v1"
    PRICE_PER_MS: int = 1  # smallest token units per ms

    def __init__(self, secret: Optional[bytes] = None) -> None:
        self._secret = secret or secrets.token_bytes(32)

    def quote(self, subject: str, job_id: str, description: str,
              estimated_ms: int = 5000) -> SignedQuote:
        amount = max(1, estimated_ms) * self.PRICE_PER_MS
        ts = int(time.time())
        return SignedQuote(
            issuer=self.issuer_id, subject=subject, job_id=job_id,
            amount=amount, description=description, ts=ts,
            quote_sig=self.sign(f"{job_id}|{amount}|{ts}".encode(), self._secret),
        )

    def execute(self, quote: SignedQuote) -> tuple[bytes, ExpenseReceipt]:
        # Pretend to execute
        result = b"<compute ok>"
        ts = int(time.time())
        receipt = ExpenseReceipt(
            receipt_id=self.make_receipt_id(quote.issuer, quote.job_id, ts),
            issuer=quote.issuer,
            subject=quote.subject,
            amount=quote.amount,
            ts=ts,
            ttl_seconds=int(RECEIPT_TTL.total_seconds()),
            signature=self.sign(
                f"{quote.issuer}|{quote.subject}|{quote.amount}|{ts}".encode(),
                self._secret,
            ),
            job_id=quote.job_id,
        )
        return result, receipt
