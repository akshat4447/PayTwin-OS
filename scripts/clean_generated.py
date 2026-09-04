#!/usr/bin/env python3
"""Remove generated local runtime artifacts without touching user recordings.

This is intentionally conservative. It removes known development/test outputs
only, while preserving the virtual environment, Git metadata, the recording
media directory, and captured recording databases.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTECTED_TOP_LEVELS = {".git", ".venv", "Recordings "}
EXACT_DIRECTORIES = (
    ROOT / ".pytest_cache",
    ROOT / "services/ml/artifacts",
)
EXACT_FILES = (
    ROOT / ".DS_Store",
    ROOT / "docs/.DS_Store",
    ROOT / "DEMO_RUN.md",
    ROOT / "services/data/reliability/.runs.lock",
    ROOT / "data/api_server.log",
    ROOT / "data/demo_dom.html",
    ROOT / "data/demo_markers.txt",
    ROOT / "data/lt_result.txt",
    ROOT / "data/parse_check.txt",
    ROOT / "data/post_cleanup_suite.log",
)
GENERATED_DATABASES = (
    "demo.db",
    "dev.db",
    "loadtest.db",
    "razorpay-hackathon.db",
    "test.db",
    "test_reliability.db",
)


def relative_path(path: Path) -> Path:
    """Return a repository-relative path, refusing protected locations."""
    relative = path.relative_to(ROOT)
    if not relative.parts or relative.parts[0] in PROTECTED_TOP_LEVELS:
        raise ValueError(f"Refusing to remove protected path: {relative}")
    return relative


def remove(path: Path, *, dry_run: bool) -> bool:
    if not path.exists() and not path.is_symlink():
        return False

    relative = relative_path(path)
    action = "Would remove" if dry_run else "Removed"
    print(f"{action} {relative}")
    if dry_run:
        return True

    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def generated_cache_paths() -> list[Path]:
    """Find only standard Python/package build cache directories."""
    candidates: list[Path] = []
    for pattern in ("__pycache__", "*.egg-info"):
        for path in ROOT.rglob(pattern):
            try:
                relative_path(path)
            except ValueError:
                continue
            candidates.append(path)
    return sorted(set(candidates))


def generated_database_paths() -> list[Path]:
    data_dir = ROOT / "data"
    candidates = [data_dir / filename for filename in GENERATED_DATABASES]
    candidates.extend(data_dir.glob("test-*.db"))
    candidates.extend(data_dir.glob("test_*.db"))
    return sorted(set(candidates))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print generated paths that would be removed",
    )
    args = parser.parse_args()

    removed = 0
    for path in (*EXACT_DIRECTORIES, *generated_cache_paths(), *EXACT_FILES, *generated_database_paths()):
        removed += remove(path, dry_run=args.dry_run)

    verb = "would be removed" if args.dry_run else "removed"
    print(f"{removed} generated path(s) {verb}. Recording assets were preserved.")


if __name__ == "__main__":
    main()
