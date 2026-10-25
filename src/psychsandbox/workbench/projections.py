"""科研 Web 工作台只读数据投影层 (Projections)

严格实现受控字段投影：
1. 隐藏私密画像：不向浏览器暴露 ClientProfile 私密 facts 与未解锁隐秘；
2. 历史轮次仅反映当时保存的上下文；缺少快照时明确标记为未记录；
3. 严格区分会后自评、规则审计、RFT 候选奖励和最终整体督导；
4. 提供案例库、流派元数据与正式运行记录读取。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..datasets import CaseRepository
from ..domain import CounselingCase
from ..therapies import list_therapy_profiles, normalize_therapy_id
from ..artifacts import find_run_dir
from .models import (
    CaseSummary,
    RunDetailProjection,
    RunSummaryProjection,
)
from ..runtime.storage import SQLiteStore


def list_therapy_definitions() -> list[dict[str, Any]]:
    therapies = []
    for profile in list_therapy_profiles():
        norm_id = normalize_therapy_id(profile.therapy_id)
        therapies.append({
            "therapy": norm_id,
            "therapy_id": norm_id,
            "name": profile.display_name,
            "description": profile.conceptualization_focus,
            "stages": [
                {
                    "stage_id": s.value if hasattr(s, "value") else str(s),
                    "name": s.value if hasattr(s, "value") else str(s),
                    "description": "; ".join(goals),
                }
                for s, goals in profile.stage_goals.items()
            ],
            "instruments": [],
        })
    return therapies


def list_case_summaries(repo: CaseRepository) -> list[CaseSummary]:
    summaries = []
    for case in repo.list():
        st = case.profile.static_traits
        age_val = None
        if st.age:
            cleaned = st.age.replace("岁", "").strip()
            if cleaned.isdigit():
                age_val = int(cleaned)
        summaries.append(
            CaseSummary(
                case_id=case.case_id,
                therapy=case.therapy,
                title=st.name or case.case_id,
                client_name=st.name or "匿名来访者",
                client_gender=st.gender or "未知",
                client_age=age_val,
                client_occupation=st.occupation or "未知",
                summary=case.profile.main_problem or case.profile.topic or "",
                available_sessions=len(case.reference_sessions) or 3,
            )
        )
    return summaries


def _get_store_connection(store: SQLiteStore) -> sqlite3.Connection:
    conn = sqlite3.connect(str(store.path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def list_experiment_runs(store: SQLiteStore, trace_dir: Path) -> list[RunSummaryProjection]:
    runs = []
    conn = _get_store_connection(store)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT r.run_id, r.case_id, r.therapy, r.provider, r.seed, r.status, r.created_at, r.completed_at,
                      (SELECT COUNT(*) FROM sessions s WHERE s.run_id = r.run_id) AS session_count,
                      (SELECT h.report_json FROM holistic_evaluations h WHERE h.run_id = r.run_id) AS holistic_json
               FROM experiment_runs r
               ORDER BY r.created_at DESC"""
        )
        for row in cur.fetchall():
            run_id = row["run_id"]
            holistic_score = None
            if row["holistic_json"]:
                try:
                    h_data = json.loads(row["holistic_json"])
                    holistic_score = h_data.get("holistic_score") or h_data.get("overall_score")
                except Exception:
                    pass

            # 检查是否有 HTML 报告
            has_html = False
            try:
                r_dir = find_run_dir(trace_dir, run_id)
                if (r_dir / "report.html").exists():
                    has_html = True
            except Exception:
                pass

            runs.append(
                RunSummaryProjection(
                    run_id=run_id,
                    case_id=row["case_id"],
                    therapy=row["therapy"],
                    provider=row["provider"],
                    seed=row["seed"],
                    status=row["status"],
                    completed_sessions=row["session_count"] or 0,
                    created_at=row["created_at"],
                    completed_at=row["completed_at"],
                    has_html_report=has_html,
                    holistic_score=holistic_score,
                )
            )
        return runs
    finally:
        conn.close()


