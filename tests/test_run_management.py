from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager

import pytest

from psychsandbox import cli
from psychsandbox.artifacts import create_artifact_dir, exclusive_run_dir, write_json
from psychsandbox.domain import SandboxConfig
from psychsandbox.runtime import SQLiteStore
from psychsandbox.runtime import run_management
from psychsandbox.runtime.run_management import RunManager, available_run_dir


TARGET = "run-0123456789ab"
KEEP = "run-abcdef012345"


def add_run(store, base, run_id, *, directory=True, status="completed"):
    store.start_run(run_id, "shared-case", "cbt", "test", 42, {})
    store.finish_run(run_id, status=status)
    db = store.connection
    with db:
        db.execute("INSERT INTO sessions VALUES (?,?,1,'{}')", (run_id + '-s', run_id))
        db.execute("INSERT INTO turns VALUES (?,1,1,'client','test','{}')", (run_id,))
        for table, fields in (
            ("memories", "?,1,'{}'"), ("evaluations", "?,1,'{}'"),
            ("llm_evaluations", "?,1,'{}'"), ("client_evaluations", "?,1,'{}'"),
            ("holistic_evaluations", "?,'{}'"),
        ):
            db.execute(f"INSERT INTO {table} VALUES ({fields})", (run_id,))
        db.execute("INSERT INTO trajectories VALUES (?,?,1,'{}')", (run_id + '-t', run_id))
        db.execute("INSERT INTO rollout_batches VALUES (?,?,1,'{}')", (run_id + '-b', run_id))
        db.execute("INSERT INTO rollout_candidates VALUES (?,1,'{}')", (run_id + '-b',))
    if directory:
        path = create_artifact_dir(base, "case", run_id)
        write_json(path / "run.json", {"run_id": run_id, "status": status})
        write_json(path / "rollouts" / "batch" / "candidate.json", {"test": True})
        return path


@pytest.fixture
def managed(tmp_path):
    base = tmp_path / "runtime"
    store = SQLiteStore(base / "test.sqlite3")
    target = add_run(store, base, TARGET)
    keep = add_run(store, base, KEEP)
    with store.connection:
        store.connection.execute("INSERT INTO cases VALUES ('shared-case','{}','test')")
        store.connection.execute("INSERT INTO skills VALUES ('shared-skill','{}')")
        store.connection.execute("INSERT INTO skill_versions VALUES ('shared-skill','v1','{}')")
    manager = RunManager(store.path, base)
    try:
        yield manager, store, target, keep
    finally:
        store.close()


def tree_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob('*')}


def test_preview_and_list_are_read_only_and_need_no_api(managed, monkeypatch):
    manager, store, target, keep = managed
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    before = tree_bytes(manager.artifacts)
    preview = manager.preview_delete(TARGET)
    assert all(n == 1 for n in preview["records"].values())
    assert preview["directory"] == str(target)
    assert len(manager.list_runs()) == 2
    assert tree_bytes(manager.artifacts) == before


def test_delete_removes_only_target_files_and_all_related_records(managed):
    manager, store, target, keep = managed
    keep_files = tree_bytes(keep)
    result = manager.delete(TARGET)
    assert result["status"] == "completed"
    assert not target.exists()
    assert tree_bytes(keep) == keep_files
    assert all(n == 0 for n in manager.preview_delete(TARGET)["records"].values())
    assert all(n == 1 for n in manager.preview_delete(KEEP)["records"].values())
    for table in ("cases", "skills", "skill_versions"):
        assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    assert manager.delete(TARGET) == result


def test_delete_database_only_run_after_manual_directory_removal(managed):
    manager, store, target, _ = managed
    shutil.rmtree(target)
    assert manager.preview_delete(TARGET)["directory"] is None
    assert manager.delete(TARGET)["status"] == "completed"


def test_directory_only_cleanup_does_not_create_database(tmp_path):
    base = tmp_path / "runtime"
    directory = create_artifact_dir(base, "case", TARGET)
    write_json(directory / "run.json", {"run_id": TARGET})
    manager = RunManager(base / "absent.sqlite3", base)
    assert not any(manager.preview_delete(TARGET)["records"].values())
    assert manager.delete(TARGET)["status"] == "completed"
    assert not manager.database.exists()
    assert not directory.exists()


def test_unknown_run_is_never_created(tmp_path):
    manager = RunManager(tmp_path / "absent.sqlite3", tmp_path / "absent")
    assert manager.list_runs() == []
    assert manager.preview_delete(TARGET)["found"] is False
    with pytest.raises(FileNotFoundError):
        manager.delete(TARGET)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id", ["../assets", "run-*", "run-0123456789ab/../", "", "run-foo"])
def test_invalid_ids_are_rejected_without_mutation(managed, run_id):
    manager, _, _, _ = managed
    before = tree_bytes(manager.artifacts)
    with pytest.raises(ValueError):
        manager.delete(run_id)
    assert tree_bytes(manager.artifacts) == before


