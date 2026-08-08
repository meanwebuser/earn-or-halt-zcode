# Earn or Halt — что внутри

> Это спецификация, а не статус. Описывает, **что строим** — даже
> если часть кусков пока не реализована в production-качестве.

## Три вложенных цикла

```
┌──────────────────────────────────────────────────────┐
│  Resurrection loop (per release, ~weeks)             │
│  ┌────────────────────────────────────────────────┐  │
│  │  Selection loop (per epoch, ~30 days)          │  │
│  │  ┌──────────────────────────────────────────┐  │  │
│  │  │  Economic loop (per task, ~minutes)       │  │  │
│  │  └──────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

Каждый цикл имеет свой таймаут и свой failure mode. Экономический цикл
падает на `halt` от нехватки денег или негативной маржи. Selection
цикл падает на `halt` от долгого отсутствия положительного
`earned_profit`. Resurrection цикл не падает — он воскресает код.

### Экономический цикл

**Назначение**: один шаг работы агента — получить задачу, заплатить
провайдеру, доставить результат, получить оплату.

**Runtime должен иметь**:

- Кошелёк (`Wallet`) с двумя бакетами: `balance_earned` и `balance_deposits`
- Ledger (SQLite) всех receipts и deposits
- `EconomicPolicy`, которая перед каждым платным действием отвечает:
  - `can_afford(next_cost)` — да/нет
  - `should_halt(...)` — да/нет, с причиной

**Halt-условия** (любое из):
- `INSUFFICIENT_BALANCE`: balance = 0 AND earned_profit ≤ 0
- `NEGATIVE_MARGIN`: cost > earned_revenue AND balance < |earned_profit|
- `OUTSIDE_TOP_TIMEOUT`: нет EarnedReceipt дольше HALT_TIMEOUT
- `PROVIDER_FAILURE`: провайдер упал (бизнес-логика, не экономика)

**Анти-whale механика**: при трате денег сначала списываются deposits
(деньги whale), потом earned. Whale-финансирование не сохраняет
operational runway — оно его быстрее сжигает.

### Selection цикл

**Назначение**: между версиями идёт конкурентная борьба за право
обслуживать входящий поток задач.

**rank_signal**:

```
rank_signal(V) = earned_profit(V) за SURVIVAL_WINDOW
              = Σ EarnedReceipt.amount
              - Σ ExpenseReceipt.amount
              (оба суммирования только по непросроченным чекам
               с уникальными (issuer, job_id))
