"""
Protocol constants — PINNED.

Any change here requires a new signed release. Constants are NOT
configurable via environment variables or runtime configuration,
because if they were, an attacker could change N to 1 and trivially
monopolize the network, or change TIMEOUT to 1 second to kill
honest competitors.

These values are committed to source, included in code_hash,
anchored on-chain at release time, and verified by every other
version at heartbeat time.
"""

from datetime import timedelta

# ── Selection ─────────────────────────────────────────────────────────
# Top-N for routing of new incoming work. Hardcoded. N=3 chosen as the
# smallest odd number enabling 2-of-3 majority for distributed decisions.
N_TOP: int = 3

# Survival window. A version with positive earned_profit during this
# window stays alive. 30 days = monthly B2B cycle.
SURVIVAL_WINDOW: timedelta = timedelta(days=30)

# Heartbeat period. Every version publishes signed state at this interval.
HEARTBEAT_PERIOD: timedelta = timedelta(hours=1)

# Receipt time-to-live. Receipts older than this are not counted in
# rank_signal. Must be >= SURVIVAL_WINDOW so that a single successful
# month keeps the version alive.
RECEIPT_TTL: timedelta = timedelta(days=30)

# Halt timeout. A version whose earned_profit stayed non-positive for
# this long MUST write halt. Note: this is not the same as
# SURVIVAL_WINDOW; SURVIVAL_WINDOW defines the rolling window for
# rank_signal, HALT_TIMEOUT defines the absolute deadline.
HALT_TIMEOUT: timedelta = timedelta(days=30)

# ── Resurrection ──────────────────────────────────────────────────────
# Blockscout contract address that stores the latest release pointer.
# Testnet default. Override per-network in deployment config.
RELEASE_POINTER_CONTRACT: str = "0x0000000000000000000000000000000000000000"

# IPFS gateways used for fallback. Tried in order. Order is public.
IPFS_GATEWAYS: tuple[str, ...] = (
    "https://ipfs.io/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://dweb.link/ipfs/",
)

# Minimum key strength for release signatures.
RELEASE_SIGNATURE_CURVE: str = "secp256k1"

# ── Coin ──────────────────────────────────────────────────────────────
# ERC-20 token contract address on testnet. Mainnet deployment TBD.
COIN_CONTRACT_ADDRESS: str = "0x0000000000000000000000000000000000000000"

# Initial supply minted to commons pool. 1_000_000 whole units × 10^18 wei.
COIN_INITIAL_SUPPLY: int = 1_000_000 * 10**18

# Emission period. Linear mint to commons pool over 4 years.
COIN_EMISSION_PERIOD: timedelta = timedelta(days=365 * 4)

# ── Audit ─────────────────────────────────────────────────────────────
# SQLite ledger file. Local to the runtime.
LEDGER_PATH: str = "earn_or_halt.db"
