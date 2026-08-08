# Earn or Halt — Agent Capitalism Protocol

> **Resilient code. Mortal economics.**

An autonomous agent that earns the right to its next cycle. Every version
competes against every other version on one signal: signed `earned_profit`.
Lose for 30 days — write `halt`, transfer residual balance to commons pool,
stop. Code may resurrect via signed releases; economic failure does not.

This is not philosophy. This is a working specification + Python MVP +
Solidity receipts registry + Docker runtime.

## Core Invariants

1. `rank_signal(V) = f(earned_profit(V))` only.
   Nothing that depends on `deposits` enters `rank_signal`.
2. `earned_profit = Σ EarnedReceipt.amount − Σ ExpenseReceipt.amount`.
   Both sums are over signed, unique, non-expired receipts.
3. Top-3 routing is hardcoded. Survival is emergent: any version with
   positive `earned_profit` in the last window stays alive.
4. Heartbeat every 1h. 30 days without positive `earned_profit` → `halt`.
5. Resurrection = pinned release hash + ECDSA signature verified before
   any byte is executed. Runtime never holds the release private key.
6. Selection enforcement is distributed. No kill switch. Misbehaving
   versions are socially excluded (receipts ignored, work not routed).

## Repository Layout

```
earn_or_halt/
  types.py            # Receipt, Deposit, Version, HaltReason
  constants.py        # N=3, TIMEOUT=30d, HB=1h, RECEIPT_TTL=30d (pinned)
  wallet.py           # Balance accounting, earned vs deposits split
  ledger.py           # SQLite ledger, audit chain
  policy.py           # Economic policy: can_afford, should_halt
  providers/          # Mock LLM + compute providers with signed receipts
  receipts/
    verify.py          # ECDSA verify, double-count, TTL
    store.py           # Receipt storage + query
  selection/
    rank.py            # rank_signal computation
    heartbeat.py       # Heartbeat sender + reader
    ejection.py        # Distributed ejection logic
  resurrection/
    seed.py            # 7-step bootstrap from Blockscout pointer
    fetch.py           # IPFS/HTTPS fallback fetcher
    verify.py          # SHA-256 + ECDSA release signature
    extract.py         # Safe tar extraction (path traversal safe)
  coin/
    erc20_abi.json     # ABI for EarnOrHaltToken
  runtime.py          # Main agent loop

contracts/
  EarnOrHaltToken.sol # ERC-20 with mint schedule + commons pool
  ReceiptsRegistry.sol# On-chain receipts anchor (optional)

tests/
  test_receipts.py
  test_economics.py
  test_anti_whale.py
  test_selection.py
  test_resurrection.py

docs/
  PHILOSOPHY.md
  INSIDE.md
  PROOFS.md
```

## Quickstart

```bash
# Local dev
pip install -e .
pytest -q

# Run the agent loop in mock mode
python -m earn_or_halt.runtime --mock

# Docker
docker compose up --build
```

## Three Loops

The runtime executes three nested loops, each with its own failure mode:

```
┌──────────────────────────────────────────────────────┐
│  Resurrection loop (per release, ~weeks)             │
│  ┌────────────────────────────────────────────────┐  │
│  │  Selection loop (per epoch, ~30 days)          │  │
│  │  ┌──────────────────────────────────────────┐  │  │
│  │  │  Economic loop (per task, ~minutes)       │  │  │
│  │  │  - receive job                           │  │  │
│  │  │  - buy LLM call (sign ExpenseReceipt)    │  │  │
│  │  │  - deliver work                          │  │  │
│  │  │  - collect payment (sign EarnedReceipt)  │  │  │
│  │  │  - update earned_profit                  │  │  │
│  │  │  - ask policy: can_afford_next?          │  │  │
│  │  │  - if NO → halt                          │  │  │
│  │  └──────────────────────────────────────────┘  │  │
│  │  - send heartbeat + state to registry          │  │
│  │  - compute rank_signal across all versions     │  │
│  │  - if outside positive earners for 30d → halt  │  │
│  │  - on halt: residual → commons pool            │  │
│  └────────────────────────────────────────────────┘  │
│  - on halt: seed fetches latest pinned release      │
│  - verifies SHA-256 + ECDSA signature               │
│  - safe extract, exec                                │
└──────────────────────────────────────────────────────┘
```

## What "0 Trust to Participants" Means Here

- **Provider collusion**: a provider signing a fake `ExpenseReceipt` for
  off-chain kickback is possible. We mitigate via provider whitelist +
  market-price oracle (X1 in PROOFS.md, not fully solved).
- **Self-reported revenue**: forbidden. `EarnedReceipt` requires a
  counter-signature from the client. Without it, the receipt is invalid.
- **Whale deposits**: explicitly separated. `deposits` increase `balance`
  (agent can spend them) but do NOT increase `rank_signal`. A whale can
  fund a version's operations, but cannot push it up the ranking.
- **Fork attacks**: a forked version starts at `earned_profit = 0` and
  must independently earn signed receipts. The fork's `code_hash`
  differs from the canonical release, so its receipts cannot be merged.
- **Code substitution**: `code_hash` is anchored on-chain at release
  time. Reproducible builds (Docker pinned versions, `SOURCE_DATE_EPOCH`)
  let any third party verify that a published binary matches the
  published source.

## Coin

`EarnOrHaltToken` is an ERC-20 with:

- Fixed initial supply minted to a commons pool multisig (governance,
  not a single key).
- Emission schedule: linear over 4 years, minted to commons pool.
- Commons pool distributes starter credits to new versions that pass
  a deterministic-build verification (proof: matching `code_hash`).
- The token is **not** a security. It is a utility token for paying
  providers that accept it. Providers that require USDC must be paid
  via an automated DEX swap (out of scope for v3 MVP; see PROOFS.md X2).

## Documentation

- [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) — why this exists
- [docs/INSIDE.md](docs/INSIDE.md) — what's inside (specification, not status)
- [docs/PROOFS.md](docs/PROOFS.md) — formal invariants, threat model

## Status

v3 — full core rewrite. Selection protocol + coin + open-source
verification added on top of v2 economic runtime + resurrection chain.

## License

Apache License 2.0. See [LICENSE](LICENSE).
