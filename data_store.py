"""Bounded JSONL parts, preserving every sample and its original order.

Run under run.sh's lock. Legacy files are migrated before sampling; the
completed directory is published atomically before the old file is removed.
"""
import os
from pathlib import Path
import sys
import tempfile

PART_BYTES = 32 * 1024 * 1024
DATA = Path(__file__).resolve().parent / "data"


def migrate(path, limit=PART_BYTES):
    parts = path.with_suffix("")
    if parts.exists():
        # A completed migration takes precedence, including after a crash
        # between publishing the directory and deleting the legacy file.
        return parts
    if not path.exists():
        parts.mkdir()
        return parts
    with tempfile.TemporaryDirectory(prefix=".migrate-", dir=path.parent) as temp:
        staged = Path(temp) / "parts"
        staged.mkdir()
        number, size = 0, 0
        output = None
        try:
            with path.open("rb") as source:
                for line in source:
                    if len(line) > limit:
                        raise ValueError(f"Single sample exceeds part limit: {path}")
                    if output is None or size + len(line) > limit:
                        if output is not None:
                            output.close()
                        output = (staged / f"part-{number:08d}.jsonl").open("wb")
                        number += 1
                        size = 0
                    output.write(line)
                    size += len(line)
        finally:
            if output is not None:
                output.close()
        os.rename(staged, parts)
    path.unlink()
    return parts


def sample_path(path, limit=PART_BYTES):
    parts = migrate(path, limit)
    files = sorted(parts.glob("part-*.jsonl"))
    if files and files[-1].stat().st_size < limit:
        return files[-1]
    number = int(files[-1].stem.split("-")[1]) + 1 if files else 0
    return parts / f"part-{number:08d}.jsonl"


def sample_files(path):
    parts = path.with_suffix("")
    if parts.is_dir():
        return sorted(parts.glob("part-*.jsonl"))
    return [path] if path.exists() else []


if __name__ == "__main__":
    name = sys.argv[1]
    if name not in ("gpu_samples", "cpu_samples", "queue_samples"):
        raise SystemExit("Unknown sample stream")
    print(sample_path(DATA / f"{name}.jsonl"))
