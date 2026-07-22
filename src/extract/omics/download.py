"""Shared GDC file downloader for the omics extractors.

One dropped connection used to abort a whole 12k-file job (the extractor did a
bare ``urlopen`` with no retry, and a killed process could leave a truncated
file that the ``exists()``-only resume check then treated as complete forever).

This module fixes both:

  * **Retry with backoff** — transient network failures (dropped connections,
    timeouts, 5xx/429) are retried with exponential backoff instead of killing
    the job.
  * **Atomic write** — bytes stream to a ``.part`` sidecar and are renamed into
    place only once complete, so a killed process never leaves a poisoned final
    file.
  * **Integrity check** — the downloaded bytes are verified against the GDC
    ``md5sum``/``file_size`` (from the manifest) before the rename, and the
    resume check re-verifies an existing file rather than trusting its mere
    presence.

The manifest already carries ``md5``/``size`` per file (written by each
extractor's ``write_manifest``); pass them through and integrity is enforced
end to end.
"""

from __future__ import annotations

import hashlib
import http.client
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_DATA_URL = "https://api.gdc.cancer.gov/data"

# Network failures worth retrying: dropped connections, resets, timeouts,
# partial reads. urllib.error.URLError wraps the underlying socket errors.
_TRANSIENT = (
    http.client.RemoteDisconnected,
    http.client.IncompleteRead,
    urllib.error.URLError,
    ConnectionError,
    socket.timeout,
    TimeoutError,
)

# HTTP status codes worth retrying (server-side / rate limiting).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_CHUNK = 1 << 20  # 1 MiB streaming chunk


class VerifyError(ValueError):
    """Raised when downloaded bytes don't match the expected md5/size."""


def verify_file(path: Path, *, md5: str | None = None, size: int | None = None) -> str | None:
    """Return a reason string if *path* fails its integrity check, else None.

    ``size`` is checked first (a cheap ``stat``); ``md5`` only if given (a full
    read). With neither, existence alone is accepted.
    """
    if not path.exists():
        return "missing"
    if size is not None:
        actual = path.stat().st_size
        if actual != int(size):
            return f"size {actual} != {size}"
    if md5:
        h = hashlib.md5()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                h.update(chunk)
        if h.hexdigest() != md5:
            return f"md5 {h.hexdigest()} != {md5}"
    return None


def _fetch_to(tmp_path: Path, url: str, *, timeout: int) -> tuple[int, str]:
    """Stream *url* into *tmp_path*, returning (bytes_written, md5_hexdigest)."""
    req = urllib.request.Request(url)
    h = hashlib.md5()
    written = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp_path.open("wb") as out:
        for chunk in iter(lambda: resp.read(_CHUNK), b""):
            out.write(chunk)
            h.update(chunk)
            written += len(chunk)
    return written, h.hexdigest()


def download_file(
    file_id: str,
    file_name: str,
    out_dir: Path,
    *,
    md5: str | None = None,
    size: int | None = None,
    retries: int = 5,
    timeout: int = 300,
    base_delay: float = 1.0,
) -> Path:
    """Download one GDC file to ``out_dir/{file_id}/{file_name}``.

    Resume-safe and integrity-checked: an existing file is returned only if it
    passes ``verify_file`` (against *md5*/*size* when provided); otherwise it is
    re-fetched. Transient network failures and retryable HTTP statuses are
    retried up to *retries* times with exponential backoff. The download streams
    to a ``.part`` sidecar and is renamed into place only after verification, so
    a killed process never leaves a truncated final file.

    Raises the last exception if every attempt fails, or ``VerifyError`` if the
    bytes never match the expected checksum.
    """
    dest = out_dir / file_id
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / file_name

    # Resume: trust an existing file only if it verifies.
    if out_path.exists() and verify_file(out_path, md5=md5, size=size) is None:
        return out_path

    tmp_path = dest / (file_name + ".part")
    url = f"{_DATA_URL}/{file_id}"
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            written, digest = _fetch_to(tmp_path, url, timeout=timeout)

            # Integrity check before we commit the rename.
            if size is not None and written != int(size):
                raise VerifyError(f"size {written} != {size}")
            if md5 and digest != md5:
                raise VerifyError(f"md5 {digest} != {md5}")

            tmp_path.replace(out_path)  # atomic within the same directory
            return out_path

        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE_STATUS:
                tmp_path.unlink(missing_ok=True)
                raise
            _warn(file_name, attempt, retries, f"HTTP {exc.code}")
        except (_TRANSIENT + (VerifyError,)) as exc:
            last_exc = exc
            _warn(file_name, attempt, retries, type(exc).__name__ + f": {exc}")

        tmp_path.unlink(missing_ok=True)
        if attempt < retries:
            time.sleep(base_delay * (2 ** (attempt - 1)))  # 1,2,4,8,… seconds

    assert last_exc is not None
    raise last_exc


def _warn(file_name: str, attempt: int, retries: int, detail: str) -> None:
    print(
        f"  ! {file_name}: {detail} (attempt {attempt}/{retries})",
        file=sys.stderr, flush=True,
    )