def test_held_run_lock_blocks_deletion_without_database_changes(managed):
    manager, store, target, _ = managed
    before = manager.database.read_bytes()
    with exclusive_run_dir(target):
        with pytest.raises(RuntimeError, match="already executing"):
            manager.delete(TARGET)
    assert manager.database.read_bytes() == before
    assert target.exists()


def test_running_without_directory_cannot_be_safely_deleted(managed):
    manager, store, target, _ = managed
    shutil.rmtree(target)
    store.mark_run_running(TARGET)
    with pytest.raises(RuntimeError, match="stop it first"):
        manager.delete(TARGET)
    assert store.load_run_metadata(TARGET)["status"] == "running"


def test_interrupted_running_with_released_lock_can_be_deleted(managed):
    manager, store, _, _ = managed
    store.mark_run_running(TARGET)
    assert manager.delete(TARGET)["status"] == "completed"


def test_file_failure_is_recorded_blocks_writers_and_can_retry(managed, monkeypatch):
    manager, store, target, _ = managed
    original = shutil.rmtree

    def partial_failure(path):
        (path / "run.json").unlink()
        raise PermissionError("test locked file")

    monkeypatch.setattr(shutil, "rmtree", partial_failure)
    with pytest.raises(PermissionError):
        manager.delete(TARGET)
    assert manager.preview_delete(TARGET)["deletion_status"] == "failed"
    assert store.load_run_metadata(TARGET)["status"] == "deleting"
    with pytest.raises(RuntimeError, match="deletion has started"):
        with available_run_dir(manager.artifacts, TARGET):
            pytest.fail("deleted run admitted a writer")
    monkeypatch.setattr(shutil, "rmtree", original)
    assert manager.delete(TARGET)["status"] == "completed"


def test_sql_failure_rolls_back_all_records_and_retries_without_directory(managed):
    manager, store, target, _ = managed
    store.connection.execute(
        "CREATE TRIGGER block_delete BEFORE DELETE ON sessions "
        "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        manager.delete(TARGET)
    assert not target.exists()
    assert all(n == 1 for n in manager.preview_delete(TARGET)["records"].values())
    assert manager.preview_delete(TARGET)["deletion_status"] == "failed"
    store.connection.execute("DROP TRIGGER block_delete")
    assert manager.delete(TARGET)["status"] == "completed"


def test_duplicate_directories_and_mismatched_metadata_are_rejected(managed):
    manager, _, target, _ = managed
    other = create_artifact_dir(manager.artifacts, "duplicate", TARGET)
    with pytest.raises(ValueError, match="Multiple"):
        manager.delete(TARGET)
    other.rmdir()
    write_json(target / "run.json", {"run_id": KEEP})
    with pytest.raises(ValueError, match="metadata"):
        manager.delete(TARGET)


def test_shared_database_inside_target_is_protected(tmp_path):
    target = create_artifact_dir(tmp_path, "case", TARGET)
    manager = RunManager(target / "shared.sqlite3", tmp_path)
    with pytest.raises(ValueError, match="shared database"):
        manager.delete(TARGET)
    assert target.exists()


def test_nested_symlink_is_not_followed(managed, tmp_path):
    manager, _, target, _ = managed
    outside = tmp_path / "source-data"
    outside.mkdir()
    (outside / "important.txt").write_text("keep")
    try:
        (target / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(outside), str(target / "link"))
    with pytest.raises(ValueError, match="linked/reparse"):
        manager.delete(TARGET)
    assert (outside / "important.txt").read_text() == "keep"


def test_cli_requires_explicit_confirmation_and_lists_missing_directories(managed, monkeypatch, capsys):
    manager, _, target, _ = managed
    config = SandboxConfig(project_root=manager.artifacts.parent, database_path=manager.database, trace_dir=manager.artifacts)
    monkeypatch.setattr(cli, "default_config", lambda root: config)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "runs", "delete", "--run", TARGET])
    before = tree_bytes(manager.artifacts)
    assert cli.main() == 0
    assert "仅预览" in capsys.readouterr().out
    assert target.exists()
    assert tree_bytes(manager.artifacts) == before
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "runs", "delete", "--run", TARGET, "--yes"])
    assert cli.main() == 0
    assert not target.exists()
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "runs", "list"])
    capsys.readouterr()
    assert cli.main() == 0
    rows = json.loads(capsys.readouterr().out)
    assert next(r for r in rows if r["run_id"] == TARGET)["deletion_status"] == "completed"


def test_cli_missing_run_is_nonzero_and_has_no_side_effects(tmp_path, monkeypatch):
    config = SandboxConfig(project_root=tmp_path, database_path=tmp_path / "db.sqlite3", trace_dir=tmp_path / "runs")
    monkeypatch.setattr(cli, "default_config", lambda root: config)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "runs", "delete", "--run", TARGET, "--yes"])
    assert cli.main() == 1
    assert list(tmp_path.iterdir()) == []


def test_directory_database_mismatch_refuses_sync_deletion(managed, tmp_path):
    manager, _, target, _ = managed
    write_json(target / "run.json", {"run_id": TARGET, "database": str(tmp_path / "other.sqlite3")})
    before = tree_bytes(manager.artifacts)
    with pytest.raises(ValueError, match="different database"):
        manager.delete(TARGET)
    assert tree_bytes(manager.artifacts) == before


