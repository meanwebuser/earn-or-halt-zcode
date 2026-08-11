# Verification status

Проверка выполнена на свежем shallow clone main в nested package
arena-v0.2.0.

## Выполнено

~~~
python3 -m unittest discover -s tests -v
Ran 64 tests ... OK

sh -n scripts/compile.sh
OK
~~~

Набор состоит из 42 базовых arena tests и 22 tests в
tests/test_v02_hardening.py. В базовой части проверяются ranked/market split,
proof replay, runtime heartbeat, supersede, stale/vacancy и token
conservation. В hardening части отдельно проверяются:

- U1 bond funding/reclaim;
- U2 daily cap и multi-sig;
- U3 commit/reveal;
- U4 verifier-set validation;
- U5 IPFS proof tracking;
- U6 objective market auto-accept;
- U8 median profit;
- U9 stale capital split;
- U10 heartbeat burn.

## Claim audit

Тесты hardening относятся к Python model/arena.py. Solidity
contracts/EohArena.sol содержит additive fields/entrypoints, но не все
hardening правила подключены к базовым transitions:

- registerVersion не собирает VERSION_BOND;
- settleOperatingExpense не применяет DAILY_EXPENSE_CAP или signer threshold;
- heartbeat не принимает ipfs proof и не списывает heartbeat burn;
- createRankedJob использует один verifier, а verifierSet не заполняется;
- openMarketJob не принимает work_verifier_id;
- ejectStale не выполняет lineage half-split;
- allowedSettlementTokens не участвует в transfer validation;
- legacy supersede остаётся single-epoch path.

Поэтому корректная claim boundary: 64 green Python/static tests и additive
reference surface, но не полностью hardened Solidity deployment.

## Compile and deployment limits

scripts/compile.sh pin'ит solc 0.8.36+commit.8a079791 и проверяет checksum.
В текущем окружении solc отсутствовал, поэтому compiler script не запускался
для генерации artifacts; shell syntax проверен отдельно.

Не выполнены security audit, fuzzing, symbolic/formal verification,
testnet/mainnet deployment, live token transaction или production verifier
canary. До этих gates nested arena нельзя использовать с реальными деньгами.
