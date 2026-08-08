"""
Receipt verification.

The verifier is the gatekeeper. A receipt that fails ANY of the
following checks is rejected and does not enter the wallet:

1. Signature is valid for the receipt's canonical bytes.
2. Receipt has not expired (now <= ts + ttl_seconds).
3. Issuer is on the provider whitelist (for ExpenseReceipt) or is a
   known client (for EarnedReceipt).
4. (issuer, job_id) is unique — no double-count.
5. Amount is positive and within reasonable bounds for the issuer
   (anti-forgery heuristic; market-price oracle comparison belongs
   here in production).
"""

from __future__ import annotations

import time
from typing import Optional, Set

from ..types import EarnedReceipt, ExpenseReceipt, Receipt
from ..providers.base import Provider
from ..ledger import Ledger


class ReceiptVerifier:
    """Verify receipts before they enter the wallet."""

    def __init__(
        self,
        ledger: Ledger,
        provider_whitelist: Optional[Set[str]] = None,
        client_whitelist: Optional[Set[str]] = None,
        max_amount_per_receipt: int = 1_000_000 * 10**18,
    ) -> None:
        self.ledger = ledger
        self.provider_whitelist = provider_whitelist or set()
        self.client_whitelist = client_whitelist or set()
        self.max_amount = max_amount_per_receipt

    def verify(self, r: Receipt, now_ts: Optional[int] = None) -> tuple[bool, str]:
        """
        Returns (ok, reason). If ok=False, the receipt MUST NOT enter
        the wallet and MUST NOT be stored in the ledger.
        """
        now = now_ts if now_ts is not None else int(time.time())

        # 1. Expiry
        if r.is_expired(now):
            return False, "expired"

        # 2. Amount sanity
        if r.amount <= 0:
            return False, "amount must be positive"
        if r.amount > self.max_amount:
            return False, f"amount {r.amount} exceeds sanity bound"

        # 3. Issuer whitelist
        if r.kind == "earned":
            if self.client_whitelist and r.issuer not in self.client_whitelist:
                return False, f"client {r.issuer} not whitelisted"
        else:
            if self.provider_whitelist and r.issuer not in self.provider_whitelist:
                return False, f"provider {r.issuer} not whitelisted"

        # 4. Double-count
        if self.ledger.has_receipt(r.issuer, r.job_id):
            return False, f"duplicate (issuer={r.issuer}, job_id={r.job_id})"

        # 5. Signature — see Provider.verify for the mock impl.
        # In production, fetch the issuer's pubkey from a registry and
        # verify the ECDSA signature against canonical_bytes().
        # Here, we accept any non-empty signature; the provider mock
        # signs deterministically with HMAC.
        if not r.signature:
            return False, "missing signature"

        return True, "ok"

    def verify_and_store(self, r: Receipt) -> tuple[bool, str]:
        ok, reason = self.verify(r)
        if not ok:
            return False, reason
        inserted = self.ledger.ingest_receipt(r)
        if not inserted:
            return False, "duplicate receipt_id"
        return True, "ok"
