"""Explicit run deletion across SQLite and files, with a durable retry journal."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path

from ..artifacts import exclusive_run_dir, find_run_dir, write_json
from ..domain import utc_now


_RUN_ID = re.compile(r"run-[0-9a-f]{12}\Z")
_RUN_TABLES = (
    "turns", "memories", "evaluations", "llm_evaluations",
    "client_evaluations", "trajectories", "holistic_evaluations",
    "sessions", "rollout_batches", "experiment_runs",
)


def _check_id(run_id: str) -> None:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("Expected a run ID such as run-0123456789ab")


def _check_links(path: Path) -> None:
    for part in (*path.parents, path):
        if part.is_symlink() or (
            part.exists()
            and getattr(part.lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"Refusing linked/reparse path: {part}")


def _journal_path(base: Path, run_id: str) -> Path:
    _check_id(run_id)
    path = base / ".deletions" / run_id / "deletion.json"
    _check_links(path)
    return path


@contextmanager
def available_run_dir(base: Path, run_id: str):
    """Serialize writers with deletion; never recreate a deleting run's files."""
    # Existing non-CLI callers also use descriptive IDs, so validate through find_run_dir.
    def check():
        if (base / ".deletions" / run_id / "deletion.json").exists():
            raise RuntimeError("Run deletion has started; this run cannot be resumed or rendered")

    directory = find_run_dir(base, run_id)
    check()
    _check_links(directory / ".run.lock")
    with exclusive_run_dir(directory):
        check()
        yield directory


