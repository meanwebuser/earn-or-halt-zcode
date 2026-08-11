# Earn or Halt — философия и текущая граница

Философия Earn or Halt: код может быть resilient, но экономическое право на
следующий цикл нужно зарабатывать. В zcode это выражено несколькими
соседними модулями, а не одним готовым distributed protocol.

## Экономика

Wallet хранит два bucket'а: EarnedReceipt balance и Deposit balance.
Expense сначала списывает deposits, затем earned balance. Ranker отдельно
считает receipts за SURVIVAL_WINDOW = 30 дней:

~~~
rank_signal(version) = earned revenue - expense
~~~

Deposit повышает runway, но не rank. N_TOP = 3 влияет только на routing;
positive earners вне top-three остаются alive в модели.

Экономическая policy проверяет affordability и локальные halt conditions:
нулевой balance без прибыли, negative margin при недостаточном runway и
старый last-positive timestamp. Это правила Wallet/Policy, а не блокчейн
consensus.

## Receipts — интерфейс, не готовая криптография

EarnedReceipt и ExpenseReceipt описывают, какая сторона должна была бы
подтвердить деньги. В текущем коде:

- ReceiptVerifier применяет expiry, positive amount, optional whitelist,
  duplicate guard и non-empty signature;
- Provider.sign — HMAC-style mock helper;
- ReceiptVerifier не сверяет подпись с issuer public key;
- client payment в Runtime._simulate_client_payment подписывается mock
  runtime secret и прямо помечен как production substitution point.

Поэтому философская формула честно ограничена локальной моделью. Она не
является доказательством независимой оплаты или provider cost.

## Три lifecycle слоя

1. Economic cycle — quote, affordability, mock provider expense, simulated
   earned payment и policy check.
2. Selection cycle — rank aggregation, heartbeat records и ejection helper.
3. Resurrection cycle — pointer file, fetch, hash/signature gate, safe
   extraction и subprocess entrypoint.

Интегрированный CLI демонстрирует только первый слой плюс self-heartbeat в
памяти. Selection и resurrection имеют отдельные unit tests, но не соединены
в public network loop.

## Code may resurrect; economics may halt

ResurrectionSeed проверяет bytes release tarball до extraction. Однако
pointer в MVP читается из local JSON file, live RPC integration отсутствует,
а signature verifier — placeholder, принимающий любую непустую signature.
Это честный prototype boundary, не production supply-chain guarantee.

Смысл проекта сохраняется именно при такой маркировке: не называть
симуляцию cryptographic proof и не называть локальный stop механизмом,
которого нет в runtime.
