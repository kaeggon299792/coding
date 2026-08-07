"""Remove tracked source files that disappeared between two Git revisions.

Runtime databases, secrets, logs, backups, and user uploads are never touched.
The deployment archive can then be overlaid without leaving deleted public or
executable source files behind.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path, PurePosixPath


RUNTIME_PREFIXES = (
    "dashboard/backups/",
    "dashboard/logs/",
    "dashboard/static/uploads/",
    "dashboard/data/diary_images/",
    "dashboard/data/work_note_files/",
    "dashboard/data/research_library/",
)
RUNTIME_FILES = {
    "dashboard/.env",
    "dashboard/dashboard.db",
}


def tracked_paths(repo: Path, revision: str) -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", revision, "dashboard"],
        cwd=repo,
        text=True,
        encoding="utf-8",
    )
    return {line for line in output.splitlines() if line}


def safe_source_path(path: str) -> bool:
    item = PurePosixPath(path)
    if not item.parts or item.parts[0] != "dashboard" or ".." in item.parts:
        return False
    if path in RUNTIME_FILES:
        return False
    return not any(path.startswith(prefix) for prefix in RUNTIME_PREFIXES)


def remove_disappeared(repo: Path, previous: str, target: str) -> list[str]:
    removed = []
    for relative in sorted(tracked_paths(repo, previous) - tracked_paths(repo, target)):
        if not safe_source_path(relative):
            continue
        candidate = (repo / Path(*PurePosixPath(relative).parts)).resolve()
        dashboard_root = (repo / "dashboard").resolve()
        if candidate.parent != dashboard_root and dashboard_root not in candidate.parents:
            raise ValueError(f"refusing path outside dashboard: {relative}")
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
            removed.append(relative)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    removed = remove_disappeared(args.repo.resolve(), args.previous, args.target)
    print(f"removed_stale_tracked_files={len(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
