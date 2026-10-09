"""Incremental processing helpers: file hashing and discovery of files not yet loaded."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import Connection, select

from app.models import PipelineRun

_BLOCK = 1024 * 1024


def sha256_file(path: str | Path) -> str:
    """SHA-256 hex digest of a file's bytes (streamed)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def loaded_hashes(conn: Connection) -> set[str]:
    """Hashes of files that already have a SUCCESS pipeline run."""
    rows = conn.execute(select(PipelineRun.file_hash).where(PipelineRun.status == "SUCCESS",
                                                           PipelineRun.file_hash.is_not(None))).scalars()
    return set(rows)


def find_new_files(incoming_dir: str | Path, conn: Connection) -> list[Path]:
    """CSV files in ``incoming_dir`` whose hash has no SUCCESS run, in file-name order."""
    done = loaded_hashes(conn)
    files = sorted(Path(incoming_dir).glob("*.csv"), key=lambda p: p.name)
    return [f for f in files if sha256_file(f) not in done]
