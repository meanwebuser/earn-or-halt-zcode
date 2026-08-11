# EOH Arena v0.2.0 — hardened reference package

Это nested arena package внутри earn-or-halt-zcode. Он содержит копию
Solidity/Python EOH Arena и v0.2 hardening model. Важно различать:

1. базовый EOH Arena flow, который есть в Solidity contract;
2. hardening transitions, которые полно описаны и проверены в
   model/arena.py;
3. additive Solidity storage/entrypoints, часть которых явно оставлена
   minimal/reference и не подключена к базовым entrypoints.

Комментарий в contracts/EohArena.sol называет Python model source of truth
для exact state transitions. Поэтому этот пакет нельзя описывать как
полностью hardened deployed contract.

## Базовый arena flow

Общие правила сохраняются из v0.1:

- AGPL source/image/provenance/runtime metadata проверяются при регистрации;
- ranked jobs получают authorization через immutable Merkle authorizer;
- work verifier возвращает result proof и verified cost;
- market revenue идёт через buyer escrow и не входит в ranked profit;
- supersede сравнивает lineage versions по ranked economy;
- stale ejection меняет protocol status и переводит capital;
- Demo verifiers остаются test-only и не доказывают реальную полезность.

См. [contracts/EohArena.sol](contracts/EohArena.sol),
[model/arena.py](model/arena.py) и [CHANGELOG.md](CHANGELOG.md).

## Hardening matrix: model versus Solidity

| Patch | Python model и тесты | Solidity surface в этом clone |
| --- | --- | --- |
| U1 bond | create/register требуют VERSION_BOND; reclaim после positive epoch; slash на stale. | Есть mappings и reclaimBond, но текущий registerVersion не принимает bond и не заполняет versionBond. End-to-end bond registration не подключён. |
| U2 operator safety | daily expense cap и M-of-N signer checks в model. | Базовый settleOperatingExpense не вызывает cap/multisig checks. |
| U3 commit-reveal | model commit/reveal использует phase/block model; legacy supersede оставлен отдельно. | Additive commitSupersede/revealSupersede есть. Legacy supersede остаётся single-epoch. Solidity хранит timestamp, хотя константы названы blocks; REVEAL_PHASE_BLOCKS не enforcement gate. |
| U4 verifier set | authorization model хранит verifier set и отвергает duplicate ids. | RankedJob содержит поле verifierSet, но createRankedJob принимает один verifier и set не заполняет/не выбирает. |
| U5 retrieval proof | model heartbeat принимает ipfs_proof и обновляет last_ipfs_proof_ts. | Базовый heartbeat не принимает ipfs proof и не обновляет mapping. |
| U6 market auto-accept | model auto-accepts objective proof при work_verifier_id. | Базовый openMarketJob/submitMarketResult не имеют work verifier argument; buyer acceptance остаётся обязательной. |
| U7 uint256 economy | model использует Python integers. | Economy fields — uint256; другие reward/cost/event fields всё ещё имеют отдельные uint128. |
| U8 median | model и additive commit/reveal сравнивают median за PROFIT_WINDOW_EPOCHS = 3. | medianProfit и reveal path есть; legacy supersede использует single-epoch profit. |
| U9 stale split | model делит stale capital между commons и qualifying lineage successor. | Базовый ejectStale переводит весь amount в commons; split не wired в этот entrypoint. |
| U10 heartbeat burn | model списывает HEARTBEAT_BURN из vault и добавляет в commons. | Базовый heartbeat только проверяет runtime proof и timestamp; burn не списывается. |
| U12 token allowlist | model tracks configured token boundary. | allowedSettlementTokens mapping существует, но текущие transfer paths его не используют. |

Такое разделение — часть review surface, а не мелкая реализационная деталь:
green model tests не превращают неполностью подключённые Solidity extensions
в production guarantees.

## Проверка

~~~
python3 -m unittest discover -s tests -v
# 64 tests, OK: 42 base + 22 v0.2 hardening
~~~

В hardening tests отдельно проверяются bond, daily expense cap, multisig,
commit/reveal, verifier set, retrieval proof, market auto-accept, median
profit, stale split и heartbeat burn. Solidity static tests проверяют imports,
delimiters и pinned compiler script; они не deploy'ят контракт.

До compiled bytecode, independent audit, fuzz/formal verification и live
deployment этот nested package остаётся reference model/source. Demo
verifiers и test token нельзя использовать с value.
