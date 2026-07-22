"""Tests for the shared omics downloader and the verify command.

The GDC server is mocked via ``urllib.request.urlopen`` so nothing touches the
network. Covers: retry-with-backoff on transient drops, atomic write, md5/size
verification, and the resume check that re-fetches a corrupted file instead of
trusting its mere presence.
"""

from __future__ import annotations

import hashlib
import http.client
from pathlib import Path

import pytest

from src.extract.omics import download, verify


class _FakeResp:
    """Minimal urlopen response: chunked .read(n) + context manager."""

    def __init__(self, body: bytes):
        self._buf = body

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk, self._buf = self._buf, b""
            return chunk
        chunk, self._buf = self._buf[:n], self._buf[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(bodies, drops=0):
    """Return a urlopen stub that raises RemoteDisconnected `drops` times first."""
    calls = {"n": 0}

    def _open(req, timeout=None):
        calls["n"] += 1
        if calls["n"] <= drops:
            raise http.client.RemoteDisconnected("boom")
        return _FakeResp(bodies)

    _open.calls = calls
    return _open


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(download.time, "sleep", lambda *_: None)


BODY = b"hello world\n" * 100
MD5 = hashlib.md5(BODY).hexdigest()
SIZE = len(BODY)


def test_download_success_writes_and_verifies(tmp_path, monkeypatch):
    monkeypatch.setattr(download.urllib.request, "urlopen", _opener(BODY))
    out = download.download_file("fid", "f.txt", tmp_path, md5=MD5, size=SIZE)
    assert out.read_bytes() == BODY
    assert not (tmp_path / "fid" / "f.txt.part").exists()  # sidecar cleaned


def test_download_retries_transient_then_succeeds(tmp_path, monkeypatch):
    op = _opener(BODY, drops=2)
    monkeypatch.setattr(download.urllib.request, "urlopen", op)
    out = download.download_file("fid", "f.txt", tmp_path, md5=MD5, size=SIZE, retries=5)
    assert out.read_bytes() == BODY
    assert op.calls["n"] == 3  # 2 drops + 1 success


def test_download_gives_up_after_retries(tmp_path, monkeypatch):
    op = _opener(BODY, drops=99)
    monkeypatch.setattr(download.urllib.request, "urlopen", op)
    with pytest.raises(http.client.RemoteDisconnected):
        download.download_file("fid", "f.txt", tmp_path, retries=3)
    assert op.calls["n"] == 3
    assert not (tmp_path / "fid" / "f.txt.part").exists()  # no poisoned partial


def test_download_rejects_bad_md5(tmp_path, monkeypatch):
    monkeypatch.setattr(download.urllib.request, "urlopen", _opener(BODY))
    with pytest.raises(download.VerifyError):
        download.download_file("fid", "f.txt", tmp_path, md5="deadbeef", size=SIZE, retries=2)
    assert not (tmp_path / "fid" / "f.txt").exists()  # never committed


def test_resume_skips_verified_file(tmp_path, monkeypatch):
    op = _opener(BODY)
    monkeypatch.setattr(download.urllib.request, "urlopen", op)
    download.download_file("fid", "f.txt", tmp_path, md5=MD5, size=SIZE)
    assert op.calls["n"] == 1
    # Second call: file already present and valid → no new fetch.
    download.download_file("fid", "f.txt", tmp_path, md5=MD5, size=SIZE)
    assert op.calls["n"] == 1


def test_resume_refetches_corrupted_file(tmp_path, monkeypatch):
    dest = tmp_path / "fid"
    dest.mkdir()
    (dest / "f.txt").write_bytes(b"truncated")  # wrong size — simulates a killed write
    op = _opener(BODY)
    monkeypatch.setattr(download.urllib.request, "urlopen", op)
    out = download.download_file("fid", "f.txt", tmp_path, md5=MD5, size=SIZE)
    assert out.read_bytes() == BODY
    assert op.calls["n"] == 1  # the bad file did NOT satisfy the resume check


def _write_manifest(base: Path, rows):
    base.mkdir(parents=True, exist_ok=True)
    lines = ["id\tfilename\tmd5\tsize\tstate"]
    lines += ["\t".join(r) for r in rows]
    (base / "manifest.tsv").write_text("\n".join(lines) + "\n")


def test_verify_flags_and_deletes_bad(tmp_path):
    base = tmp_path / "methylation"
    _write_manifest(base, [
        ("good", "g.txt", MD5, str(SIZE), "validated"),
        ("trunc", "t.txt", MD5, str(SIZE), "validated"),
        ("gone", "m.txt", MD5, str(SIZE), "validated"),
    ])
    (base / "good").mkdir()
    (base / "good" / "g.txt").write_bytes(BODY)
    (base / "trunc").mkdir()
    (base / "trunc" / "t.txt").write_bytes(b"short")

    tally = verify.verify_dir(base, check_md5=True, delete=True)
    assert tally["ok"] == 1
    assert tally["bad"] == 1
    assert tally["missing"] == 1
    assert not (base / "trunc" / "t.txt").exists()  # deleted for re-fetch


def test_verify_finds_manifest_from_parent(tmp_path):
    base = tmp_path / "TCGA_X" / "expression"
    _write_manifest(base, [("good", "g.txt", MD5, str(SIZE), "validated")])
    (base / "good").mkdir()
    (base / "good" / "g.txt").write_bytes(BODY)
    tally = verify.verify_dir(tmp_path / "TCGA_X", check_md5=False, delete=False)
    assert tally["ok"] == 1
