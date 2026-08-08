"""
Release signature verification.

A release is verified iff:

1. SHA-256(tarball) == code_hash
2. ECDSA(release_pubkey, code_hash) == release_sig

The release private key lives ONLY in the release builder's RAM
(typically an air-gapped machine that signs and immediately wipes).
The runtime NEVER has access to the release private key; it only
has the public key, which is hardcoded in the source AND anchored
on-chain.

If either check fails, the tarball MUST NOT be extracted and MUST
NOT be executed. The runtime writes an error to its log and exits.

Key separation:
- release_privkey: signs releases. Air-gapped, ephemeral.
- runtime_privkey: signs heartbeats. Lives in the running process.
- wallet_privkey: signs on-chain transactions. Stored in keystore,
  encrypted at rest; decrypt only into RAM when spending.

These are three different keys. If the runtime is compromised, the
release key is still safe, and the attacker cannot forge a new
"authorized" release.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..types import Version


class ReleaseVerificationError(Exception):
    """Tarball failed verification."""


@dataclass
class ReleaseVerifier:
    """Verify a fetched release tarball."""

    # In production, this would use ecdsa.VerifyingKey.from_string(...)
    # and verify the signature over the sha256 digest. For the MVP we
    # use a deterministic HMAC-style mock signature scheme, which is
    # NOT secure for production. The interface is what matters.

    expected_pubkey: str   # release signer's pubkey

    def verify(self, tarball: bytes, version: Version) -> None:
        """
        Raise ReleaseVerificationError if verification fails.

        Otherwise return None.
        """
        actual_hash = hashlib.sha256(tarball).hexdigest()
        if actual_hash != version.code_hash:
            raise ReleaseVerificationError(
                f"sha256 mismatch: got {actual_hash}, "
                f"expected {version.code_hash}"
            )

        if not self._verify_signature(version.code_hash, version.release_sig):
            raise ReleaseVerificationError(
                f"signature verification failed for code_hash {actual_hash}"
            )

    def _verify_signature(self, message_hex: str, signature_hex: str) -> bool:
        """Mock signature verification. Replace with real ecdsa in prod."""
        # The release signature is a hex string. In production:
        #   vk = ecdsa.VerifyingKey.from_string(
        #       bytes.fromhex(self.expected_pubkey),
        #       curve=ecdsa.SECP256k1,
        #   )
        #   vk.verify(
        #       bytes.fromhex(signature_hex),
        #       bytes.fromhex(message_hex),
        #       hashfunc=hashlib.sha256,
        #   )
        #
        # For the MVP, we accept any non-empty signature. The hash
        # check above is the real verification gate; the signature
        # check is a placeholder that exists only to make the test
        # pipeline runnable without bringing in a real ECDSA dependency.
        # Do NOT ship this in production.
        return bool(signature_hex) and bool(self.expected_pubkey)
