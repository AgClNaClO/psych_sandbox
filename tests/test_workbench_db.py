"""Real SQLite lock regressions for concurrent API/worker initialization."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from psychsandbox.workbench import db


def _locked_database(path, *, wal=False):
    conn = sqlite3.connect(path, isolation_level=None)
    if wal:
        conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("CREATE TABLE retained (value TEXT);")
    conn.execute("INSERT INTO retained VALUES ('existing data');")
    conn.execute("BEGIN IMMEDIATE;")
    return conn


def _track_connections(monkeypatch, *, factory=sqlite3.Connection, statements=None):
    connect = sqlite3.connect
    opened = []

    def tracked_connect(*args, **kwargs):
        conn = connect(*args, **kwargs, factory=factory)
        if statements is not None:
            conn.set_trace_callback(statements.append)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracked_connect)
    return opened


def test_connection_recovers_when_wal_promotion_lock_is_released(tmp_path, monkeypatch):
    path = tmp_path / "workbench.sqlite3"
    locker = _locked_database(path)
    monkeypatch.setattr(db, "_BUSY_TIMEOUT_MS", 1)
    delays = []

    def release_lock(delay):
        delays.append(delay)
        locker.rollback()

    monkeypatch.setattr(db.time, "sleep", release_lock)
    try:
        conn = db.get_connection(path)
        try:
            assert conn.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
            assert conn.execute("SELECT value FROM retained;").fetchone()[0] == "existing data"
            assert len(delays) == 1
        finally:
            conn.close()
    finally:
        locker.close()


def test_persistent_wal_lock_is_bounded_and_failed_connection_is_closed(tmp_path, monkeypatch):
    path = tmp_path / "workbench.sqlite3"
    locker = _locked_database(path)
    monkeypatch.setattr(db, "_BUSY_TIMEOUT_MS", 1)
    delays = []
    monkeypatch.setattr(db.time, "sleep", delays.append)
    opened = _track_connections(monkeypatch)
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db.get_connection(path)
        assert len(delays) == 2
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1;")
        assert locker.in_transaction
    finally:
        locker.close()


def test_existing_wal_is_not_reset_during_an_active_write(tmp_path, monkeypatch):
    path = tmp_path / "workbench.sqlite3"
    locker = _locked_database(path, wal=True)
    statements = []
    _track_connections(monkeypatch, statements=statements)
    try:
        conn = db.get_connection(path)
        try:
            assert conn.execute("SELECT value FROM retained;").fetchone()[0] == "existing data"
            assert conn.execute("PRAGMA busy_timeout;").fetchone()[0] == 5000
            assert "PRAGMA journal_mode = WAL;" not in statements
            assert statements.index("PRAGMA busy_timeout = 5000;") < statements.index("PRAGMA journal_mode;")
            assert locker.in_transaction
        finally:
            conn.close()
    finally:
        locker.close()


def test_connection_closes_and_does_not_retry_non_lock_errors(tmp_path, monkeypatch):
    class BrokenConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "PRAGMA journal_mode;":
                raise sqlite3.OperationalError("disk I/O error")
            return super().execute(sql, *args)

    delays = []
    monkeypatch.setattr(db.time, "sleep", delays.append)
    opened = _track_connections(monkeypatch, factory=BrokenConnection)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        db.get_connection(tmp_path / "workbench.sqlite3")
    assert delays == []
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1;")


def test_schema_initialization_recovers_after_a_writer_releases_its_lock(tmp_path, monkeypatch):
    path = tmp_path / "workbench.sqlite3"
    locker = _locked_database(path, wal=True)
    monkeypatch.setattr(db, "_BUSY_TIMEOUT_MS", 1)
    delays = []

    def release_lock(delay):
        delays.append(delay)
        locker.rollback()

    monkeypatch.setattr(db.time, "sleep", release_lock)
    try:
        db.init_db(path)
        conn = db.get_connection(path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';")}
            assert {"jobs", "events", "courses"} <= tables
            assert conn.execute("SELECT value FROM retained;").fetchone()[0] == "existing data"
            assert len(delays) == 1
        finally:
            conn.close()
    finally:
        locker.close()


def test_schema_errors_are_not_retried_and_connection_is_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "SCHEMA", "CREATE TABLE broken (")
    delays = []
    monkeypatch.setattr(db.time, "sleep", delays.append)
    opened = _track_connections(monkeypatch)
    with pytest.raises(sqlite3.OperationalError, match="incomplete input"):
        db.init_db(tmp_path / "workbench.sqlite3")
    assert delays == []
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1;")


def test_api_and_both_workers_can_initialize_the_same_new_database(tmp_path):
    path = tmp_path / "workbench.sqlite3"
    start = Barrier(3)

    def initialize(_):
        start.wait(timeout=10)
        db.init_db(path)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(initialize, range(3)))
    conn = db.get_connection(path)
    try:
        assert conn.execute("PRAGMA journal_mode;").fetchone()[0] == "wal"
        assert conn.execute("SELECT count(*) FROM jobs;").fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check;").fetchone()[0] == "ok"
    finally:
        conn.close()
