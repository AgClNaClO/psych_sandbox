from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain import RunResult, SessionMemory, SessionRecord, Trajectory, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment_runs (
  run_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, therapy TEXT NOT NULL,
  provider TEXT NOT NULL, seed INTEGER NOT NULL, status TEXT NOT NULL,
  config_json TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, case_json TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_index INTEGER NOT NULL,
  session_json TEXT NOT NULL, UNIQUE(run_id, session_index)
);
CREATE TABLE IF NOT EXISTS turns (
  run_id TEXT NOT NULL, session_index INTEGER NOT NULL, turn_index INTEGER NOT NULL,
  role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL,
  PRIMARY KEY(run_id, session_index, turn_index, role)
);
CREATE TABLE IF NOT EXISTS memories (
  run_id TEXT NOT NULL, session_index INTEGER NOT NULL, memory_json TEXT NOT NULL,
  PRIMARY KEY(run_id, session_index)
);
CREATE TABLE IF NOT EXISTS evaluations (
  run_id TEXT NOT NULL, session_index INTEGER NOT NULL, report_json TEXT NOT NULL,
  PRIMARY KEY(run_id, session_index)
);
CREATE TABLE IF NOT EXISTS llm_evaluations (
  run_id TEXT NOT NULL, session_index INTEGER NOT NULL, report_json TEXT NOT NULL,
  PRIMARY KEY(run_id, session_index)
);
CREATE TABLE IF NOT EXISTS trajectories (
  trajectory_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_index INTEGER NOT NULL,
  trajectory_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  skill_id TEXT PRIMARY KEY, skill_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_versions (
  skill_id TEXT NOT NULL, version TEXT NOT NULL, version_json TEXT NOT NULL,
  PRIMARY KEY(skill_id, version)
);
"""


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def start_run(
        self, run_id: str, case_id: str, therapy: str, provider: str, seed: int, config: dict
    ) -> None:
        self.connection.execute(
            """INSERT INTO experiment_runs
            (run_id,case_id,therapy,provider,seed,status,config_json,created_at)
            VALUES (?,?,?,?,?,'running',?,?)""",
            (run_id, case_id, therapy, provider, seed, _json(config), utc_now()),
        )
        self.connection.commit()

    def save_case(self, case) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO cases VALUES (?,?,?)",
            (case.case_id, case.model_dump_json(), case.source),
        )
        self.connection.commit()

    def save_session(
        self, run_id: str, session: SessionRecord, memory: SessionMemory, trajectory: Trajectory
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
                (session.session_id, run_id, session.session_index, session.model_dump_json()),
            )
            for message in session.messages:
                self.connection.execute(
                    "INSERT OR REPLACE INTO turns VALUES (?,?,?,?,?,?)",
                    (
                        run_id, session.session_index, message.turn_index,
                        message.role, message.content, "{}",
                    ),
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO memories VALUES (?,?,?)",
                (run_id, session.session_index, memory.model_dump_json()),
            )
            if session.supervisor_report:
                self.connection.execute(
                    "INSERT OR REPLACE INTO evaluations VALUES (?,?,?)",
                    (run_id, session.session_index, session.supervisor_report.model_dump_json()),
                )
            if session.llm_supervisor_report:
                self.connection.execute(
                    "INSERT OR REPLACE INTO llm_evaluations VALUES (?,?,?)",
                    (
                        run_id,
                        session.session_index,
                        session.llm_supervisor_report.model_dump_json(),
                    ),
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO trajectories VALUES (?,?,?,?)",
                (
                    trajectory.trajectory_id, run_id, session.session_index,
                    trajectory.model_dump_json(),
                ),
            )

    def finish_run(self, run_id: str) -> None:
        self.connection.execute(
            "UPDATE experiment_runs SET status='completed', completed_at=? WHERE run_id=?",
            (utc_now(), run_id),
        )
        self.connection.commit()

    def load_memory(self, run_id: str) -> SessionMemory | None:
        row = self.connection.execute(
            "SELECT memory_json FROM memories WHERE run_id=? ORDER BY session_index DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return SessionMemory.model_validate_json(row[0]) if row else None

    def load_sessions(self, run_id: str) -> list[SessionRecord]:
        rows = self.connection.execute(
            "SELECT session_json FROM sessions WHERE run_id=? ORDER BY session_index", (run_id,)
        ).fetchall()
        return [SessionRecord.model_validate_json(row[0]) for row in rows]

    def load_run(self, run_id: str) -> RunResult:
        row = self.connection.execute(
            "SELECT * FROM experiment_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise KeyError(run_id)
        memory = self.load_memory(run_id)
        if memory is None:
            raise ValueError(f"Run {run_id} has no session boundary to restore")
        return RunResult(
            run_id=run_id,
            case_id=row["case_id"],
            therapy=row["therapy"],
            seed=row["seed"],
            sessions=self.load_sessions(run_id),
            final_memory=memory,
            created_at=row["created_at"],
        )

    def evaluation_rows(self, run_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT session_index, report_json FROM evaluations WHERE run_id=? ORDER BY session_index",
            (run_id,),
        ).fetchall()
        llm = {
            row[0]: json.loads(row[1])
            for row in self.connection.execute(
                "SELECT session_index, report_json FROM llm_evaluations WHERE run_id=?",
                (run_id,),
            ).fetchall()
        }
        return [
            {
                "session_index": row[0],
                "rule_report": json.loads(row[1]),
                "llm_report": llm.get(row[0]),
            }
            for row in rows
        ]


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
