"""
Test selection cycle: rank, heartbeat, ejection.
"""

import time

import pytest

from earn_or_halt.types import Version, Heartbeat
from earn_or_halt.wallet import Wallet
from earn_or_halt.ledger import Ledger
from earn_or_halt.receipts.store import ReceiptStore
from earn_or_halt.selection.rank import Ranker
from earn_or_halt.selection.heartbeat import HeartbeatSender, HeartbeatReader
from earn_or_halt.selection.ejection import EjectionTracker, EjectionState
from earn_or_halt.constants import HALT_TIMEOUT


@pytest.fixture
def ledger(tmp_path):
    return Ledger(str(tmp_path / "test.db"))


def make_version(vid: str) -> Version:
    return Version(
        version_id=vid,
        code_hash=("a" * 60) + vid[-4:].rjust(4, "0"),
        release_sig="b" * 64,
        release_pubkey="c" * 64,
    )


def test_rank_signal_only_uses_earned_profit(ledger):
    """
    CRITICAL: deposits must NOT influence rank.
    """
    store = ReceiptStore(ledger)
    ranker = Ranker(store)

    v_honest = make_version("honest")
    v_whale = make_version("whale")
    ledger.record_version(v_honest)
    ledger.record_version(v_whale)

    # Honest: earned 100, cost 0, balance 100
    from earn_or_halt.types import EarnedReceipt
    from earn_or_halt.constants import RECEIPT_TTL
    r = EarnedReceipt(
        receipt_id="e_honest_1",
        issuer="client1", subject="honest", amount=100,
        ts=int(time.time()), ttl_seconds=int(RECEIPT_TTL.total_seconds()),
        signature="deadbeef", job_id="j1",
    )
    ledger.ingest_receipt(r)

    # Whale: balance 1_000_000 from deposits, but earned_revenue = 0
    rows = ranker.rank(
        versions=[v_honest, v_whale],
        wallet_balances={"honest": 100, "whale": 1_000_000},
    )

    # Honest should be rank 1, whale should be rank 2 (or unranked)
    # but more importantly, honest's rank_signal > whale's rank_signal.
    honest_row = next(r for r in rows if r.version.version_id == "honest")
    whale_row = next(r for r in rows if r.version.version_id == "whale")

    assert honest_row.rank_signal == 100
    assert whale_row.rank_signal == 0
    assert honest_row.rank_signal > whale_row.rank_signal
    assert honest_row.rank == 1


def test_top_n_routing_returns_top_3(ledger):
    store = ReceiptStore(ledger)
    ranker = Ranker(store)

    from earn_or_halt.types import EarnedReceipt
    from earn_or_halt.constants import RECEIPT_TTL

    versions = []
    for i in range(5):
        v = make_version(f"v{i}")
        versions.append(v)
        ledger.record_version(v)
        r = EarnedReceipt(
            receipt_id=f"e_v{i}_1",
            issuer="client1", subject=f"v{i}", amount=100 * (i + 1),
            ts=int(time.time()), ttl_seconds=int(RECEIPT_TTL.total_seconds()),
            signature="deadbeef", job_id=f"j{i}",
        )
        ledger.ingest_receipt(r)

    rows = ranker.rank(
        versions=versions,
        wallet_balances={f"v{i}": 100 * (i + 1) for i in range(5)},
    )
    top = ranker.top_n(rows)
    assert len(top) == 3
    # Highest earned first
    assert top[0].version.version_id == "v4"
    assert top[1].version.version_id == "v3"
    assert top[2].version.version_id == "v2"


