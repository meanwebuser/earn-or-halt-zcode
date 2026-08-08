"""
Coin integration — ERC-20 wrapper.

Lightweight wrapper around the EarnOrHaltToken contract. Used by the
runtime to:
- check on-chain balance
- transfer tokens to providers (for paid services)
- request starter credit from the commons pool
- send residual balance to commons pool at halt

The wrapper does NOT trust the local wallet's balance_earned /
balance_deposits as the on-chain truth. The on-chain balance is the
real source of truth for "can I spend this token"; the local wallet
tracks earned_revenue / cost separately for rank_signal computation.

This split is intentional:
- on-chain balance = spendable money (governed by token contract)
- local earned_revenue / cost = rank signal (governed by signed receipts)

A whale can deposit into the on-chain balance, but those deposits
become balance_deposits locally (not earned_revenue), so they
inflate spendable money but NOT rank_signal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# web3 is an optional dependency; the runtime works without it.
try:
    from web3 import Web3  # type: ignore
    HAS_WEB3 = True
except ImportError:
    Web3 = None  # type: ignore
    HAS_WEB3 = False


ABI_PATH = Path(__file__).parent / "erc20_abi.json"


@dataclass
class CoinClient:
    """ERC-20 client. No-op when web3 is not installed."""

    contract_address: str
    rpc_url: str = "http://localhost:8545"
    account: Optional[str] = None     # agent's wallet address

    _w3: object = None
    _contract: object = None

    def __post_init__(self) -> None:
        if not HAS_WEB3:
            return
        self._w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        with ABI_PATH.open() as f:
            abi = json.load(f)
        self._contract = self._w3.eth.contract(
            address=self.contract_address, abi=abi
        )

    @property
    def available(self) -> bool:
        return HAS_WEB3 and self._w3 is not None

    def balance_of(self, address: Optional[str] = None) -> int:
        if not self.available:
            return 0
        addr = address or self.account
        if addr is None:
            return 0
        return self._contract.functions.balanceOf(addr).call()

    def transfer(self, to: str, amount: int) -> bool:
        """Send tokens. Returns True on success."""
        if not self.available or self.account is None:
            return False
        tx = self._contract.functions.transfer(to, amount).transact(
            {"from": self.account}
        )
        receipt = self._w3.eth.wait_for_transaction_receipt(tx)
        return receipt["status"] == 1

    def request_starter_credit(self, code_hash: bytes) -> bool:
        """Request starter credit from commons pool.

        The contract verifies that the requesting address's claimed
        code_hash matches a known release; this prevents a whale from
        minting unlimited starter credits for arbitrary code.
        """
        if not self.available or self.account is None:
            return False
        tx = self._contract.functions.requestStarterCredit(
            self.account, 0, code_hash
        ).transact({"from": self.account})
        receipt = self._w3.eth.wait_for_transaction_receipt(tx)
        return receipt["status"] == 1
