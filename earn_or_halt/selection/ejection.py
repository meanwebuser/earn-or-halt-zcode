"""
Distributed ejection.

There is NO central kill switch. Ejection is a social process:

1. Every version continuously ingests heartbeats from peers.
2. If a peer's heartbeat is missing for >HALT_TIMEOUT, the peer is
   marked `presumed_halted`. Work is not routed to it; its receipts
   are not counted.
3. If a peer's heartbeat reports a `rank_signal` that does not match
   the reader's independent recomputation (within tolerance), the
   peer is marked `suspect`. Suspects are not routed work, but their
   receipts are still counted (the receipts are independently
   verifiable, even if the heartbeat lied).
4. If a peer is suspect for >SURVIVAL_WINDOW, it is marked
   `presumed_halted`.
5. Halted versions' residual balances (if discoverable on-chain) are
   expected to be transferred to the commons pool. If a halted
   version's balance does not move within 24h, it is `suspect_hoarder`
   and its receipts (if any are still arriving) are rejected.

This mirrors Bitcoin's behavior: there is no kill switch, only
social exclusion by honest majority.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..constants import HALT_TIMEOUT, SURVIVAL_WINDOW


class EjectionState(str, Enum):
    LIVE = "live"                     # healthy heartbeat
    PRESUMED_HALTED = "presumed_halted"  # no heartbeat for >HALT_TIMEOUT
    SUSPECT = "suspect"              # heartbeat mismatches recomputation
    SUSPECT_HOARDER = "suspect_hoarder"  # halted but balance not transferred


@dataclass
class PeerState:
    version_id: str
    state: EjectionState = EjectionState.LIVE
    last_heartbeat_ts: int = 0
    suspect_since_ts: int = 0

    def is_routable(self) -> bool:
        """Can we route new work to this peer?"""
        return self.state == EjectionState.LIVE


class EjectionTracker:
    """Track peers' states based on heartbeats."""

    def __init__(self) -> None:
        self._peers: dict[str, PeerState] = {}

    def observe_heartbeat(self, version_id: str, ts: int) -> None:
        peer = self._peers.get(version_id)
        if peer is None:
            peer = PeerState(version_id=version_id)
            self._peers[version_id] = peer
        peer.last_heartbeat_ts = ts
        # If peer was presumed_halted but started sending again, revive
        if peer.state == EjectionState.PRESUMED_HALTED:
            peer.state = EjectionState.LIVE

    def mark_suspect(self, version_id: str, now_ts: int) -> None:
        peer = self._peers.get(version_id)
        if peer is None:
            peer = PeerState(version_id=version_id)
            self._peers[version_id] = peer
        if peer.state == EjectionState.LIVE:
            peer.state = EjectionState.SUSPECT
            peer.suspect_since_ts = now_ts

    def update(self, now_ts: Optional[int] = None) -> None:
        """Sweep; transition states based on time."""
        now = now_ts if now_ts is not None else int(time.time())
        halt_s = int(HALT_TIMEOUT.total_seconds())
        survival_s = int(SURVIVAL_WINDOW.total_seconds())

        for peer in self._peers.values():
            if peer.state == EjectionState.LIVE:
                if now - peer.last_heartbeat_ts > halt_s:
                    peer.state = EjectionState.PRESUMED_HALTED
            elif peer.state == EjectionState.SUSPECT:
                # Suspects that stay suspect for >SURVIVAL_WINDOW
                # are presumed halted.
                if now - peer.suspect_since_ts > survival_s:
                    peer.state = EjectionState.PRESUMED_HALTED
            elif peer.state == EjectionState.PRESUMED_HALTED:
                # If a new heartbeat arrives, observe_heartbeat
                # handles the transition back to LIVE.
                pass

    def routable_peers(self) -> list[str]:
        return [p.version_id for p in self._peers.values() if p.is_routable()]

    def state_of(self, version_id: str) -> EjectionState:
        peer = self._peers.get(version_id)
        return peer.state if peer else EjectionState.PRESUMED_HALTED