class RunManager:
    def __init__(self, database: Path, artifacts: Path):
        self.database = Path(database).absolute()
        self.artifacts = Path(artifacts).absolute()
        _check_links(self.database)
        _check_links(self.artifacts)

    @contextmanager
    def _connection(self, *, write: bool = False):
        _check_links(self.database)
        if not self.database.exists():
            yield None
            return
        mode = "rw" if write else "ro"
        with closing(sqlite3.connect(self.database.as_uri() + f"?mode={mode}", uri=True)) as db:
            db.row_factory = sqlite3.Row
            yield db

    @staticmethod
    def _tables(db) -> set[str]:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} if db else set()

    def _directory(self, run_id: str) -> Path | None:
        matches = list(self.artifacts.glob(f"*__{run_id}"))
        if len(matches) > 1:
            raise ValueError(f"Multiple artifact paths for {run_id}")
        if not matches:
            return None
        path = matches[0]
        self._validate_directory(path, run_id)
        return path

    def _validate_directory(self, path: Path, run_id: str) -> None:
        _check_links(path)
        resolved = path.resolve()
        if resolved.parent != self.artifacts.resolve() or not path.name.endswith(f"__{run_id}"):
            raise ValueError("Run directory must be a direct child of its artifact root")
        if not path.is_dir():
            raise ValueError("Run artifact path is not a directory")
        if self.database.resolve().is_relative_to(resolved):
            raise ValueError("Run directory contains the shared database")
        for parent, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                _check_links(Path(parent) / name)
        metadata = path / "run.json"
        if metadata.exists():
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("run_id") != run_id:
                raise ValueError("Artifact metadata does not match the requested run")
            if payload.get("database") and Path(payload["database"]).resolve() != self.database.resolve():
                raise ValueError("Artifact metadata belongs to a different database; verify its original configuration")

    def preview_delete(self, run_id: str) -> dict:
        """Read-only: do not create a database, lock, journal or artifact directory."""
        _check_id(run_id)
        directory = self._directory(run_id)
        journal_path = _journal_path(self.artifacts, run_id)
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else None
        if journal is not None and (not isinstance(journal, dict) or not journal):
            raise ValueError("Invalid deletion journal")
        if journal and (
            journal.get("run_id") != run_id
            or journal.get("database") != str(self.database)
            or (directory and journal.get("directory") != directory.name)
        ):
            raise ValueError("Deletion journal does not match this run/database")
        counts = dict.fromkeys((*_RUN_TABLES, "rollout_candidates"), 0)
        status = None
        with self._connection() as db:
            tables = self._tables(db)
            for table in _RUN_TABLES:
                if table in tables:
                    counts[table] = db.execute(f"SELECT count(*) FROM {table} WHERE run_id=?", (run_id,)).fetchone()[0]
            if {"rollout_candidates", "rollout_batches"} <= tables:
                counts["rollout_candidates"] = db.execute(
                    "SELECT count(*) FROM rollout_candidates WHERE batch_id IN "
                    "(SELECT batch_id FROM rollout_batches WHERE run_id=?)", (run_id,),
                ).fetchone()[0]
            if counts["experiment_runs"]:
                status = db.execute("SELECT status FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()[0]
        return {
            "run_id": run_id, "status": status, "database": str(self.database),
            "directory": str(directory) if directory else None,
            "records": counts, "deletion_status": journal.get("status") if journal else None,
            "found": bool(directory or any(counts.values()) or journal),
        }

    def list_runs(self) -> list[dict]:
        ids = set()
        with self._connection() as db:
            if "experiment_runs" in self._tables(db):
                ids.update(row[0] for row in db.execute("SELECT run_id FROM experiment_runs"))
        for path in self.artifacts.glob("*__run-*"):
            ids.add(path.name.rsplit("__", 1)[-1])
        deletion_root = self.artifacts / ".deletions"
        _check_links(deletion_root)
        for path in deletion_root.glob("*/deletion.json"):
            ids.add(path.parent.name)
        return [self.preview_delete(run_id) for run_id in sorted(ids)]

    def delete(self, run_id: str) -> dict:
        """Caller has explicitly confirmed this run; completed deletions are idempotent."""
        preview = self.preview_delete(run_id)
        if not preview["found"]:
            raise FileNotFoundError(f"No run records or artifacts for {run_id}")
        journal_path = _journal_path(self.artifacts, run_id)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        _check_links(journal_path.parent / ".run.lock")
        with exclusive_run_dir(journal_path.parent):
            preview = self.preview_delete(run_id)
            if preview["deletion_status"] == "completed":
                if preview["directory"] or any(preview["records"].values()):
                    raise ValueError("A completed deletion unexpectedly has new records or files")
                return json.loads(journal_path.read_text(encoding="utf-8"))
            directory = Path(preview["directory"]) if preview["directory"] else None
            if directory is None and preview["status"] == "running":
                raise RuntimeError("Cannot verify a running task without its artifact lock; stop it first")
            previous = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
            journal = {
                "run_id": run_id, "database": str(self.database),
                "directory": directory.name if directory else previous.get("directory"),
                "records": previous.get("records", preview["records"]),
                "status": "deleting", "updated_at": utc_now(), "error": None,
            }
            # Windows cannot remove an open lock file. Mark deletion durably while
            # holding the run lock, then release it; all writers honor the journal.
            started = False
            try:
                with exclusive_run_dir(directory) if directory else nullcontext():
                    if directory:
                        self._validate_directory(directory, run_id)
                    write_json(journal_path, journal)
                    started = True
                    with self._connection(write=True) as db:
                        if "experiment_runs" in self._tables(db):
                            with db:
                                db.execute("UPDATE experiment_runs SET status='deleting' WHERE run_id=?", (run_id,))
                if directory:
                    self._validate_directory(directory, run_id)
                    shutil.rmtree(directory)
                self._delete_records(run_id)
                remaining = self.preview_delete(run_id)
                if remaining["directory"] or any(remaining["records"].values()):
                    raise RuntimeError("Run deletion did not remove all targeted records/files")
            except BaseException as exc:
                if started:
                    journal.update(status="failed", error=f"{type(exc).__name__}: {exc}", updated_at=utc_now())
                    try:
                        write_json(journal_path, journal)
                    except OSError:
                        pass  # The earlier 'deleting' journal still blocks writers and permits retry.
                raise
            journal.update(status="completed", updated_at=utc_now())
            write_json(journal_path, journal)
            return journal

    def _delete_records(self, run_id: str) -> None:
        with self._connection(write=True) as db:
            if db is None:
                return
            tables = self._tables(db)
            with db:
                db.execute("BEGIN IMMEDIATE")
                if {"rollout_candidates", "rollout_batches"} <= tables:
                    db.execute(
                        "DELETE FROM rollout_candidates WHERE batch_id IN "
                        "(SELECT batch_id FROM rollout_batches WHERE run_id=?)", (run_id,),
                    )
                for table in _RUN_TABLES:
                    if table in tables:
                        db.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