def test_linked_deletion_lock_cannot_be_opened(managed, tmp_path):
    manager, _, _, _ = managed
    audit = manager.artifacts / ".deletions" / TARGET
    audit.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = audit / ".run.lock"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="linked/reparse"):
        manager.delete(TARGET)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("failure_status", ["deleting", "failed", "completed"])
def test_journal_write_failure_still_allows_safe_retry(managed, monkeypatch, failure_status):
    manager, store, target, _ = managed
    original_write = run_management.write_json
    original_remove = shutil.rmtree

    def fail_write(path, value):
        if value.get("status") == failure_status:
            raise OSError("test journal disk full")
        return original_write(path, value)

    def fail_remove(path):
        raise PermissionError("test file locked")

    monkeypatch.setattr(run_management, "write_json", fail_write)
    if failure_status == "failed":
        monkeypatch.setattr(shutil, "rmtree", fail_remove)
    with pytest.raises(OSError):
        manager.delete(TARGET)
    if failure_status == "deleting":
        assert store.load_run_metadata(TARGET)["status"] == "completed"
        assert manager.preview_delete(TARGET)["deletion_status"] is None
        assert target.exists()
    else:
        assert manager.preview_delete(TARGET)["deletion_status"] == "deleting"
    monkeypatch.setattr(run_management, "write_json", original_write)
    monkeypatch.setattr(shutil, "rmtree", original_remove)
    result = manager.delete(TARGET)
    assert result["status"] == "completed"
    assert result["directory"] == target.name
    assert all(n == 1 for n in result["records"].values())


def test_initial_status_write_failure_is_recorded_before_file_deletion(managed):
    manager, store, target, _ = managed
    store.connection.execute(
        "CREATE TRIGGER block_update BEFORE UPDATE ON experiment_runs "
        "BEGIN SELECT RAISE(ABORT, 'test update failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        manager.delete(TARGET)
    assert target.exists()
    assert manager.preview_delete(TARGET)["deletion_status"] == "failed"
    assert store.load_run_metadata(TARGET)["status"] == "completed"
    store.connection.execute("DROP TRIGGER block_update")
    assert manager.delete(TARGET)["status"] == "completed"


def test_delete_transaction_commit_failure_rolls_back_and_retries(managed, monkeypatch):
    manager, _, target, _ = managed
    original_connect = sqlite3.connect

    class CommitFailure(sqlite3.Connection):
        deleting = False

        def execute(self, sql, *args, **kwargs):
            if sql.startswith("DELETE"):
                self.deleting = True
            return super().execute(sql, *args, **kwargs)

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None and self.deleting:
                self.rollback()
                raise sqlite3.OperationalError("test commit failure")
            return super().__exit__(exc_type, exc, tb)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: original_connect(*a, **k, factory=CommitFailure))
    with pytest.raises(sqlite3.OperationalError, match="commit failure"):
        manager.delete(TARGET)
    assert not target.exists()
    assert all(n == 1 for n in manager.preview_delete(TARGET)["records"].values())
    monkeypatch.setattr(sqlite3, "connect", original_connect)
    assert manager.delete(TARGET)["status"] == "completed"


def test_writer_rechecks_deletion_after_acquiring_lock(managed, monkeypatch):
    manager, _, target, _ = managed

    @contextmanager
    def deletion_before_lock_acquired(directory):
        with exclusive_run_dir(directory):
            write_json(manager.artifacts / ".deletions" / TARGET / "deletion.json", {"status": "deleting"})
            yield

    monkeypatch.setattr(run_management, "exclusive_run_dir", deletion_before_lock_acquired)
    with pytest.raises(RuntimeError, match="deletion has started"):
        with available_run_dir(manager.artifacts, TARGET):
            pytest.fail("writer raced past deletion")


@pytest.mark.asyncio
async def test_new_run_checks_deletion_between_directory_creation_and_lock(
    root, tmp_path, sample_case, repository, monkeypatch
):
    from psychsandbox.runtime import CounselingSandbox, orchestrator
    from tests.deterministic_gateway import DeterministicGateway

    config = SandboxConfig(project_root=root, trace_dir=tmp_path / "runtime", database_path=tmp_path / "db.sqlite3")
    sandbox = CounselingSandbox(
        config, gateway=DeterministicGateway(), repository=repository
    )

    def mark_before_lock(base, label, run_id):
        path = create_artifact_dir(base, label, run_id)
        write_json(base / ".deletions" / run_id / "deletion.json", {"status": "deleting"})
        return path

    monkeypatch.setattr(orchestrator, "create_artifact_dir", mark_before_lock)
    try:
        with pytest.raises(RuntimeError, match="deletion has started"):
            await sandbox.run_case(sample_case.case_id, session_count=1)
        assert sandbox.store.connection.execute("SELECT count(*) FROM experiment_runs").fetchone()[0] == 0
    finally:
        sandbox.store.close()
