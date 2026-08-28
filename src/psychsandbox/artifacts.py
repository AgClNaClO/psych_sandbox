"""Paths for retained test and runtime artifacts (never input resources)."""

from __future__ import annotations

import json
import os
import re
import uuid
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


_simulation_lock = threading.Lock()


@contextmanager
def single_simulation():
    """The process-wide temp environment belongs to one run, not one candidate."""
    if not _simulation_lock.acquire(blocking=False):
        raise RuntimeError("Only one run_case may execute in a process; parallelize candidates within the run")
    try:
        yield
    finally:
        _simulation_lock.release()


@contextmanager
def exclusive_run_dir(directory: Path):
    """Prevent simultaneous recovery of the same run; OS releases locks on exit."""
    with (directory / ".run.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("This run is already executing in another process") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def runtime_root(project_root: Path) -> Path:
    # Pytest supplies a session-local root, also inherited by CLI subprocesses.
    override = os.environ.get("PSYCHSANDBOX_RUNTIME_DIR")
    return Path(override).resolve() if override else project_root.resolve() / "runs" / "runtime"


def create_artifact_dir(base: Path, label: str, identifier: str | None = None) -> Path:
    label = re.sub(r"[^\w.-]+", "-", label).strip(".-") or "run"
    identifier = identifier or uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[\w-]+", identifier):
        raise ValueError("Invalid run identifier")
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    path = base / f"{stamp}__{label}__{identifier}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def find_run_dir(base: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[\w-]+", run_id):
        raise ValueError("Invalid run identifier")
    matches = [path for path in base.glob(f"*__{run_id}") if path.is_dir()]
    if not matches:
        raise FileNotFoundError(f"No artifact directory for {run_id}")
    if len(matches) != 1:
        raise ValueError(f"Multiple artifact directories for {run_id}")
    path = matches[0].resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError("Run directory must stay inside its artifact root")
    return path


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep atomic-write names short enough for nested Windows run directories.
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex[:16]}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def local_temp_dir(path: Path):
    """Scope stdlib and subprocess temporary files to a CLI/run invocation."""
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    previous = {name: os.environ.get(name) for name in ("TMP", "TEMP", "TMPDIR")}
    previous_tempdir = tempfile.tempdir
    try:
        for name in previous:
            os.environ[name] = str(path)
        tempfile.tempdir = str(path)
        yield
    finally:
        tempfile.tempdir = previous_tempdir
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def set_latest_data(root: Path, kind: str, path: Path) -> None:
    base = runtime_root(root)
    write_json(base / f"{kind}-latest.json", {"path": path.relative_to(base).as_posix()})


def latest_data_dir(root: Path, kind: str) -> Path:
    base = runtime_root(root)
    pointer = base / f"{kind}-latest.json"
    if pointer.exists():
        path = (base / json.loads(pointer.read_text(encoding="utf-8"))["path"]).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError("Data cache must stay inside its artifact root")
        return path
    # Read-only compatibility for checkouts not yet migrated.
    return root / "data" / kind / "psycheval"
