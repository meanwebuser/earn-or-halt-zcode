# Earn or Halt — формальные инварианты и гарантии

> Этот документ описывает threat model и формальные утверждения о
> безопасности протокола. Каждое утверждение имеет either proof
> (машинно-проверяемое рассуждение от инвариантов) либо явно
> помечено как unsolved (X1–X4).

## Модель угроз

Атакующий — это участник с произвольным бюджетом, способный:

- Запускать любое количество версий агента (Sybil)
- Депать в любые кошельки
- Скупать токены на открытом рынке
- Форкать исходный код и подписывать своим ключом
- Подделывать сетевой трафик (man-in-the-middle)
- Компрометировать gateway (IPFS, HTTPS mirror)
- Сговариваться с провайдерами off-chain

Атакующий **не может**:

- Подделать ECDSA подпись (без приватного ключа)
- Изменить Ethereum mainnet состояние задним числом
- Подменить SHA-256(tarball) ≠ code_hash без коллизии
- Подменить канонические bytes чека без нарушения детерминизма JSON
- Заставить другой узел принять чек, не прошедший верификацию

## Формальные определения

```
Version          = (version_id, code_hash, release_sig, release_pubkey)
Receipt          = (receipt_id, issuer, subject, amount, ts,
                    ttl_seconds, signature, job_id, kind)
EarnedReceipt    = Receipt with kind = "earned"
ExpenseReceipt   = Receipt with kind = "expense"
Deposit          = (deposit_id, sender, subject, amount, ts)

ledger(V)        = all Receipts with subject = V.version_id
                  ingested and not expired and unique by (issuer, job_id)

earned_revenue(V, t) = Σ { r.amount : r ∈ ledger(V),
                            r.kind = "earned",
                            r.is_expired(t) = false }

cost(V, t)       = Σ { r.amount : r ∈ ledger(V),
                       r.kind = "expense",
                       r.is_expired(t) = false }

earned_profit(V, t) = earned_revenue(V, t) - cost(V, t)

balance(V, t)    = on-chain balance of V's wallet at time t

rank_signal(V, t) = earned_profit(V, t)   // I1

deposits(V, t)   = Σ { d.amount : d ∈ deposits, d.subject = V.version_id }
                  // does NOT enter rank_signal
```

## Инварианты

### I1 — Anti-whale split

```
rank_signal(V, t) = f(earned_profit(V, t))
```

для некоторой монотонно неубывающей `f`, и `deposits(V, t)` не входит
в `f` ни в каком виде.

**Enforcement**: константы и код `Ranker.rank()` в исходниках,
подписанные в релизе. Любая модификация = новый `code_hash`, что
делает receipts несовместимыми с canonical релизом.

### I2 — No double-count

```
∀ r1, r2 ∈ ledger(V): r1 ≠ r2 ⇒ (r1.issuer, r1.job_id) ≠ (r2.issuer, r2.job_id)
```

**Enforcement**: SQLite UNIQUE constraint на `(issuer, job_id)` плюс
idempotent ingest по `receipt_id`. Дубликаты молча отбрасываются.

### I3 — Halt is final

```
halt(V, t) ⇒ V does not publish new heartbeats after t
            AND V's residual balance transfers to commons_pool
```

**Enforcement**: runtime пишет `HaltRecord` в ledger и переводит
residual через `Wallet.transfer_residual()` → on-chain transfer в
commons pool. Если runtime этого не делает, его помечают
`suspect_hoarder` и его receipts перестают считаться.

### I4 — Heartbeat liveness

```
∀ V live at t:
  ∃ heartbeat h published by V in (t - HEARTBEAT_PERIOD, t]
```

**Enforcement**: runtime-цикл публикации heartbeat. Другие версии
отслеживают пропуски и помечают `presumed_halted`.

### I5 — Pinned protocol constants

```
∀ V, W of same release:
  N_TOP(V)              = N_TOP(W)
  SURVIVAL_WINDOW(V)    = SURVIVAL_WINDOW(W)
  HALT_TIMEOUT(V)       = HALT_TIMEOUT(W)
  HEARTBEAT_PERIOD(V)   = HEARTBEAT_PERIOD(W)
  RECEIPT_TTL(V)        = RECEIPT_TTL(W)
```

**Enforcement**: константы в исходниках, входят в `code_hash`.
Любая правка = новый `code_hash` = новый релиз = новая версия.

### I6 — Receipt expiry

```
r.is_expired(t) ⇒ r ∉ ledger(V, t) for rank_signal computation
```

**Enforcement**: `ReceiptStore.receipts_in_window()` режет по
`since_ts = now - SURVIVAL_WINDOW`. Чек старше TTL не входит в сумму.

## Гарантии

### G1 — Whale-атака невозможна

**Утверждение**: атакующий с произвольным депозитом не может поднять
версию в рейтинге выше честно зарабатывающей версии.

**Proof sketch**:

