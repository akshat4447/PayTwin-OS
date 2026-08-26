"""JSON evidence store for Reliability Lab runs (data/reliability/).

Decision (HISTORY.md §4 audit matrix): run artifacts are immutable JSON documents rather
than new SQL tables for v1 — they are generated evidence, queried rarely, and
this keeps the feature migration-free while remaining fully auditable on disk.
"""
from __future__ import annotations

import json
import pathlib
import threading

_LOCK = threading.Lock()
_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "reliability"


def _path() -> pathlib.Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / "runs.json"


def load_runs() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def save_run(run: dict) -> dict:
    with _LOCK:
        runs = load_runs()
        runs.insert(0, run)
        _path().write_text(json.dumps(runs[:50], indent=2))
    return run


def get_run(run_id: str) -> dict | None:
    return next((r for r in load_runs() if r["run_id"] == run_id), None)


def latest() -> dict | None:
    runs = load_runs()
    return runs[0] if runs else None
