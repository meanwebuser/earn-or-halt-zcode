"""
Sign a release tarball with the release private key.

USAGE:
    python tools/release_sign.py <tarball_path> <release_privkey_hex>

Outputs JSON to stdout:
    {
      "code_hash": "<sha256 hex>",
      "release_sig": "<signature hex>",
      "release_pubkey": "<pubkey hex>",
      "tarball_size": <int>
    }

SECURITY:
    The release private key MUST live only in RAM. Generate it on an
    air-gapped machine, sign the release, immediately wipe.

    # Generate key (mock HMAC-based; replace with ecdsa in prod):
    openssl rand -hex 32 > /tmp/release_privkey_hex
    chmod 600 /tmp/release_privkey_hex

    # Sign:
    python tools/release_sign.py release.tar.gz $(cat /tmp/release_privkey_hex)

    # Wipe:
    shred -u /tmp/release_privkey_hex

    # Publish pubkey:
    # The pubkey is derived from the privkey via a one-way function
    # (mock: SHA-256 of privkey). In production, use ecdsa to derive
    # the VerifyingKey and serialize it.
"""

import hashlib
import json
import sys
from pathlib import Path


def derive_pubkey_mock(privkey_hex: str) -> str:
    """Mock pubkey derivation. Replace with real ecdsa in production."""
    return hashlib.sha256(bytes.fromhex(privkey_hex)).hexdigest()


def sign_mock(message_hex: str, privkey_hex: str) -> str:
    """Mock signature. Replace with real ecdsa in production."""
    import hmac
    return hmac.new(
        bytes.fromhex(privkey_hex),
        bytes.fromhex(message_hex),
        hashlib.sha256,
    ).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    tarball_path = Path(sys.argv[1])
    privkey_hex = sys.argv[2].strip()

    if not tarball_path.exists():
        print(f"error: tarball not found: {tarball_path}", file=sys.stderr)
        return 1

    tarball = tarball_path.read_bytes()
    code_hash = hashlib.sha256(tarball).hexdigest()
    release_sig = sign_mock(code_hash, privkey_hex)
    release_pubkey = derive_pubkey_mock(privkey_hex)

    out = {
        "code_hash": code_hash,
        "release_sig": release_sig,
        "release_pubkey": release_pubkey,
        "tarball_size": len(tarball),
        "tarball_path": str(tarball_path),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
