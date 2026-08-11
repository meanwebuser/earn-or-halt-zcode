# Claims, evidence и ограничения

Этот файл заменяет сильные формулировки старой спецификации на claims,
которые можно проследить до кода и тестов.

## C1 — Deposit не поднимает rank

Wallet.earned_profit использует только cumulative earned revenue minus cost.
Deposit попадает в balance_deposits и расходуется первым, но не меняет
earned_profit. Ranker получает wallet balance отдельно и сортирует по
receipt-derived profit.

Evidence:

- [earn_or_halt/wallet.py](../earn_or_halt/wallet.py);
- [earn_or_halt/selection/rank.py](../earn_or_halt/selection/rank.py);
- tests/test_anti_whale.py и tests/test_selection.py.

Это защищает только accounting split. Оно не защищает от provider/client
collusion или от невалидного источника receipt.

## C2 — Duplicate/expired receipt guards exist on verified path

ReceiptVerifier проверяет expiry, positive amount, optional issuer whitelist,
existing (issuer, job_id) и non-empty signature. Ledger primary key защищает
duplicate receipt_id. ReceiptStore и Ranker агрегируют ledger rows в window.

Важно: Ledger.ingest_receipt можно вызвать напрямую, и verifier не проверяет
cryptographic signature. Поэтому C2 означает локальный guard path, а не
signed receipt security.

Evidence: [earn_or_halt/receipts/verify.py](../earn_or_halt/receipts/verify.py),
[earn_or_halt/ledger.py](../earn_or_halt/ledger.py),
tests/test_receipts.py.

## C3 — Top-three и alive — разные outputs

Ranker присваивает rank 1..3 только top-three, но alive=True у каждой version
с positive profit в rolling 30-day window. EjectionTracker отдельно
учитывает heartbeat age и не является Ranker.

Evidence: [earn_or_halt/selection/rank.py](../earn_or_halt/selection/rank.py),
[earn_or_halt/selection/ejection.py](../earn_or_halt/selection/ejection.py),
tests/test_selection.py.

В Runtime нет peer network, который автоматически отправляет эти результаты
другим версиям. Это локальные classes.

## C4 — Heartbeat ejection is local state

HeartbeatReader считает запись alive до HALT_TIMEOUT, игнорирует старую запись
после более новой, а EjectionTracker переводит stale peer в
PRESUMED_HALTED. Новая heartbeat запись может вернуть его в LIVE.
Suspect state создаётся explicit mark_suspect; автоматического rank mismatch
verifier в runtime нет.

## C5 — Economic halt clears local Wallet only in mock path

EconomicPolicy создаёт HaltRecord при configured conditions. Runtime
_execute_halt обнуляет local Wallet и логирует residual; on-chain CoinClient
transfer — optional и выполняется только при configured account/web3. HaltRecord
не записывается persistent store в текущем implementation.

Evidence: [earn_or_halt/policy.py](../earn_or_halt/policy.py),
[earn_or_halt/runtime.py](../earn_or_halt/runtime.py),
tests/test_economics.py.

## C6 — Resurrection rejects hash mismatch and unsafe archive entries

ReleaseVerifier действительно сравнивает SHA-256 tarball с Version.code_hash.
SafeExtractor отклоняет traversal, absolute paths, escaping links и device
files. Но _verify_signature в текущем MVP — placeholder: достаточно непустой
signature и expected_pubkey. ResurrectionSeed читает local EOH_POINTER_FILE;
live RPC integration отсутствует.

Evidence: [earn_or_halt/resurrection/verify.py](../earn_or_halt/resurrection/verify.py),
[earn_or_halt/resurrection/extract.py](../earn_or_halt/resurrection/extract.py),
tests/test_resurrection.py.

## C7 — Solidity contracts are optional anchors, not full selection proof

EarnOrHaltToken реализует token movement, code-hash registry и starter-credit
sketch. ReceiptsRegistry хранит receipt hash/code hash/kind/timestamp, но
anchor не проверяет receipt signature и не считает rank. Runtime по умолчанию
не вызывает эти контракты.

До production ECDSA verifier, live registry transport, deployment и audit
нельзя утверждать on-chain Earn or Halt protocol.
