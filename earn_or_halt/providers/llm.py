"""Mock LLM provider. Returns canned text + signed ExpenseReceipt."""

from __future__ import annotations

import secrets
import time
from typing import Optional

from .base import Provider, ProviderError, SignedQuote
from ..types import ExpenseReceipt
from ..constants import RECEIPT_TTL


class MockLLMProvider(Provider):
    """Pretends to be OpenRouter / OpenAI / Anthropic.

    Each instance has a `secret` (mock private key) used to sign
    ExpenseReceipts. The provider's `issuer_id` is the public
    counterpart, and is what other versions whitelist.
    """

    issuer_id: str = "mock_llm_v1"

    # Price per 1K tokens. In production this would be fetched from
    # a market-price oracle and compared against the receipt amount
    # to detect collusion (X1 mitigation).
    PRICE_PER_1K: int = 100  # smallest token units

    def __init__(self, secret: Optional[bytes] = None) -> None:
        self._secret = secret or secrets.token_bytes(32)

    def quote(self, subject: str, job_id: str, description: str,
              max_tokens: int = 1024) -> SignedQuote:
        amount = (max_tokens // 1000 + 1) * self.PRICE_PER_1K
        ts = int(time.time())
        q = SignedQuote(
            issuer=self.issuer_id, subject=subject, job_id=job_id,
            amount=amount, description=description, ts=ts,
            quote_sig=self.sign(f"{job_id}|{amount}|{ts}".encode(), self._secret),
        )
        return q

    def execute(self, quote: SignedQuote) -> tuple[bytes, ExpenseReceipt]:
        # In production, here we'd call the real provider API.
        result = f"<llm response for {quote.description[:40]}>".encode()
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
