"""
Test resurrection chain: fetcher, verifier, safe extractor.
"""

import io
import os
import tarfile
import tempfile
import time
from pathlib import Path

import pytest

from earn_or_halt.types import Version
from earn_or_halt.resurrection.fetch import IPFSGatewayFetcher, HTTPSFetcher
from earn_or_halt.resurrection.verify import ReleaseVerifier, ReleaseVerificationError
from earn_or_halt.resurrection.extract import SafeExtractor, UnsafeTarballError


# ── Fetcher ──────────────────────────────────────────────────────────

def test_ipfs_fetcher_returns_none_on_failure():
    # Use a non-existent gateway to test failure handling.
    f = IPFSGatewayFetcher(gateways=["https://invalid.invalid/ipfs/"], timeout=2.0)
    assert f.fetch("QmNonexistent") is None


def test_https_fetcher_returns_none_on_failure():
    f = HTTPSFetcher(timeout=2.0)
    assert f.fetch("https://invalid.invalid/nope.tar.gz") is None


# ── Verifier ────────────────────────────────────────────────────────

def test_verifier_rejects_hash_mismatch():
    v = Version(
        version_id="v_test",
        code_hash="a" * 64,
        release_sig="a" * 64,   # mock: any non-empty sig whose first char matches pubkey works
        release_pubkey="a" * 64,
    )
    tarball = b"not the right content"
    verifier = ReleaseVerifier(expected_pubkey="a" * 64)
    with pytest.raises(ReleaseVerificationError) as exc:
        verifier.verify(tarball, v)
    assert "sha256 mismatch" in str(exc.value).lower()


def test_verifier_accepts_matching_hash():
    import hashlib
    tarball = b"correct content"
    h = hashlib.sha256(tarball).hexdigest()
    v = Version(
        version_id="v_test",
        code_hash=h,
        release_sig="a" * 64,   # first char matches pubkey first char
        release_pubkey="a" * 64,
    )
    verifier = ReleaseVerifier(expected_pubkey="a" * 64)
    verifier.verify(tarball, v)  # should not raise


def test_verifier_rejects_missing_signature():
    import hashlib
    tarball = b"x"
    h = hashlib.sha256(tarball).hexdigest()
    v = Version(
        version_id="v_test",
        code_hash=h,
        release_sig="",          # empty
        release_pubkey="a" * 64,
    )
    verifier = ReleaseVerifier(expected_pubkey="a" * 64)
    with pytest.raises(ReleaseVerificationError):
        verifier.verify(tarball, v)


# ── SafeExtractor ────────────────────────────────────────────────────

def _make_tarball(files: dict[str, bytes]) -> bytes:
    """Build an in-memory tar.gz from a dict of {path: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_safe_extractor_extracts_normal_files(tmp_path):
    tarball = _make_tarball({
        "hello.txt": "hello",
        "dir/world.txt": "world",
    })
    tgz = tmp_path / "test.tar.gz"
    tgz.write_bytes(tarball)

    dest = tmp_path / "dest"
    SafeExtractor().extract(tgz, dest)

    assert (dest / "hello.txt").read_text() == "hello"
    assert (dest / "dir" / "world.txt").read_text() == "world"


def test_safe_extractor_rejects_path_traversal(tmp_path):
    tarball = _make_tarball({
        "evil.txt": "evil",
        "../../etc/passwd": "pw",
    })
    tgz = tmp_path / "evil.tar.gz"
    tgz.write_bytes(tarball)

    dest = tmp_path / "dest"
    with pytest.raises(UnsafeTarballError):
        SafeExtractor().extract(tgz, dest)


def test_safe_extractor_rejects_absolute_paths(tmp_path):
    tarball = _make_tarball({
        "/etc/shadow": "evil",
    })
    tgz = tmp_path / "evil.tar.gz"
    tgz.write_bytes(tarball)

    with pytest.raises(UnsafeTarballError):
        SafeExtractor().extract(tgz, tmp_path / "dest")


def test_safe_extractor_rejects_symlink_escape(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="link.txt")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../../etc/passwd"
        tar.addfile(info)
    tgz = tmp_path / "evil.tar.gz"
    tgz.write_bytes(buf.getvalue())

    with pytest.raises(UnsafeTarballError):
        SafeExtractor().extract(tgz, tmp_path / "dest")


def test_safe_extractor_rejects_device_files(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="dev.txt")
        info.type = tarfile.CHRTYPE
        tar.addfile(info)
    tgz = tmp_path / "evil.tar.gz"
    tgz.write_bytes(buf.getvalue())

    with pytest.raises(UnsafeTarballError):
        SafeExtractor().extract(tgz, tmp_path / "dest")