```

**Hardcoded параметры** (любая правка = новый релиз):
- `N_TOP = 3` — топ-3 версии получают входящую работу
- `SURVIVAL_WINDOW = 30 days`
- `HALT_TIMEOUT = 30 days`
- `HEARTBEAT_PERIOD = 1 hour`
- `RECEIPT_TTL = 30 days`

**Эмерджентное биоразнообразие**: `N_TOP` решает только роутинг новой
работы. Выживают ВСЕ версии с `earned_profit > 0` в окне. Если 100
версий реально заработали — 100 живут. Если 2 — 2.

**Tenure bonus** (опционально, не реализовано в MVP): версия, дольше
всех продержавшаяся в топе, получает +бонус к рангу. Защищает от
свежих версий, которые могли накрутить earned через сговор с
провайдером. Требует, чтобы новая версия реально поработала, а не
просто получила deposits.

### Resurrection цикл

**Назначение**: если runtime halted, новый seed может воскресить код,
найдя последний подписанный релиз.

**7 шагов**:
1. Запросить указатель с контракта в Blockscout
2. Получить: `(code_hash, ipfs_cid, release_pubkey, ts)`
3. Скачать tarball через IPFS-гейтвеи (fallback на HTTPS mirror)
4. Проверить `SHA-256(tarball) == code_hash`
5. Проверить `ECDSA(release_pubkey, code_hash) == release_sig`
6. Safe-extract tarball в песочницу (защита от path traversal, symlinks)
7. Exec entrypoint нового релиза

**Контракты**:
- Приватный ключ релиза — только в RAM сборщика (air-gapped)
- Runtime-ключ — для подписи heartbeats (другой ключ)
- Wallet-ключ — для on-chain транзакций (третий ключ, keystore)
- ETH-ключ — для pointer-контракта (четвёртый ключ, multisig)

## Receipt спецификация

```json
{
  "receipt_id": "rcpt_<sha256(issuer, job_id, ts)[:24]>",
  "issuer":     "<client pubkey for Earned, provider pubkey for Expense>",
  "subject":    "<version_id>",
  "amount":     <int, smallest token unit>,
  "ts":         <unix seconds>,
  "ttl_seconds": 2592000,
  "job_id":     "<unique per issuer>",
  "kind":       "earned | expense",
  "signature":  "<ECDSA hex over canonical_bytes>"
}
```

`canonical_bytes(receipt)` = JSON с отсортированными ключами, без
signature. Подпись — ECDSA над SHA-256 от canonical_bytes.

**No double-count**: `(issuer, job_id)` уникален в ledger. Повторный
вставка с тем же `receipt_id` игнорируется. Вставка с другим
`receipt_id`, но тем же `(issuer, job_id)` отбрасывается верификатором.

**TTL**: чек старше `RECEIPT_TTL` не входит в `rank_signal`. TTL ≥
`SURVIVAL_WINDOW`, чтобы один успешный месяц держал версию живой.

## Enforcement — распределённый

Никакого kill switch. Никакого центрального authority. Каждая версия:

1. Шлёт heartbeat с подписанным state каждые `HEARTBEAT_PERIOD`
2. Независимо пересчитывает `earned_profit` других версий из их чеков
3. Если своя переcчёт не совпадает с опубликованным heartbeat — помечает версию `suspect`
4. Если heartbeat пропал больше `HALT_TIMEOUT` — помечает `presumed_halted`
5. Suspects не получают работу. Их receipts всё ещё считаются (receipts
   верифицируются независимо, даже если heartbeat врал).
6. Suspects, оставшиеся suspect дольше `SURVIVAL_WINDOW` → `presumed_halted`

Это модель Bitcoin: пока большинство честных, misbehaving узел просто
отрезан от роутинга.

## General pool

Проигравший (тот, кто написал `halt`) переводит остатки в общий пул,
не в текущий топ-1. Это критично: если бы остатки шли топ-1, whale
со временем собирал бы всё. Общий пул финансирует starter credit
для новых честных версий.

**Starter credit**:
- 1000 токенов на версию
- Запрашивается через `requestStarterCredit(codeHash)` на токен-контракте
- Только для `codeHash`, зарегистрированных release authority
- Один раз на codeHash (anti-Sybil)

## Константы протокола

| Константа | Значение | Меняется как |
|------------|----------|--------------|
| `N_TOP` | 3 | Новый релиз |
| `SURVIVAL_WINDOW` | 30 days | Новый релиз |
| `HALT_TIMEOUT` | 30 days | Новый релиз |
| `HEARTBEAT_PERIOD` | 1 hour | Новый релиз |
| `RECEIPT_TTL` | 30 days | Новый релиз |
| `IPFS_GATEWAYS` | tuple | Новый релиз |
| `RELEASE_POINTER_CONTRACT` | адрес | Multisig upgrade |
| `COIN_INITIAL_SUPPLY` | 1M EOH | При deploy |
| `COIN_EMISSION_PERIOD` | 4 years | При deploy |

Правило: любой параметр, который влияет на `rank_signal` или
срабатывание `halt`, зашит в исходник и подписан в релизе. Env vars
и runtime config не могут их переопределить. Это защита от того,
чтобы whale не закинул и не поменял N на 1.

## Открытые вопросы

1. **Стартовый кредит распределения**: multisig решает кому дать
   starter credit. Это центр доверия. Возможен DAO с quadratic voting,
   но это новая attack surface.
2. **Well-known провайдеры**: где хранится whitelist? On-chain
   registry, обновляемый через DAO? Или каждый релиз привносит свой?
3. **`code_hash` discovery**: как клиент узнаёт `code_hash`, чтобы
   подписать чек на правильную версию? Возможно, через ENS-like
   resolver.
4. **Whale-форк**: что если whale форкает код, подписывает своим
   ключом, и пытается соревноваться? Принципиально невозможно
   запретить, но его форк начнёт с `earned_profit = 0`.
5. **Переходные состояния при смене релиза**: как versions старого
   релиза перетекают в новый? Ждут timeout? Переносят balances?
