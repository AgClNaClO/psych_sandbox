from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain import (
    HolisticEvaluationReport,
    RunResult,
    RolloutSelection,
    SessionMemory,
    SessionRecord,
    Trajectory,
    utc_now,
)


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
CREATE TABLE IF NOT EXISTS holistic_evaluations (
  run_id TEXT PRIMARY KEY, report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  skill_id TEXT PRIMARY KEY, skill_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rollout_batches (
  batch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_index INTEGER NOT NULL,
  selection_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rollout_candidates (
  batch_id TEXT NOT NULL, candidate_index INTEGER NOT NULL, candidate_json TEXT NOT NULL,
  PRIMARY KEY(batch_id, candidate_index)
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

    def save_rollout_batch(self, run_id: str, selection: RolloutSelection) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO rollout_batches VALUES (?,?,?,?)",
                (selection.batch_id, run_id, selection.session_index, selection.model_dump_json()),
            )

    def save_rollout_candidate(self, batch_id: str, index: int, payload: dict) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO rollout_candidates VALUES (?,?,?)",
                (batch_id, index, _json(payload)),
            )

    def load_rollout_batches(self, run_id: str) -> list[RolloutSelection]:
        rows = self.connection.execute(
            "SELECT selection_json FROM rollout_batches WHERE run_id=? ORDER BY session_index,rowid",
            (run_id,),
        ).fetchall()
        return [RolloutSelection.model_validate_json(row[0]) for row in rows]

    def load_rollout_candidates(self, batch_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT candidate_json FROM rollout_candidates WHERE batch_id=? ORDER BY candidate_index",
            (batch_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_session(
        self, run_id: str, session: SessionRecord, memory: SessionMemory, trajectory: Trajectory
    ) -> None:
        with self.connection:
            # Candidates never use this table; a committed boundary cannot be replaced.
            last_index = self.connection.execute(
                "SELECT COALESCE(MAX(session_index),0) FROM sessions WHERE run_id=?", (run_id,),
            ).fetchone()[0]
            if session.session_index != last_index + 1:
                raise ValueError("Session commit must advance exactly one boundary; resume from the latest saved session")
            self.connection.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
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
            self.connection.execute(
                "INSERT OR REPLACE INTO trajectories VALUES (?,?,?,?)",
                (
                    trajectory.trajectory_id, run_id, session.session_index,
                    trajectory.model_dump_json(),
                ),
            )
            # A report for the old course must not survive a newly committed session.
            self.connection.execute("DELETE FROM holistic_evaluations WHERE run_id=?", (run_id,))

    def finish_run(self, run_id: str, *, status: str = "completed") -> None:
        self.connection.execute(
            "UPDATE experiment_runs SET status=?, completed_at=? WHERE run_id=?",
            (status, utc_now(), run_id),
        )
        self.connection.commit()

    def mark_run_running(self, run_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE experiment_runs SET status='running', completed_at=NULL WHERE run_id=?", (run_id,),
            )

    def load_run_metadata(self, run_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM experiment_runs WHERE run_id=?", (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        metadata = dict(row)
        metadata["config"] = json.loads(metadata.pop("config_json"))
        return metadata

    def trajectory_rows(self, run_id: str) -> list[str]:
        return [row[0] for row in self.connection.execute(
            "SELECT trajectory_json FROM trajectories WHERE run_id=? ORDER BY session_index",
            (run_id,),
        ).fetchall()]

    def save_holistic_report(
        self, run_id: str, report: HolisticEvaluationReport
    ) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO holistic_evaluations VALUES (?,?)",
            (run_id, report.model_dump_json()),
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
        holistic = self.load_holistic_report(run_id)
        return RunResult(
            run_id=run_id,
            case_id=row["case_id"],
            therapy=row["therapy"],
            seed=row["seed"],
            sessions=self.load_sessions(run_id),
            final_memory=memory,
            holistic_report=holistic,
            created_at=row["created_at"],
        )

    def load_holistic_report(self, run_id: str) -> HolisticEvaluationReport | None:
        row = self.connection.execute(
            "SELECT report_json FROM holistic_evaluations WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return HolisticEvaluationReport.model_validate_json(row[0]) if row else None

def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
