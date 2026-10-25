"""科研 Web 工作台数据库连接与持久化定义 (workbench.sqlite3)

独立于正式仿真库 psychsandbox.sqlite3，
负责任务生命周期、SSE 事件流、人工疗程、技能演化闭环及导出审计。
短事务设计，WAL 模式，保证高并发读写安全。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Generator
from contextlib import contextmanager

from ..domain import utc_now

DEFAULT_WORKBENCH_DB = Path("runs/runtime/workbench.sqlite3")

SCHEMA = """
-- 任务表：支持短/长 lane 隔离、认领、租约、心跳和 attempt 栅栏
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  lane TEXT NOT NULL,
  status TEXT NOT NULL, -- queued, running, succeeded, failed, stopped, cancelled
  payload_json TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  lease_owner TEXT,
  lease_expires_at TEXT,
  heartbeat_at TEXT,
  stop_requested INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  result_json TEXT,
  error TEXT,
  run_id TEXT,
  course_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_lane_status ON jobs(lane, status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_course_id ON jobs(course_id);

-- 事件流表：单调自增 seq，先落库再推送，支持断线重放与去重
CREATE TABLE IF NOT EXISTS events (
  stream TEXT NOT NULL,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(stream, seq)
);

CREATE INDEX IF NOT EXISTS idx_events_stream_seq ON events(stream, seq);

-- 人工疗程表 (Course)
CREATE TABLE IF NOT EXISTS courses (
  course_id TEXT PRIMARY KEY,
  therapy TEXT NOT NULL,
  title TEXT NOT NULL,
  input_mode TEXT NOT NULL DEFAULT 'natural', -- natural, roleplay
  roleplay_card TEXT, -- 仅供审计，不注入咨询师已知档案
  status TEXT NOT NULL DEFAULT 'active', -- active, closed
  close_reason TEXT, -- completed, participant_ended, safety_risk, etc.
  skill_release_id TEXT,
  prompt_tree_version TEXT,
  config_hash TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 人工会谈表 (CourseSession)
CREATE TABLE IF NOT EXISTS course_sessions (
  course_id TEXT NOT NULL,
  session_index INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', -- open, closing, closed, close_failed
  plan_json TEXT NOT NULL,
  memory_before_json TEXT NOT NULL,
  memory_after_json TEXT,
  next_plan_json TEXT,
  review_json TEXT,
  close_reason TEXT,
  created_at TEXT NOT NULL,
  closed_at TEXT,
  PRIMARY KEY(course_id, session_index)
);

-- 人工对话消息 (CourseMessage)
CREATE TABLE IF NOT EXISTS course_messages (
  message_id TEXT PRIMARY KEY,
  course_id TEXT NOT NULL,
  session_index INTEGER NOT NULL,
  role TEXT NOT NULL, -- counselor, participant, system
  source TEXT NOT NULL, -- participant_natural, participant_roleplay, counselor, system
  content TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_course_messages_session ON course_messages(course_id, session_index, created_at);

-- 人工会谈操作表 (CourseOperation，用于幂等调用与生成锁)
CREATE TABLE IF NOT EXISTS course_operations (
  operation_id TEXT PRIMARY KEY,
  course_id TEXT NOT NULL,
  session_index INTEGER NOT NULL,
  kind TEXT NOT NULL, -- opening, message, close_session, close_course
  status TEXT NOT NULL DEFAULT 'pending', -- pending, running, succeeded, failed
  expected_version INTEGER NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 会后整理分步记录
CREATE TABLE IF NOT EXISTS course_close_steps (
  course_id TEXT NOT NULL,
  session_index INTEGER NOT NULL,
  step_name TEXT NOT NULL, -- extract, merge, summary, consolidate, review, plan
  status TEXT NOT NULL, -- succeeded, failed, skipped
  input_summary_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(course_id, session_index, step_name)
);

-- 技能不可变发布快照 (SkillRelease)
CREATE TABLE IF NOT EXISTS skill_releases (
  release_id TEXT PRIMARY KEY,
  therapy TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  tree_hash TEXT NOT NULL,
  parent_release_id TEXT,
  overlay_skills_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 各流派活动技能发布指针 (支持无损回滚)
CREATE TABLE IF NOT EXISTS active_skill_releases (
  therapy TEXT PRIMARY KEY,
  release_id TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 技能演化修改提案 (SkillProposal)
CREATE TABLE IF NOT EXISTS skill_proposals (
  proposal_id TEXT PRIMARY KEY,
  therapy TEXT NOT NULL,
  base_release_id TEXT NOT NULL,
  title TEXT NOT NULL,
  target_skill_id TEXT,
  parent_meta_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  content_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', -- draft, validated, replayed, simulated, reviewed, approved, rejected, published
  justification TEXT NOT NULL,
  author TEXT NOT NULL,
  validation_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 专家审核记录 (ExpertReview，真实审核者与回避原则)
CREATE TABLE IF NOT EXISTS expert_reviews (
  review_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  reviewer_name TEXT NOT NULL,
  verdict TEXT NOT NULL, -- approve, reject, revise
  rationale TEXT NOT NULL,
  checklist_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_expert_reviews_proposal ON expert_reviews(proposal_id);

-- 回放与验证仿真记录
CREATE TABLE IF NOT EXISTS replay_validations (
  validation_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  replay_type TEXT NOT NULL, -- fixed_context, simulation
  status TEXT NOT NULL, -- pending, running, completed, failed
  candidate_outputs_json TEXT NOT NULL DEFAULT '{}',
  baseline_outputs_json TEXT NOT NULL DEFAULT '{}',
  diff_summary TEXT NOT NULL DEFAULT '',
  error TEXT,
  created_at TEXT NOT NULL
);

-- 训练数据导出审计
CREATE TABLE IF NOT EXISTS export_audits (
  export_id TEXT PRIMARY KEY,
  export_type TEXT NOT NULL, -- sft, dpo
  criteria_json TEXT NOT NULL,
  output_path TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  split_info_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def get_db_path(explicit_path: Path | str | None = None) -> Path:
    if explicit_path:
        return Path(explicit_path)
    env_path = os.getenv("PSYCHSANDBOX_WORKBENCH_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_WORKBENCH_DB


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = get_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        target,
        timeout=10.0,
        isolation_level=None,  # 自动事务管理配合显式 BEGIN IMMEDIATE
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


@contextmanager
def db_transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """写事务上下文：使用 BEGIN IMMEDIATE 并在退出时提交或回滚"""
    conn.execute("BEGIN IMMEDIATE;")
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def init_db(db_path: Path | str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
