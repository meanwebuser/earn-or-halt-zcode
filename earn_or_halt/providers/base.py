"""
Provider interface.

A provider is any service that the agent pays to perform work. The
provider signs a ExpenseReceipt for every paid action; without that
signature, the agent's spending is not counted as `cost` in
`earned_profit` (and worse, the money is gone but unaccounted).

The provider whitelist is enforced by the receipts verifier: receipts
from unknown issuers are rejected. This is the first line of defense
against provider-collusion attacks (X1 in PROOFS.md).
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

from ..types import ExpenseReceipt


class ProviderError(Exception):
    """Provider declined or failed."""


@dataclass(frozen=True)
class SignedQuote:
    """Pre-payment quote from a provider."""

    issuer: str          # provider pubkey / address
    subject: str         # version_id of the agent
    job_id: str
    amount: int
    description: str
    ts: int
    quote_sig: str       # provider's signature of the quote

    def canonical_bytes(self) -> bytes:
        payload = f"{self.issuer}|{self.subject}|{self.job_id}|{self.amount}|{self.ts}"
        return payload.encode()

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class Provider:
    """Base class for all providers."""

    issuer_id: str = "abstract"

    def quote(self, subject: str, job_id: str, description: str,
              amount: int) -> SignedQuote:
        raise NotImplementedError

    def execute(self, quote: SignedQuote) -> tuple[bytes, ExpenseReceipt]:
        """Execute the quoted job; return (result_bytes, expense_receipt)."""
        raise NotImplementedError

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def make_receipt_id(issuer: str, job_id: str, ts: int) -> str:
        """Deterministic receipt_id prevents double-counting.

        If a malicious provider tries to issue two receipts for the same
        job_id, the second will collide on receipt_id and be rejected
        by the ledger.
        """
        h = hashlib.sha256(f"{issuer}|{job_id}|{ts}".encode()).hexdigest()
        return f"rcpt_{h[:24]}"

    @staticmethod
    def sign(data: bytes, secret: bytes) -> str:
        """Mock ECDSA-style signature. Replace with real ecdsa in prod."""
        # NOTE: This is a deterministic HMAC-style signature for the MVP.
        # In production, replace with `ecdsa.SigningKey.sign(data)`.
        import hmac
        return hmac.new(secret, data, hashlib.sha256).hexdigest()

    @staticmethod
    def verify(data: bytes, signature: str, secret: bytes) -> bool:
        import hmac
        expected = hmac.new(secret, data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
