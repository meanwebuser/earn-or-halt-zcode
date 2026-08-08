"""
Core types for Earn or Halt.

All cryptographic operations use ECDSA over secp256k1, matching the
EVM curve so receipts can be verified on-chain by the ReceiptsRegistry
contract without any conversion.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

# ── Identifiers ──────────────────────────────────────────────────────


class HaltReason(str, Enum):
    """Reasons an agent voluntarily stops."""

    NEGATIVE_MARGIN = "negative_margin"           # cost > revenue
    INSUFFICIENT_BALANCE = "insufficient_balance" # cannot afford next step
    OUTSIDE_TOP_TIMEOUT = "outside_top_timeout"  # 30d no positive earned
    PROVIDER_FAILURE = "provider_failure"        # upstream died
    PROTOCOL_VIOLATION = "protocol_violation"    # self-detected


@dataclass(frozen=True)
class Version:
    """A specific released version of the agent.

    `code_hash` is the SHA-256 of the canonical release tarball, anchored
    on-chain. A fork of the source produces a different `code_hash` and
    is therefore a different Version for ranking purposes.
    """

    version_id: str         # human-readable, e.g. "v3.0.0"
    code_hash: str          # sha256 hex of release tarball
    release_sig: str        # ECDSA signature of code_hash by release key
    release_pubkey: str     # release signer's pubkey (hex)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Receipt:
    """
    Base receipt. Subclassed by EarnedReceipt and ExpenseReceipt.

    A receipt is the atomic proof that money moved for a reason. Without
    a receipt, money movement does not count toward earned_profit.

    Fields:

    - receipt_id: unique, derived from (issuer, job_id, ts)
    - issuer: signing party (client for Earned, provider for Expense)
    - subject: version_id this receipt is about
    - amount: in smallest token unit (wei-equivalent)
    - ts: issuance unix timestamp, seconds
    - ttl_seconds: receipt expires after this; defaults to RECEIPT_TTL
    - signature: ECDSA(r,s,v) over the canonical hash of the above
    - job_id: work identifier, scoped to issuer
    - kind: 'earned' or 'expense'
    """

    receipt_id: str
    issuer: str
    subject: str          # version_id
    amount: int
    ts: int
    ttl_seconds: int
    signature: str
    job_id: str
    kind: str             # 'earned' or 'expense'

    def canonical_bytes(self) -> bytes:
        """Bytes that get signed. Deterministic ordering."""
        payload = {
            "receipt_id": self.receipt_id,
            "issuer": self.issuer,
            "subject": self.subject,
            "amount": self.amount,
            "ts": self.ts,
            "ttl_seconds": self.ttl_seconds,
            "job_id": self.job_id,
            "kind": self.kind,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def canonical_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def is_expired(self, now_ts: Optional[int] = None) -> bool:
        now = now_ts if now_ts is not None else int(time.time())
        return now > (self.ts + self.ttl_seconds)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EarnedReceipt(Receipt):
    """
    Proof that a client paid the agent for work done.

    Signed by the client (issuer). The agent is the subject.

    The split between EarnedReceipt and a generic deposit is critical:
    ONLY EarnedReceipt counts toward earned_revenue. A whale can
    deposit any amount into the agent's wallet, but that deposit is
    NOT an EarnedReceipt and therefore does not affect rank_signal.
    """

    kind: str = "earned"


@dataclass(frozen=True)
class ExpenseReceipt(Receipt):
    """
    Proof that the agent paid a provider for a service.

    Signed by the provider (issuer). The agent is the subject.

    A provider signing a fake ExpenseReceipt for an off-chain kickback
    is a known attack (X1 in PROOFS.md). Mitigations: provider whitelist,
    market-price oracle comparison, double-count detection by (issuer, job_id).
    """

    kind: str = "expense"


@dataclass(frozen=True)
class Deposit:
    """
    A non-earned money movement into the agent's wallet.

    Examples: starter credit from commons pool, user donation, transfer
    from another version. Deposits increase `balance` but do NOT enter
    `earned_profit` and therefore do NOT affect `rank_signal`.
    """

    deposit_id: str
    sender: str
    subject: str       # version_id
    amount: int
    ts: int
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Heartbeat:
    """
    Periodic signed state publication.

    Every HEARTBEAT_PERIOD, each live version publishes its current
    state: wallet balance, earned_revenue, cost, rank_signal, and a
    list of receipt_ids since the last heartbeat. Other versions
    use heartbeats to compute the global ranking and to detect
    misbehaving or halted peers.
    """

    version: Version
    ts: int
    earned_revenue: int
    cost: int
    balance: int
    rank_signal: float
    receipt_ids_since_last: list[str] = field(default_factory=list)
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        payload = {
            "version_id": self.version.version_id,
            "code_hash": self.version.code_hash,
            "ts": self.ts,
            "earned_revenue": self.earned_revenue,
            "cost": self.cost,
            "balance": self.balance,
            "rank_signal": self.rank_signal,
            "receipt_ids": sorted(self.receipt_ids_since_last),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


@dataclass
class HaltRecord:
    """Recorded halt decision. Final state of a version."""

    version: Version
    ts: int
    reason: HaltReason
    final_balance: int
    residual_destination: str = "commons_pool"

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "version": self.version.to_dict(),
            "reason": self.reason.value,
        }