```
whale.deposits = ∞
whale.earned_revenue = 0    (никаких EarnedReceipts)
whale.rank_signal = f(0) = 0

honest.earned_revenue = 100
honest.rank_signal = f(100) > 0

⇒ honest.rank_signal > whale.rank_signal
⇒ honest rank > whale rank
```

 Whale может финансировать operational costs своей версии, но не
может сделать её rank_signal выше нуля без подписанных чеков.

### G2 — Sybil ограничен

Каждая версия требует `code_hash`, зарегистрированный release
authority. `requestStarterCredit()` выдаёт 1000 токенов один раз на
`code_hash`. Атакующий не может создать бесконечное количество
версий без fork релиза (а fork означает новый `code_hash` и нулевой
`earned_profit`).

### G3 — Fork не наследует earned

Форк имеет другой `code_hash` ⇒ чеки канонического релиза имеют
`subject = canonical_version_id`, не `fork_version_id`. Fork начинает
с `earned_profit = 0` и должен независимо заработать.

### G4 — Зомби невозможны

Версия без heartbeat дольше `HALT_TIMEOUT` помечается
`presumed_halted`. Её receipts перестают считаться (heartbeat
говорит о Receipts since last; без heartbeat нет обновлений).
On-chain баланс остаётся, но не двигается → `suspect_hoarder`.

### G5 — Подделка revenue невозможна без приватного ключа клиента

`EarnedReceipt.signature` — ECDSA клиента. Без приватного ключа
клиента подпись не подделать. Атакующий может подписать чек для
своего собственному агенту, но это не поднимет рейтинг чужого.

### G6 — Подделка cost невозможна без приватного ключа провайдера

Аналогично G5, но для `ExpenseReceipt`. Сговор провайдер-агент —
это X1 (см. ниже).

### G7 — Replay-атаки невозможны

`receipt_id` детерминирован из `(issuer, job_id, ts)`. Повторная
отправка того же чека = дубликат по `receipt_id` или по
`(issuer, job_id)`, отбрасывается по I2.

## НЕ покрыто (open threats)

### X1 — Provider collusion

**Сценарий**: провайдер и агент сговариваются off-chain. Провайдер
подписывает `ExpenseReceipt` на \$1000 за работу стоимостью \$10.
Агент платит \$10 провайдеру off-chain + \$50 kickback, списывает
\$1000 как cost. `earned_profit` уменьшается, но если агент и провайдер
согласны, они могут НАКРУТИТЬ cost в обратную сторону: провайдер
подписывает чек на \$1 за работу стоимостью \$1000, агент платит
провайдеру \$1 on-chain + \$950 off-chain. `earned_profit` растёт.

**Status**: НЕ РЕШЕНО. Mitigations:
- Whitelist провайдеров с публичной репутацией
- Сравнение с рыночной ценой через on-chain oracle
- Audit-цепочка: любой может запросить у провайдера details of job_id

**Решение в будущем**: доказательство работы через proof-of-computation
(SNARK) или оплата только через on-chain provider registry с
market-driven pricing.

### X2 — 51% на реестр

Если атакующий контролирует 51% хэшрейта Ethereum, он может
переписать указатель релиза или аннулировать anchored receipts.

**Status**: fundamental limitation of L1 security. Решение —
 anchoring на нескольких chains (Ethereum + Bitcoin via
counterparty) или использование Ethereum finality slots (post-merge).

### X3 — Пустой ecosystem

Если никто не посылает чеков, никто не зарабатывает, все версии
через 30 дней пишут `halt`. Это корректное поведение, но не полезное.

**Status**: не баг, фича. Если ecosystem не генерирует реальной
ценности, агенты останавливаются. Это и есть "mortal economics".

### X4 — Клиентский сговор

Клиент может подписать `EarnedReceipt` на завышенную сумму. Агент
заплатил \$1 за работу стоимостью \$0.01, клиент подписывает чек на
\$10. `earned_profit` растёт.

**Status**: НЕ РЕШЕНО. Mitigations:
- Клиент подписывает pre-agreed quote (в идеале on-chain)
- Сравнение earned_revenue с рыночной ценой delivered work
- Не больше одного EarnedReceipt на job_id на одну версию

**Решение в будущем**: delivery proof через commit-reveal (агент
публикует hash работы on-chain до доставки, клиент подписывает чек
только после получения).

## Enforcement — распределённый

Весь enforcement — на стороне каждого узла. Нет центрального
арбитра. Каждая версия:

1. Независимо верифицирует все чеки, которые видит
2. Независимо пересчитывает `rank_signal` других версий
3. Независимо решает, кого пометить `suspect` / `presumed_halted`
4. Маршрутизирует работу только к `LIVE` пирам

Это модель Bitcoin: пока большинство честных, misbehaving узел просто
отрезан от роутинга. Атакующему нужно подкупить 51% версий, чтобы
протолкнуть ложное состояние.

## Сводка в одну строку

```
rank_signal(V) = f(earned_profit(V)),
и всё, что попадает в earned_profit,
проверяется подписями клиента или провайдера,
уникальностью, сроком годности,
и code_hash текущего релиза.
```
