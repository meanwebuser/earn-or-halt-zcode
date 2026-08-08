"""
Resurrection fetcher — fetch a release tarball from IPFS / HTTPS.

Tries IPFS gateways in order. Falls back to direct HTTPS mirror if
all gateways fail. The fetcher NEVER trusts transport-layer integrity:
the bytes are always re-hashed and re-verified against the on-chain
code_hash and the release ECDSA signature.

This is critical: an attacker who controls a gateway can serve a
modified tarball, but cannot forge the SHA-256 hash or the ECDSA
signature. The verifier (verify.py) catches any tampering before
the tarball is extracted.
"""

from __future__ import annotations

import urllib.request
import urllib.error
from typing import Iterable, Optional

from ..constants import IPFS_GATEWAYS


class IPFSGatewayFetcher:
    """Fetch a content-addressed blob from IPFS via public gateways."""

    def __init__(self, gateways: Iterable[str] = IPFS_GATEWAYS,
                 timeout: float = 15.0) -> None:
        self.gateways = tuple(gateways)
        self.timeout = timeout

    def fetch(self, cid: str) -> Optional[bytes]:
        """Try each gateway in order. Returns first successful bytes."""
        for gw in self.gateways:
            url = gw.rstrip("/") + "/" + cid.lstrip("/")
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as r:
                    if r.status != 200:
                        continue
                    return r.read()
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
        return None

    def fetch_or_raise(self, cid: str) -> bytes:
        b = self.fetch(cid)
        if b is None:
            raise RuntimeError(f"all gateways failed for CID {cid}")
        return b


class HTTPSFetcher:
    """Fetch a release tarball from a direct HTTPS mirror."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> Optional[bytes]:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                if r.status != 200:
                    return None
                return r.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
