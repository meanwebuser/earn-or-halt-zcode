"""
Safe tar extraction.

Tarballs can contain path traversal attacks:
- ../../../etc/passwd
- absolute paths like /etc/shadow
- symlinks pointing outside the extraction root
- hardlinks pointing outside

This module extracts a tarball strictly into a sandboxed directory
and rejects any entry that attempts to escape.

We use Python's tarfile with a custom filter that enforces:
1. All paths are relative.
2. No path component is "..".
3. No absolute paths.
4. Symlinks resolve inside the extraction root.
5. Hardlinks resolve inside the extraction root.
"""

from __future__ import annotations

import os
import tarfile
from pathlib import Path


class UnsafeTarballError(Exception):
    """Raised when a tarball entry attempts a path traversal."""


class SafeExtractor:
    """Extract tarballs safely into a sandboxed directory."""

    def extract(self, tarball_path: str | Path, dest_dir: str | Path) -> None:
        dest = Path(dest_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        with tarfile.open(tarball_path, mode="r:*") as tar:
            for member in tar.getmembers():
                self._check_member(member, dest)
            # Python 3.12+ supports filter='data'; we use 'data' if available,
            # falling back to our manual filter.
            try:
                tar.extractall(path=dest, filter="data")
            except TypeError:
                tar.extractall(path=dest)

    def _check_member(self, member: tarfile.TarInfo, dest: Path) -> None:
        # Reject absolute paths
        if member.name.startswith("/"):
            raise UnsafeTarballError(
                f"absolute path in tarball: {member.name}"
            )
        # Reject ..
        parts = Path(member.name).parts
        if ".." in parts:
            raise UnsafeTarballError(
                f"parent reference in tarball: {member.name}"
            )

        # Resolve the final path inside dest
        final = (dest / member.name).resolve()
        if not str(final).startswith(str(dest)):
            raise UnsafeTarballError(
                f"path escapes extraction root: {member.name}"
            )

        # Check symlinks and hardlinks
        if member.issym() or member.islnk():
            link_target = member.linkname
            if link_target.startswith("/"):
                raise UnsafeTarballError(
                    f"absolute link target: {link_target}"
                )
            target_parts = Path(link_target).parts
            if ".." in target_parts:
                raise UnsafeTarballError(
                    f"parent reference in link target: {link_target}"
                )
            # Verify the link target stays inside dest
            if member.issym():
                link_final = (final.parent / link_target).resolve()
            else:
                link_final = (dest / link_target).resolve()
            if not str(link_final).startswith(str(dest)):
                raise UnsafeTarballError(
                    f"link target escapes root: {link_target}"
                )

        # Reject device files
        if member.isdev():
            raise UnsafeTarballError(
                f"device file in tarball: {member.name}"
            )
