"""
Runtime — main agent loop.

The runtime executes three nested cycles:

  Economic cycle (per task, ~minutes):
    receive job → quote from provider → check policy.can_afford →
    execute (signs ExpenseReceipt) → deliver work → collect payment
    (signs EarnedReceipt) → update wallet → ask policy.should_halt

  Selection cycle (per epoch, ~30 days):
    every HEARTBEAT_PERIOD: publish signed Heartbeat
    every SURVIVAL_WINDOW: recompute ranking across all versions
    if outside positive earners for >HALT_TIMEOUT: write halt,
    residual balance → commons pool

  Resurrection cycle (per release, ~weeks):
    if the runtime is starting from a halted state, run ResurrectionSeed
    to fetch + verify + extract + exec the next release.

This file is the entrypoint. Run with:

    python -m earn_or_halt.runtime --mock

to use the mock LLM/compute providers and a local SQLite ledger.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .types import (
    Deposit, EarnedReceipt, ExpenseReceipt, HaltReason, HaltRecord,
    Receipt, Version,
)
from .wallet import Wallet, InsufficientBalanceError
from .ledger import Ledger
from .policy import EconomicPolicy, PolicyDecision
from .providers import MockLLMProvider, MockComputeProvider, Provider
from .receipts.verify import ReceiptVerifier
from .receipts.store import ReceiptStore
from .selection.rank import Ranker, RankEntry
from .selection.heartbeat import HeartbeatSender, HeartbeatReader
from .selection.ejection import EjectionTracker, EjectionState
from .coin.client import CoinClient
from .constants import (
    LEDGER_PATH, HEARTBEAT_PERIOD, SURVIVAL_WINDOW, HALT_TIMEOUT,
    RECEIPT_TTL,
)


log = logging.getLogger("earn_or_halt.runtime")


@dataclass
class RuntimeConfig:
    version_id: str = "v3.0.0-mock"
    code_hash: str = "0" * 64
    release_sig: str = "0" * 64
    release_pubkey: str = "0" * 64
    ledger_path: str = LEDGER_PATH
    runtime_secret_hex: str = ""
    provider_whitelist: set[str] = field(default_factory=set)
    client_whitelist: set[str] = field(default_factory=set)
    coin_address: Optional[str] = None
    rpc_url: str = "http://localhost:8545"
    mock_loops: int = 5   # number of economic cycles to run in --mock mode

    def runtime_secret(self) -> bytes:
        if self.runtime_secret_hex:
            return bytes.fromhex(self.runtime_secret_hex)
        return secrets.token_bytes(32)


@dataclass
class Runtime:
    """Top-level agent runtime."""

    cfg: RuntimeConfig
    wallet: Wallet = field(init=False)
    ledger: Ledger = field(init=False)
    verifier: ReceiptVerifier = field(init=False)
    store: ReceiptStore = field(init=False)
    policy: EconomicPolicy = field(init=False)
    ranker: Ranker = field(init=False)
    heartbeat_sender: HeartbeatSender = field(init=False)
    heartbeat_reader: HeartbeatReader = field(init=False)
    ejection: EjectionTracker = field(init=False)
    llm: MockLLMProvider = field(init=False)
    compute: MockComputeProvider = field(init=False)
    coin: Optional[CoinClient] = field(init=False, default=None)
    version: Version = field(init=False)

    def __post_init__(self) -> None:
        self.version = Version(
            version_id=self.cfg.version_id,
            code_hash=self.cfg.code_hash,
            release_sig=self.cfg.release_sig,
            release_pubkey=self.cfg.release_pubkey,
        )
        self.wallet = Wallet(version_id=self.cfg.version_id)
        self.ledger = Ledger(self.cfg.ledger_path)
        self.verifier = ReceiptVerifier(
            ledger=self.ledger,
            provider_whitelist=self.cfg.provider_whitelist,
            client_whitelist=self.cfg.client_whitelist,
        )
        self.store = ReceiptStore(self.ledger)
        self.policy = EconomicPolicy()
        self.ranker = Ranker(self.store)
        self.heartbeat_sender = HeartbeatSender(self.cfg.runtime_secret())
        self.heartbeat_reader = HeartbeatReader()
        self.ejection = EjectionTracker()
        self.llm = MockLLMProvider()
        self.compute = MockComputeProvider()
        if self.cfg.coin_address:
            self.coin = CoinClient(
                contract_address=self.cfg.coin_address,
                rpc_url=self.cfg.rpc_url,
            )

        self.ledger.record_version(self.version)

        # On first run (empty ledger), request starter credit.
        # In production this is a call to EarnOrHaltToken.requestStarterCredit(codeHash).
        # For mock mode, we just inject a Deposit locally.
        if not self.ledger.receipts_for(self.cfg.version_id):
            self._request_starter_credit()

    def _request_starter_credit(self) -> None:
        """Bootstrap with starter credit from commons pool."""
        starter_amount = 10_000  # smallest token units; prod: 1000 * 10^18
        deposit = Deposit(
            deposit_id=f"starter_{self.cfg.version_id}",
            sender="commons_pool",
            subject=self.cfg.version_id,
            amount=starter_amount,
            ts=int(time.time()),
            note="starter credit (mock mode)",
        )
        # Deposits skip the verifier (they're not receipts); just store + credit.
        self.ledger.ingest_deposit(deposit)
        self.wallet.credit_deposit(deposit)
        log.info("starter credit: +%d tokens from commons pool", starter_amount)

    # ── Economic cycle ─────────────────────────────────────────────────

    def run_economic_cycle(self, job_id: str) -> Optional[HaltRecord]:
        """One iteration of the economic loop. Returns HaltRecord if halted."""
        log.info("economic cycle start: job=%s", job_id)

        # 1. Get a quote from the LLM provider
        quote = self.llm.quote(
            subject=self.cfg.version_id,
            job_id=job_id,
            description=f"complete job {job_id}",
            max_tokens=2048,
        )
        log.info("quote: amount=%d from=%s", quote.amount, quote.issuer)

        # 2. Check policy: can we afford it?
        decision = self.policy.can_afford(self.wallet, quote.amount)
        if not decision.allow:
            log.warning("cannot afford next step: %s", decision.reason)
            halt_decision = self.policy.should_halt(
                self.version, self.wallet,
                last_positive_earned_ts=self.store.last_earned_ts(
                    self.cfg.version_id
                ),
            )
            if halt_decision.halt:
                self._execute_halt(halt_decision.halt)
                return halt_decision.halt
            return None

        # 3. Execute the LLM call (produces an ExpenseReceipt)
        try:
            _, expense_receipt = self.llm.execute(quote)
        except Exception as e:
            log.error("provider failed: %s", e)
            return None

        # 4. Verify and ingest the ExpenseReceipt
        ok, reason = self.verifier.verify_and_store(expense_receipt)
        if not ok:
            log.error("expense receipt rejected: %s", reason)
            return None

        # 5. Debit the wallet
        try:
            self.wallet.debit_expense(expense_receipt)
        except InsufficientBalanceError as e:
            log.error("insufficient balance despite policy: %s", e)
            return None
        log.info("debited %d, balance=%d earned_profit=%d",
                 expense_receipt.amount, self.wallet.total_balance,
                 self.wallet.earned_profit)

        # 6. Deliver work and collect payment (EarnedReceipt)
        # In production, this is where the agent does the actual work
        # and the client signs an EarnedReceipt for the agreed price.
        payment_amount = quote.amount * 2  # 2x markup for demo
        earned_receipt = self._simulate_client_payment(job_id, payment_amount)

        ok, reason = self.verifier.verify_and_store(earned_receipt)
        if not ok:
            log.error("earned receipt rejected: %s", reason)
            return None
        self.wallet.credit_earned(earned_receipt)
        log.info("earned %d, balance=%d earned_profit=%d",
                 earned_receipt.amount, self.wallet.total_balance,
                 self.wallet.earned_profit)

        # 7. Check halt conditions
        halt_decision = self.policy.should_halt(
            self.version, self.wallet,
            last_positive_earned_ts=self.store.last_earned_ts(
                self.cfg.version_id
            ),
        )
        if halt_decision.halt:
            self._execute_halt(halt_decision.halt)
            return halt_decision.halt

        return None

    def _simulate_client_payment(self, job_id: str, amount: int) -> EarnedReceipt:
        """Mock: simulate a client signing an EarnedReceipt."""
        client_id = "mock_client_v1"
        ts = int(time.time())
        receipt_id = Provider.make_receipt_id(client_id, job_id, ts)
        # NOTE: in production this is signed by the client's key, not ours.
        sig = Provider.sign(
            f"{client_id}|{self.cfg.version_id}|{amount}|{ts}".encode(),
            self.cfg.runtime_secret(),
        )
        return EarnedReceipt(
            receipt_id=receipt_id,
            issuer=client_id,
            subject=self.cfg.version_id,
            amount=amount,
            ts=ts,
            ttl_seconds=int(RECEIPT_TTL.total_seconds()),
            signature=sig,
            job_id=job_id,
        )

    # ── Selection cycle ───────────────────────────────────────────────

    def publish_heartbeat(self) -> None:
        """Send a signed heartbeat to the registry (mock: in-memory)."""
        # In production: post to a public message board / on-chain anchor.
        receipt_ids = [r.receipt_id for r in self.ledger.receipts_for(
            self.cfg.version_id
        )]
        hb = self.heartbeat_sender.build(
            version=self.version, wallet=self.wallet,
            receipt_ids_since_last=receipt_ids[-20:],
        )
        self.heartbeat_reader.ingest(hb)
        log.info("heartbeat published: rank_signal=%s balance=%d",
                 hb.rank_signal, hb.balance)

    # ── Halt ──────────────────────────────────────────────────────────

    def _execute_halt(self, halt: HaltRecord) -> None:
        log.warning("HALT: reason=%s final_balance=%d",
                    halt.reason.value, halt.final_balance)
        # Transfer residual to commons pool
        residual = self.wallet.transfer_residual()
        if residual > 0 and self.coin is not None:
            # In production: on-chain transfer to commons pool address.
            log.info("transferring %d tokens to commons pool", residual)
        # In production: persist HaltRecord to disk and exit non-zero.

    # ── Main loop ─────────────────────────────────────────────────────

    def run_mock(self, loops: Optional[int] = None) -> int:
        """Run N mock economic cycles. Returns 0 if all OK, 1 if halted."""
        n = loops if loops is not None else self.cfg.mock_loops
        for i in range(n):
            log.info("=== loop %d/%d ===", i + 1, n)
            halt = self.run_economic_cycle(job_id=f"job_{i:04d}")
            if halt is not None:
                log.info("agent halted after %d cycles", i + 1)
                return 1
            self.publish_heartbeat()
        log.info("completed %d cycles without halt", n)
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Earn or Halt runtime")
    p.add_argument("--mock", action="store_true",
                   help="Run in mock mode (no real providers)")
    p.add_argument("--loops", type=int, default=5,
                   help="Number of economic cycles to run in mock mode")
    p.add_argument("--ledger", default=LEDGER_PATH,
                   help="Path to SQLite ledger file")
    p.add_argument("--version-id", default="v3.0.0-mock")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    cfg = RuntimeConfig(
        version_id=args.version_id,
        ledger_path=args.ledger,
        mock_loops=args.loops,
        # In mock mode, whitelist the mock providers and mock client so
        # the verifier accepts their receipts.
        provider_whitelist={"mock_llm_v1", "mock_compute_v1"},
        client_whitelist={"mock_client_v1"},
    )
    rt = Runtime(cfg=cfg)

    # Handle SIGINT cleanly: write halt record and exit
    def _sigint(_signo, _frame):
        log.warning("SIGINT received, halting")
        sys.exit(130)
    signal.signal(signal.SIGINT, _sigint)

    return rt.run_mock()


if __name__ == "__main__":
    sys.exit(main())