def test_emergent_survival_all_positive_earners_alive(ledger):
    """Versions with positive earned_profit stay alive regardless of rank."""
    store = ReceiptStore(ledger)
    ranker = Ranker(store)

    from earn_or_halt.types import EarnedReceipt
    from earn_or_halt.constants import RECEIPT_TTL

    versions = []
    for i in range(5):
        v = make_version(f"v{i}")
        versions.append(v)
        ledger.record_version(v)
        # All earn 10, except v0 which earns 0
        amt = 10 if i > 0 else 0
        if amt > 0:
            r = EarnedReceipt(
                receipt_id=f"e_v{i}_1",
                issuer="client1", subject=f"v{i}", amount=amt,
                ts=int(time.time()), ttl_seconds=int(RECEIPT_TTL.total_seconds()),
                signature="deadbeef", job_id=f"j{i}",
            )
            ledger.ingest_receipt(r)

    rows = ranker.rank(versions=versions, wallet_balances={})
    alive = ranker.alive_versions(rows)
    alive_ids = {r.version.version_id for r in alive}

    assert "v1" in alive_ids
    assert "v2" in alive_ids
    assert "v3" in alive_ids
    assert "v4" in alive_ids
    assert "v0" not in alive_ids


def test_heartbeat_sender_signs():
    v = make_version("v1")
    w = Wallet(version_id="v1")
    w.earned_revenue_total = 100
    w.balance_earned = 100
    sender = HeartbeatSender(runtime_secret=b"x" * 32)
    hb = sender.build(version=v, wallet=w, receipt_ids_since_last=["r1", "r2"])
    assert hb.signature
    assert hb.earned_revenue == 100
    assert hb.rank_signal == 100.0


def test_heartbeat_reader_tracks_alive():
    v = make_version("v1")
    reader = HeartbeatReader()
    hb = Heartbeat(
        version=v, ts=int(time.time()),
        earned_revenue=100, cost=50, balance=50, rank_signal=50.0,
        receipt_ids_since_last=["r1"],
    )
    reader.ingest(hb)
    assert reader.is_alive("v1")


def test_heartbeat_reader_marks_dead_after_timeout():
    """A version whose heartbeat is older than HALT_TIMEOUT is not alive."""
    v = make_version("v1")
    reader = HeartbeatReader()
    old_ts = int(time.time()) - int(HALT_TIMEOUT.total_seconds()) - 1
    hb = Heartbeat(
        version=v, ts=old_ts,
        earned_revenue=100, cost=50, balance=50, rank_signal=50.0,
    )
    reader.ingest(hb)
    assert not reader.is_alive("v1")


def test_heartbeat_reader_ignores_old_heartbeat():
    """A newer heartbeat should not be overwritten by an older one."""
    v = make_version("v1")
    reader = HeartbeatReader()
    recent = Heartbeat(
        version=v, ts=int(time.time()),
        earned_revenue=100, cost=50, balance=50, rank_signal=50.0,
    )
    reader.ingest(recent)

    old_ts = int(time.time()) - int(HALT_TIMEOUT.total_seconds()) - 1
    old_hb = Heartbeat(
        version=v, ts=old_ts,
        earned_revenue=0, cost=0, balance=0, rank_signal=0.0,
    )
    reader.ingest(old_hb)  # should be ignored
    assert reader.is_alive("v1")  # recent still wins


def test_ejection_transitions():
    tracker = EjectionTracker()
    tracker.observe_heartbeat("v1", ts=int(time.time()))
    assert tracker.state_of("v1") == EjectionState.LIVE

    # Old heartbeat → presumed halted
    old_ts = int(time.time()) - int(HALT_TIMEOUT.total_seconds()) - 1
    tracker.observe_heartbeat("v2", ts=old_ts)
    tracker.update()
    assert tracker.state_of("v2") == EjectionState.PRESUMED_HALTED

    # v1 still routable
    assert "v1" in tracker.routable_peers()
    # v2 not routable
    assert "v2" not in tracker.routable_peers()


def test_ejection_revives_on_new_heartbeat():
    tracker = EjectionTracker()
    old_ts = int(time.time()) - int(HALT_TIMEOUT.total_seconds()) - 1
    tracker.observe_heartbeat("v1", ts=old_ts)
    tracker.update()
    assert tracker.state_of("v1") == EjectionState.PRESUMED_HALTED

    tracker.observe_heartbeat("v1", ts=int(time.time()))
    assert tracker.state_of("v1") == EjectionState.LIVE
