"""科研 Web 工作台可靠数据导出与实验比较分析 (Export & Analytics)

核心约束：
1. SFT：受控合法上下文，包含来源、哈希、脱敏状态与用途；
2. DPO：同一 RFT 批次、同一提示上下文内配对；严禁跨轨迹末句配凑；严禁将失败或安全不合格输出当作低分负例；
3. 数据集划分：按案例哈希划分，同案例全候选归入同划分，测试集隔离；
4. 人工数据默认排除；
5. 导出审计完整留痕 (export_audits)；
6. 实验对比：模型评分、人工反馈、自动仿真分栏对比，真实汇报延迟/成本/不确定性，无数据时明确标注未知不填零。
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .db import db_transaction, get_connection
from .models import (
    ExportAuditResponse,
    ExperimentComparisonRow,
    MetricStats,
)
from ..domain import utc_now
from ..domain import SessionMemory
from ..runtime.memory_view import MemoryViewBuilder
from ..runtime.storage import SQLiteStore


def _stable_case_split(case_id: str, train_ratio: float = 0.7, val_ratio: float = 0.15) -> str:
    """基于 case_id 的确定性 SHA-256 哈希划分，同案例全候选归入同一划分"""
    h = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16)
    score = (h % 10000) / 10000.0
    if score < train_ratio:
        return "train"
    elif score < train_ratio + val_ratio:
        return "val"
    else:
        return "test"


def _public_memory(value: dict[str, Any]) -> dict[str, Any]:
    return MemoryViewBuilder().build(SessionMemory.model_validate(value)) if value else {}


def _dialogue(session: dict[str, Any]) -> list[dict[str, str]]:
    """Use stored, ordered messages rather than private generation/debug fields."""
    roles = {"client": "user", "counselor": "assistant"}
    return [
        {"role": roles[message["role"]], "content": message["content"]}
        for message in session.get("messages", [])
        if message.get("role") in roles and message.get("content")
    ]


def _first_response_pair(chosen: list[dict], rejected: list[dict]):
    prefix = []
    for left, right in zip(chosen, rejected):
        if left == right:
            prefix.append(left)
            continue
        if left["role"] == right["role"] == "assistant":
            return prefix, left["content"], right["content"]
        return None
    return None


class DataExporter:
    def __init__(self, sim_store: SQLiteStore, workbench_db_path: str | None = None):
        self.sim_store = sim_store
        self.wb_db_path = workbench_db_path

    def _get_sim_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.sim_store.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def export_sft(
        self,
        output_path: Path,
        run_ids: list[str] | None = None,
        created_by: str = "researcher",
        protocol_version: str = "v1",
        include_interactive: bool = False,
    ) -> ExportAuditResponse:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sim_conn = self._get_sim_conn()
        try:
            cur = sim_conn.cursor()

            query = """SELECT r.run_id, r.case_id, r.therapy, s.session_index, s.session_json, t.trajectory_json
                       FROM experiment_runs r
                       JOIN sessions s ON s.run_id = r.run_id
                       LEFT JOIN trajectories t ON t.run_id = r.run_id AND t.session_index = s.session_index"""
            params = []
            if run_ids is not None:
                placeholders = ",".join(["?"] * len(run_ids))
                query += f" WHERE r.run_id IN ({placeholders})" if run_ids else " WHERE 0"
                params.extend(run_ids)
            query += " ORDER BY r.run_id, s.session_index"

            cur.execute(query, params)
            records = cur.fetchall()
        finally:
            sim_conn.close()

        sft_rows = []
        split_counts = {"train": 0, "val": 0, "test": 0}

        for r in records:
            case_id = r["case_id"]
            run_id = r["run_id"]
            therapy = r["therapy"]
            s_idx = r["session_index"]

            split = _stable_case_split(case_id)
            sess_data = json.loads(r["session_json"])
            trajectory = json.loads(r["trajectory_json"]) if r["trajectory_json"] else {}
            # The memories table is post-session; it leaks future evidence into earlier turns.
            mem_data = _public_memory(trajectory.get("memory_before") or {})

            turn_records = sess_data.get("turn_records", [])
            dialogue_history = []
            counselor_index = 0
            for message in _dialogue(sess_data):
                if message["role"] == "assistant":
                    t = turn_records[counselor_index] if counselor_index < len(turn_records) else {}
                    counselor_index += 1
                    # 受控上下文：包含合法前缀、记忆、目标和安全事件
                    row = {
                        "source": "simulation_committed",
                        "run_id": run_id,
                        "case_id": case_id,
                        "therapy": therapy,
                        "session_index": s_idx,
                        "split": split,
                        "allowed_use": ["model_training", "research"],
                        "anonymized": False,
                        "protocol_version": protocol_version,
                        "system_prompt": f"你是一名专业的{therapy}心理咨询师。",
                        "dialogue_context": list(dialogue_history),
                        "counselor_response": message["content"],
                        "structured_planning": t.get("planning"),
                        "skill_evidence": (t.get("decision") or {}).get("skill_evidence", []),
                        "memory_context": mem_data,
                        "context_reconstructed": True,
                        "memory_snapshot_available": bool(trajectory.get("memory_before")),
                    }
                    raw_bytes = json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
                    row["row_hash"] = hashlib.sha256(raw_bytes).hexdigest()
                    sft_rows.append(row)
                    split_counts[split] += 1

                dialogue_history.append(message)

        # 人工数据默认排除：仅当明确请求 include_interactive 时，才加入已完成且闭环的人工会谈
        if include_interactive and self.wb_db_path:
            conn = get_connection(self.wb_db_path)
            try:
                c_cur = conn.cursor()
                c_cur.execute(
                    """SELECT c.course_id, c.therapy, s.session_index, s.plan_json, s.memory_before_json
                       FROM courses c
                       JOIN course_sessions s ON s.course_id = c.course_id
                       WHERE s.status = 'closed'
                       ORDER BY c.course_id, s.session_index"""
                )
                courses_sessions = c_cur.fetchall()
                for cs in courses_sessions:
                    cid = cs["course_id"]
                    ther = cs["therapy"]
                    s_idx = cs["session_index"]
                    split = _stable_case_split(cid)

                    # 获取消息
                    c_cur.execute(
                        """SELECT role, source, content
                           FROM course_messages
                           WHERE course_id = ? AND session_index = ?
                           ORDER BY created_at ASC""",
                        (cid, s_idx),
                    )
                    msgs = c_cur.fetchall()
                    history = []
                    for m in msgs:
                        if m["role"] == "participant":
                            history.append({"role": "user", "content": m["content"]})
                        elif m["role"] == "counselor":
                            row = {
                                "source": "interactive_closed",
                                "course_id": cid,
                                "case_id": f"human_{cid}",
                                "therapy": ther,
                                "session_index": s_idx,
                                "split": split,
                                "allowed_use": ["model_training", "research_consent"],
                                "anonymized": False,
                                "protocol_version": protocol_version,
                                "system_prompt": f"你是一名专业的{ther}心理咨询师。",
                                "dialogue_context": list(history),
                                "counselor_response": m["content"],
                            }
                            raw_bytes = json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
                            row["row_hash"] = hashlib.sha256(raw_bytes).hexdigest()
                            sft_rows.append(row)
                            split_counts[split] += 1
                            history.append({"role": "assistant", "content": m["content"]})
            finally:
                conn.close()

        file_hash = hashlib.sha256()
        with output_path.open("w", encoding="utf-8") as f:
            for item in sft_rows:
                line = json.dumps(item, ensure_ascii=False) + "\n"
                f.write(line)
                file_hash.update(line.encode("utf-8"))

        sim_conn.close()

        sha256 = file_hash.hexdigest()
        audit_id = f"exp-{uuid.uuid4().hex[:12]}"
        now = utc_now()

        # 写入导出审计
        if self.wb_db_path:
            conn = get_connection(self.wb_db_path)
            try:
                with db_transaction(conn) as t_cur:
                    t_cur.execute(
                        """INSERT INTO export_audits
                        (export_id, export_type, criteria_json, output_path, row_count, split_info_json, sha256, created_by, created_at)
                        VALUES (?, 'sft', ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            audit_id,
                            json.dumps({"run_ids": run_ids, "include_interactive": include_interactive}),
                            str(output_path.resolve()),
                            len(sft_rows),
                            json.dumps(split_counts),
                            sha256,
                            created_by,
                            now,
                        ),
                    )
            finally:
                conn.close()

        return ExportAuditResponse(
            export_id=audit_id,
            export_type="sft",
            criteria={"run_ids": run_ids, "include_interactive": include_interactive},
            output_path=str(output_path),
            row_count=len(sft_rows),
            split_info=split_counts,
            sha256=sha256,
            created_by=created_by,
            created_at=now,
        )

    def export_dpo(
        self,
        output_path: Path,
        run_ids: list[str] | None = None,
        created_by: str = "researcher",
        protocol_version: str = "v1",
    ) -> ExportAuditResponse:
        """导出 DPO 偏好对：
        核心准则：
        1. 必须来自同一 RFT 批次、同一提示上下文 (prompt_context)；
        2. 严禁跨轨迹末句配凑；
        3. 严禁将失败或安全未通过输出作为低分负例；
        4. 排除人工数据。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sim_conn = self._get_sim_conn()
        try:
            cur = sim_conn.cursor()

            # 1. 查找所有有效的 RFT selection 记录
            query = """SELECT s.run_id, s.session_index, s.batch_id, s.selection_json,
                              r.case_id, r.therapy, t.trajectory_json
                       FROM rollout_batches s
                       JOIN experiment_runs r ON r.run_id = s.run_id
                       JOIN trajectories t ON t.run_id = s.run_id AND t.session_index = s.session_index"""
            params = []
            if run_ids is not None:
                placeholders = ",".join(["?"] * len(run_ids))
                query += f" WHERE s.run_id IN ({placeholders})" if run_ids else " WHERE 0"
                params.extend(run_ids)
            query += " ORDER BY s.run_id, s.session_index"

            cur.execute(query, params)
            selections = cur.fetchall()

            dpo_pairs = []
            split_counts = {"train": 0, "val": 0, "test": 0}

            for sel_row in selections:
                run_id = sel_row["run_id"]
                s_idx = sel_row["session_index"]
                bid = sel_row["batch_id"]
                case_id = sel_row["case_id"]
                therapy = sel_row["therapy"]
                sel = json.loads(sel_row["selection_json"])
                trajectory = json.loads(sel_row["trajectory_json"])
                committed_selection = (trajectory.get("session") or {}).get("rollout_selection") or {}
                if (sel.get("status") != "selected" or committed_selection.get("batch_id") != bid
                        or not trajectory.get("memory_before")):
                    continue
                winner_idx = sel.get("winner_index")

                # 2. 读取该批次所有的 candidate rollouts
                cur.execute(
                    """SELECT candidate_index, candidate_json
                       FROM rollout_candidates
                       WHERE batch_id = ?""",
                    (bid,),
                )
                candidates = {}
                for c in cur.fetchall():
                    c_idx = c["candidate_index"]
                    candidates[c_idx] = json.loads(c["candidate_json"])

                winner_candidate = candidates.get(winner_idx)
                winner_summary = (winner_candidate or {}).get("summary") or {}
                winner_session = (winner_candidate or {}).get("session") or {}
                if (winner_summary.get("status") != "selected"
                        or not (winner_session.get("safety_verdict") or {}).get("passed")):
                    continue

                winner_reward = (winner_summary.get("reward") or {}).get("total")
                winner_turns = _dialogue(winner_session)
                if not winner_turns or not isinstance(winner_reward, (int, float)) or not math.isfinite(winner_reward):
                    continue

                split = _stable_case_split(case_id)

                # 与该批次内其他合法落选候选配对
                for c_idx, candidate in candidates.items():
                    if c_idx == winner_idx:
                        continue
                    # 排除未通过安全门控、评分失败或取消的候选
                    summary = candidate.get("summary") or {}
                    session = candidate.get("session") or {}
                    if not (session.get("safety_verdict") or {}).get("passed"):
                        continue
                    if summary.get("status") != "eligible":
                        continue
                    cand_reward = (summary.get("reward") or {}).get("total")
                    if (not isinstance(cand_reward, (int, float)) or not math.isfinite(cand_reward)
                            or winner_reward <= cand_reward):
                        continue

                    cand_turns = _dialogue(session)
                    response_pair = _first_response_pair(winner_turns, cand_turns)
                    if response_pair is None:
                        continue

                    # 提取共同前缀/提示上下文
                    prefix, chosen_response, rejected_response = response_pair
                    input_context = {
                        "therapy": therapy,
                        "session_index": s_idx,
                        "plan": trajectory.get("plan"),
                        "memory_before": _public_memory(trajectory["memory_before"]),
                        "dialogue_context": prefix,
                    }

                    pair = {
                        "source": "simulation_rft",
                        "batch_id": bid,
                        "run_id": run_id,
                        "case_id": case_id,
                        "therapy": therapy,
                        "session_index": s_idx,
                        "preference_source": "model_judge_rft",
                        "split": split,
                        "allowed_use": ["model_training", "dpo"],
                        "anonymized": False,
                        "protocol_version": protocol_version,
                        "prompt_context": input_context,
                        "chosen_response": chosen_response,
                        "rejected_response": rejected_response,
                        "preference_unit": "first_divergent_counselor_turn",
                        "context_reconstructed": True,
                        "chosen_reward": winner_reward,
                        "rejected_reward": cand_reward,
                    }
                    raw_bytes = json.dumps(pair, sort_keys=True, ensure_ascii=False).encode("utf-8")
                    pair["pair_hash"] = hashlib.sha256(raw_bytes).hexdigest()
                    dpo_pairs.append(pair)
                    split_counts[split] += 1

            file_hash = hashlib.sha256()
            with output_path.open("w", encoding="utf-8") as f:
                for item in dpo_pairs:
                    line = json.dumps(item, ensure_ascii=False) + "\n"
                    f.write(line)
                    file_hash.update(line.encode("utf-8"))

        finally:
            sim_conn.close()

        sha256 = file_hash.hexdigest()
        audit_id = f"exp-{uuid.uuid4().hex[:12]}"
        now = utc_now()

        if self.wb_db_path:
            conn = get_connection(self.wb_db_path)
            try:
                with db_transaction(conn) as t_cur:
                    t_cur.execute(
                        """INSERT INTO export_audits
                        (export_id, export_type, criteria_json, output_path, row_count, split_info_json, sha256, created_by, created_at)
                        VALUES (?, 'dpo', ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            audit_id,
                            json.dumps({"run_ids": run_ids}),
                            str(output_path.resolve()),
                            len(dpo_pairs),
                            json.dumps(split_counts),
                            sha256,
                            created_by,
                            now,
                        ),
                    )
            finally:
                conn.close()

        return ExportAuditResponse(
            export_id=audit_id,
            export_type="dpo",
            criteria={"run_ids": run_ids},
            output_path=str(output_path),
            row_count=len(dpo_pairs),
            split_info=split_counts,
            sha256=sha256,
            created_by=created_by,
            created_at=now,
        )

    def list_audits(self) -> list[ExportAuditResponse]:
        if not self.wb_db_path:
            return []
        conn = get_connection(self.wb_db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT export_id, export_type, criteria_json, output_path, row_count,
                          split_info_json, sha256, created_by, created_at
                   FROM export_audits
                   ORDER BY created_at DESC"""
            )
            results = []
            for r in cur.fetchall():
                results.append(
                    ExportAuditResponse(
                        export_id=r["export_id"],
                        export_type=r["export_type"],
                        criteria=json.loads(r["criteria_json"]),
                        output_path=r["output_path"],
                        row_count=r["row_count"],
                        split_info=json.loads(r["split_info_json"]),
                        sha256=r["sha256"],
                        created_by=r["created_by"],
                        created_at=r["created_at"],
                    )
                )
            return results
        finally:
            conn.close()


class ExperimentAnalytics:
    def __init__(self, sim_store: SQLiteStore, wb_db_path: str | None = None):
        self.sim_store = sim_store
        self.wb_db_path = wb_db_path

    def get_comparison_rows(self) -> list[ExperimentComparisonRow]:
        conn = sqlite3.connect(str(self.sim_store.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT r.run_id, r.case_id, r.therapy, r.status, r.created_at,
                          (SELECT COUNT(*) FROM sessions s WHERE s.run_id = r.run_id) AS sess_cnt,
                          (SELECT h.report_json FROM holistic_evaluations h WHERE h.run_id = r.run_id) AS h_json
                   FROM experiment_runs r
                   ORDER BY r.created_at DESC"""
            )
            rows = []
            for r in cur.fetchall():
                run_id = r["run_id"]
                h_score = None
                if r["h_json"]:
                    try:
                        data = json.loads(r["h_json"])
                        h_score = next((data[key] for key in ("counselor_overall", "holistic_score", "overall_score")
                                        if data.get(key) is not None), None)
                    except Exception:
                        pass

                rows.append(
                    ExperimentComparisonRow(
                        run_id=run_id,
                        case_id=r["case_id"],
                        therapy=r["therapy"],
                        status=r["status"],
                        sessions_completed=r["sess_cnt"] or 0,
                        model_supervisor_score=h_score,
                        human_feedback_score=None,  # 真实人工反馈未发生时保持真实 None，不造假
                        auto_sim_score=None,
                        cost_estimate_cny=None,  # 无精确计量时显示 None（未知）
                        latency_sec_avg=None,
                        failure_rate=1.0 if r["status"] == "failed" else 0.0,
                        created_at=r["created_at"],
                    )
                )
            return rows
        finally:
            conn.close()

    def calculate_metric_stats(self, scores: list[float], metric_name: str) -> MetricStats:
        n = len(scores)
        if n == 0:
            return MetricStats(metric_name=metric_name, count=0, uncertainty_note="无数据")
        mean = sum(scores) / n
        if n < 2:
            return MetricStats(
                metric_name=metric_name,
                count=n,
                mean=mean,
                min_val=min(scores),
                max_val=max(scores),
                uncertainty_note="样本量 n=1，无法估计不确定性/方差",
            )
        variance = sum((x - mean) ** 2 for x in scores) / (n - 1)
        std = math.sqrt(variance)
        return MetricStats(
            metric_name=metric_name,
            count=n,
            mean=round(mean, 4),
            std=round(std, 4),
            min_val=min(scores),
            max_val=max(scores),
        )