def get_run_detail(
    store: SQLiteStore, trace_dir: Path, run_id: str
) -> RunDetailProjection | None:
    conn = _get_store_connection(store)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM experiment_runs WHERE run_id = ?", (run_id,))
        run_row = cur.fetchone()
        if not run_row:
            return None

        # 加载已提交的 sessions
        cur.execute(
            "SELECT session_index, session_json FROM sessions WHERE run_id = ? ORDER BY session_index ASC",
            (run_id,),
        )
        sessions_data = []
        for s_row in cur.fetchall():
            s_idx = s_row["session_index"]
            s_obj = json.loads(s_row["session_json"])

            # 读取该 session 的 memory 快照
            cur.execute(
                "SELECT memory_json FROM memories WHERE run_id = ? AND session_index = ?",
                (run_id, s_idx),
            )
            mem_row = cur.fetchone()
            memory_dict = json.loads(mem_row["memory_json"]) if mem_row else None

            # 受控投影：脱敏 turn 与决策
            projected_turns = []
            for turn in s_obj.get("turn_records", []):
                decision = turn.get("counselor_turn", {}).get("decision")
                planner_reasoning = decision.get("reasoning", "") if decision else ""
                skill_evidence = decision.get("skill_evidence", []) if decision else []
                chosen_skills = decision.get("skills_selected", []) if decision else []

                projected_turns.append({
                    "turn_index": turn.get("turn_index"),
                    "client_utterance": turn.get("client_turn", {}).get("utterance"),
                    "counselor_response": turn.get("counselor_turn", {}).get("utterance"),
                    "counselor_plan_summary": planner_reasoning,
                    "chosen_skills": chosen_skills,
                    "skill_evidence": skill_evidence,
                    "safety_events": turn.get("counselor_turn", {}).get("safety_events", []),
                    "context_snapshot_available": bool(turn.get("counselor_turn", {}).get("context_payload")),
                })

            sessions_data.append({
                "session_index": s_idx,
                "plan": s_obj.get("plan"),
                "summary": s_obj.get("summary"),
                "clinical_summary": s_obj.get("clinical_summary"),
                "counselor_review": s_obj.get("counselor_review"),
                "longitudinal_report": s_obj.get("longitudinal_report"),
                "safety_verdict": s_obj.get("safety_verdict"),
                "turns": projected_turns,
                "memory_snapshot": memory_dict,
                "end_reason": s_obj.get("end_reason"),
            })

        # 读取整体督导报告
        cur.execute("SELECT report_json FROM holistic_evaluations WHERE run_id = ?", (run_id,))
        h_row = cur.fetchone()
        holistic_report = json.loads(h_row["report_json"]) if h_row else None

        # 读取 RFT 批次与候选对比
        cur.execute(
            "SELECT batch_id, session_index, selection_json FROM rollout_batches WHERE run_id = ? ORDER BY session_index ASC",
            (run_id,),
        )
        rft_batches = []
        for b_row in cur.fetchall():
            bid = b_row["batch_id"]
            sel = json.loads(b_row["selection_json"])
            # 获取候选记录
            cur.execute(
                "SELECT candidate_index, candidate_json FROM rollout_candidates WHERE batch_id = ? ORDER BY candidate_index ASC",
                (bid,),
            )
            candidates = []
            for c_row in cur.fetchall():
                c_data = json.loads(c_row["candidate_json"])
                # 脱敏候选
                candidates.append({
                    "candidate_index": c_row["candidate_index"],
                    "status": c_data.get("status"),
                    "total_reward": c_data.get("reward", {}).get("total") if c_data.get("reward") else None,
                    "safety_passed": c_data.get("safety_passed", False),
                    "assessment": c_data.get("assessment"),
                    "summary": c_data.get("summary"),
                })
            rft_batches.append({
                "batch_id": bid,
                "session_index": b_row["session_index"],
                "selection": sel,
                "candidates": candidates,
            })

        config_dict = json.loads(run_row["config_json"]) if run_row["config_json"] else {}
        # 清理密钥敏感字段
        if "api_key" in config_dict:
            config_dict["api_key"] = "***"

        return RunDetailProjection(
            run_id=run_id,
            case_id=run_row["case_id"],
            therapy=run_row["therapy"],
            provider=run_row["provider"],
            seed=run_row["seed"],
            status=run_row["status"],
            created_at=run_row["created_at"],
            completed_at=run_row["completed_at"],
            sessions=sessions_data,
            holistic_report=holistic_report,
            rft_batches=rft_batches,
            config=config_dict,
        )
    finally:
        conn.close()
