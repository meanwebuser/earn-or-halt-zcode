"""
Verify a release tarball against a published release pointer.

USAGE:
    python tools/release_verify.py <tarball_path> <release_pubkey_hex> <expected_code_hash> <expected_release_sig>

Outputs "OK" to stdout if verification passes; non-zero exit on failure.

This is a thin CLI wrapper around earn_or_halt.resurrection.verify.
"""

import sys
from pathlib import Path

from earn_or_halt.resurrection.verify import (
    ReleaseVerifier, ReleaseVerificationError,
)
from earn_or_halt.types import Version


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2

    tarball_path = Path(sys.argv[1])
    release_pubkey = sys.argv[2]
    expected_code_hash = sys.argv[3]
    expected_release_sig = sys.argv[4]

    if not tarball_path.exists():
        print(f"error: tarball not found: {tarball_path}", file=sys.stderr)
        return 1

    tarball = tarball_path.read_bytes()
    version = Version(
        version_id="verify_target",
        code_hash=expected_code_hash,
        release_sig=expected_release_sig,
        release_pubkey=release_pubkey,
    )

    verifier = ReleaseVerifier(expected_pubkey=release_pubkey)
    try:
        verifier.verify(tarball, version)
    except ReleaseVerificationError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
