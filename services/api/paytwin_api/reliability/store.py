"""Durable, fail-closed JSON evidence store for Reliability Lab runs.

Runs remain small v1 evidence artifacts, but a missing or unreadable artifact must
never be interpreted as a clean verification result. Callers therefore receive a
typed error and can expose an ``UNKNOWN`` release gate instead of a false READY.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import tempfile
import threading
from collections.abc import Iterator


class EvidenceStoreError(RuntimeError):
    """Base error for evidence that cannot safely be read or written."""


class EvidenceMissing(EvidenceStoreError):
    """No evidence artifact exists yet."""


class EvidenceCorrupt(EvidenceStoreError):
    """Evidence exists but is not a valid run list."""


class EvidenceWriteError(EvidenceStoreError):
    """A run could not be durably written."""


_LOCK = threading.Lock()
_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "reliability"


def _path() -> pathlib.Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / "runs.json"


@contextlib.contextmanager
def _process_lock(directory: pathlib.Path) -> Iterator[None]:
    """Serialize writers across processes when flock is available.

    ``os.replace`` below is the durability boundary; the file lock avoids the
    lost-update race between two API workers. The threading lock remains a
    harmless fallback for platforms without ``fcntl``.
    """
    lock_path = directory / ".runs.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl = None
    try:
        try:
            import fcntl as _fcntl  # POSIX deployment target (Linux/macOS)

            fcntl = _fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows fallback
            pass
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _validate_runs(value: object, path: pathlib.Path) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(run, dict) for run in value):
        raise EvidenceCorrupt(f"reliability evidence at {path} is not a list of runs")
    return value


def load_runs(*, allow_missing: bool = False) -> list[dict]:
    """Read evidence explicitly; never silently substitute an empty history."""
    p = _path()
    if not p.exists():
        if allow_missing:
            return []
        raise EvidenceMissing(f"reliability evidence is missing: {p}")
    try:
        raw = p.read_text(encoding="utf-8")
        return _validate_runs(json.loads(raw), p)
    except EvidenceStoreError:
        raise
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EvidenceCorrupt(f"reliability evidence is unreadable: {p}") from exc


def _atomic_write(path: pathlib.Path, runs: list[dict]) -> None:
    """Write JSON to a sibling temp file, fsync it, then atomically replace."""
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".runs-", suffix=".json", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(runs, fh, indent=2, sort_keys=True, default=str)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
        # Persist the directory entry as well where the filesystem supports it.
        try:
            dir_fd = os.open(path.parent, os.O_DIRECTORY)
        except (AttributeError, OSError):  # pragma: no cover - platform dependent
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError as exc:
        raise EvidenceWriteError(f"could not write reliability evidence: {path}") from exc
    finally:
        if temp_name:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_name)


def save_run(run: dict) -> dict:
    """Atomically append one run without discarding historical evidence."""
    p = _path()
    with _LOCK, _process_lock(p.parent):
        runs = load_runs(allow_missing=True)
        runs.insert(0, run)
        _atomic_write(p, runs[:50])
    return run


def get_run(run_id: str) -> dict | None:
    return next((r for r in load_runs() if r.get("run_id") == run_id), None)


def latest() -> dict | None:
    runs = load_runs()
    return runs[0] if runs else None
