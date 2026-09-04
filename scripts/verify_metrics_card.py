"""Verify that committed Buildathon evidence matches a fresh evaluator run.

The card is intentionally reviewed as structured data instead of compared as
bytes: the evaluator is deterministic, but a harmless JSON formatter or a
minor numerical-library rounding difference should not make public CI flaky.
All scenario outcomes and counts remain exact; measured floating-point metrics
are allowed a small, explicit tolerance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read metrics card {path}: {exc}") from exc


def _same(expected, actual, label: str, failures: list[str]) -> None:
    if expected != actual:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def _close(expected, actual, label: str, tolerance: float,
           failures: list[str]) -> None:
    if not isinstance(actual, (int, float)):
        failures.append(f"{label}: expected a number, got {actual!r}")
    elif abs(float(expected) - float(actual)) > tolerance:
        failures.append(
            f"{label}: expected {expected!r}, got {actual!r} "
            f"(tolerance {tolerance:g})")


def verify(committed: dict, fresh: dict, tolerance: float) -> list[str]:
    """Return human-readable discrepancies between committed and fresh evidence."""
    failures: list[str] = []
    for key in ("success_model", "detection", "rca", "rar", "bandit"):
        if key not in committed:
            failures.append(f"committed card is missing {key}")
        if key not in fresh:
            failures.append(f"fresh card is missing {key}")
    if failures:
        return failures

    for key in ("rows", "n_test", "reproducible"):
        _same(committed["success_model"].get(key), fresh["success_model"].get(key),
              f"success_model.{key}", failures)
    for key in ("roc_auc", "pr_auc", "brier", "ece"):
        _close(committed["success_model"].get(key),
               fresh["success_model"].get(key),
               f"success_model.{key}", tolerance, failures)

    _same(committed["detection"], fresh["detection"], "detection", failures)
    _same(committed["rca"], fresh["rca"], "rca", failures)
    _same(committed["rar"].get("coverage80"), fresh["rar"].get("coverage80"),
          "rar.coverage80", failures)
    _same(committed["rar"].get("point_in_interval_all"),
          fresh["rar"].get("point_in_interval_all"),
          "rar.point_in_interval_all", failures)
    _close(committed["rar"].get("median_rel_err"),
           fresh["rar"].get("median_rel_err"),
           "rar.median_rel_err", tolerance, failures)
    for key in ("fixed_arm0", "linucb"):
        _close(committed["bandit"].get(key), fresh["bandit"].get(key),
               f"bandit.{key}", tolerance, failures)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("committed", help="committed metrics card")
    parser.add_argument("fresh", help="fresh evaluator output")
    parser.add_argument("--tolerance", type=float, default=5e-4,
                        help="absolute tolerance for measured floats")
    args = parser.parse_args()
    if args.tolerance < 0:
        raise SystemExit("tolerance must be non-negative")

    failures = verify(_load(args.committed), _load(args.fresh), args.tolerance)
    if failures:
        raise SystemExit("metrics evidence drifted:\n- " + "\n- ".join(failures))
    print("metrics evidence matches fresh evaluator output")


if __name__ == "__main__":
    main()
