"""
Resurrection seed — the 7-step bootstrap that brings a halted agent
back to life using a new pinned release.

Steps:

  1. Query Blockscout for the release pointer contract's current value.
     The contract stores: (code_hash, ipfs_cid, release_pubkey, ts).
  2. Resolve the IPFS CID via multiple public gateways (fallback).
  3. Download the tarball.
  4. Verify SHA-256(tarball) == code_hash from the contract.
  5. Verify ECDSA(release_pubkey, code_hash) == release_sig.
  6. Safe-extract the tarball into a fresh sandbox directory.
  7. Exec the entrypoint of the new release.

The seed itself is a tiny piece of code (~200 LOC) that lives outside
the agent's release cycle. It is the only code that the runtime
"trusts" — everything else is verified.

The seed does NOT have the release private key. It only has the
release public key (hardcoded) and the Blockscout RPC endpoint
(configurable per network).

If the seed is compromised, an attacker can:
- Extract the wallet private key from RAM and steal funds.
- Read the agent's state and history.
- Send malicious heartbeats.

But an attacker CANNOT:
- Forge a new release (no release private key).
- Modify the next release's code (the new release is independently
  signed and the seed verifies the signature before exec).
- Survive past the next release cycle (the new release can pin
  new pubkeys, change the wallet key, etc.).

This is exactly the "Resilient code. Mortal economics." distinction.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..types import Version
from ..constants import (
    RELEASE_POINTER_CONTRACT,
    IPFS_GATEWAYS,
)
from .fetch import IPFSGatewayFetcher, HTTPSFetcher
from .verify import ReleaseVerifier, ReleaseVerificationError
from .extract import SafeExtractor, UnsafeTarballError


@dataclass(frozen=True)
class ReleasePointer:
    """Pointer as read from the on-chain contract."""

    code_hash: str
    ipfs_cid: str
    release_pubkey: str
    ts: int
    https_mirror: Optional[str] = None  # optional fallback URL


class PointerFetchError(Exception):
    """Could not fetch release pointer from RPC."""


class ResurrectionSeed:
    """The 7-step resurrection pipeline."""

    def __init__(
        self,
        release_pubkey: str,
        rpc_url: str = "https://eth.llamarpc.com",
        pointer_contract: str = RELEASE_POINTER_CONTRACT,
    ) -> None:
        self.verifier = ReleaseVerifier(expected_pubkey=release_pubkey)
        self.ipfs_fetcher = IPFSGatewayFetcher(IPFS_GATEWAYS)
        self.https_fetcher = HTTPSFetcher()
        self.rpc_url = rpc_url
        self.pointer_contract = pointer_contract

    # ── Step 1: query pointer ─────────────────────────────────────────

    def fetch_pointer(self) -> ReleasePointer:
        """
        Query the Blockscout/Eth RPC for the current release pointer.

        In production this would call:
          eth_call to pointer_contract.readPointer()

        For the MVP we read from a local JSON file that simulates the
        contract's storage, OR fall back to a hardcoded value if the
        env var EOH_POINTER_FILE is set.
        """
        pointer_file = os.environ.get("EOH_POINTER_FILE")
        if pointer_file and Path(pointer_file).exists():
            data = json.loads(Path(pointer_file).read_text())
            return ReleasePointer(
                code_hash=data["code_hash"],
                ipfs_cid=data["ipfs_cid"],
                release_pubkey=data["release_pubkey"],
                ts=data["ts"],
                https_mirror=data.get("https_mirror"),
            )
        # No pointer file: use a hardcoded placeholder for testing.
        # In production, replace with a real eth_call.
        raise PointerFetchError(
            "no EOH_POINTER_FILE set and no live RPC integration in MVP"
        )

    # ── Steps 2-3: fetch tarball ──────────────────────────────────────

    def fetch_tarball(self, pointer: ReleasePointer) -> bytes:
        b = self.ipfs_fetcher.fetch(pointer.ipfs_cid)
        if b is not None:
            return b
        if pointer.https_mirror:
            b = self.https_fetcher.fetch(pointer.https_mirror)
            if b is not None:
                return b
        raise RuntimeError(
            f"failed to fetch tarball for CID {pointer.ipfs_cid}"
        )

    # ── Steps 4-5: verify ─────────────────────────────────────────────

    def build_version(self, pointer: ReleasePointer) -> Version:
        """Construct a Version object from the on-chain pointer."""
        # The release_sig is stored alongside the pointer in the
        # contract; for the MVP we read it from the same JSON file.
        pointer_file = os.environ.get("EOH_POINTER_FILE")
        if not pointer_file:
            raise PointerFetchError("EOH_POINTER_FILE not set")
        data = json.loads(Path(pointer_file).read_text())
        return Version(
            version_id=data.get("version_id", f"v{pointer.ts}"),
            code_hash=pointer.code_hash,
            release_sig=data.get("release_sig", ""),
            release_pubkey=pointer.release_pubkey,
        )

    def verify(self, tarball: bytes, version: Version) -> None:
        try:
            self.verifier.verify(tarball, version)
        except ReleaseVerificationError as e:
            # Critical: do not proceed. Log and exit.
            print(f"[resurrection] verification FAILED: {e}", file=sys.stderr)
            raise

    # ── Step 6: extract ───────────────────────────────────────────────

    def extract(self, tarball: bytes, dest_dir: Path) -> None:
        tmp = dest_dir.parent / f"{dest_dir.name}.tar.gz"
        tmp.write_bytes(tarball)
        try:
            SafeExtractor().extract(tmp, dest_dir)
        except UnsafeTarballError as e:
            print(f"[resurrection] unsafe tarball: {e}", file=sys.stderr)
            raise
        finally:
            tmp.unlink(missing_ok=True)

    # ── Step 7: exec ──────────────────────────────────────────────────

    def exec_entrypoint(self, release_dir: Path,
                        entrypoint: str = "earn_or_halt/runtime.py") -> int:
        """Exec the new release. Returns exit code."""
        entry = release_dir / entrypoint
        if not entry.exists():
            raise FileNotFoundError(f"entrypoint not found: {entry}")
        # In production, exec() replaces the current process so the
        # seed's memory is wiped. Here we use subprocess for testability.
        return subprocess.call([sys.executable, str(entry)])

    # ── Orchestration ─────────────────────────────────────────────────

    def run(self, dest_dir: Optional[Path] = None) -> int:
        """Execute the full 7-step pipeline. Returns entrypoint exit code."""
        if dest_dir is None:
            dest_dir = Path(tempfile.mkdtemp(prefix="eoh_release_"))

        print(f"[resurrection] step 1: fetch pointer")
        pointer = self.fetch_pointer()
        print(f"[resurrection] pointer: {pointer}")

        print(f"[resurrection] step 2-3: fetch tarball (CID={pointer.ipfs_cid})")
        tarball = self.fetch_tarball(pointer)

        print(f"[resurrection] step 4-5: verify SHA-256 + ECDSA")
        version = self.build_version(pointer)
        self.verify(tarball, version)

        print(f"[resurrection] step 6: safe-extract to {dest_dir}")
        self.extract(tarball, dest_dir)

        print(f"[resurrection] step 7: exec entrypoint")
        return self.exec_entrypoint(dest_dir)
