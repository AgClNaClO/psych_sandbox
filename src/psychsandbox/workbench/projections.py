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


def _to_standard_therapy_code(therapy: str) -> str:
    s = str(therapy).strip().lower().replace("-", "_")
    mapping = {
        "behavioral": "bt",
        "bt": "bt",
        "cbt": "cbt",
        "humanistic_existential": "het",
        "het": "het",
        "psychodynamic": "pdt",
        "pdt": "pdt",
        "postmodern": "pmt",
        "pmt": "pmt",
    }
    return mapping.get(s, s)


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
                therapy=_to_standard_therapy_code(case.therapy),
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
                    holistic_score = next((h_data[key] for key in (
                        "counselor_overall", "holistic_score", "overall_score"
                    ) if h_data.get(key) is not None), None)
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

            # 读取该 session 在 turns 表中的正式对话内容
            cur.execute(
                "SELECT turn_index, role, content FROM turns WHERE run_id = ? AND session_index = ? ORDER BY turn_index, role",
                (run_id, s_idx),
            )
            turns_text_map: dict[int, dict[str, str]] = {}
            for tr in cur.fetchall():
                t_idx_val = tr["turn_index"]
                if t_idx_val not in turns_text_map:
                    turns_text_map[t_idx_val] = {}
                turns_text_map[t_idx_val][tr["role"]] = tr["content"]

            # 受控投影：脱敏 turn 与决策
            projected_turns = []
            for turn in s_obj.get("turn_records", []):
                t_idx = turn.get("turn_index")
                decision = turn.get("decision") or turn.get("counselor_turn", {}).get("decision") or {}
                planning = turn.get("planning") or {}
                planner_reasoning = decision.get("reasoning") or decision.get("strategy") or planning.get("reasoning_summary") or ""
                skill_evidence = decision.get("skill_evidence") or []
                chosen_skills = decision.get("selected_atomic_skill_ids") or decision.get("skills_selected") or []

                # 对话内容优先从 turns 表读取，次之兼容各类数据结构
                table_texts = turns_text_map.get(t_idx, {})
                client_text = (
                    table_texts.get("client")
                    or turn.get("client_generation", {}).get("utterance")
                    or turn.get("client_input")
                    or turn.get("client_turn", {}).get("utterance")
                    or ""
                )
                counselor_text = (
                    table_texts.get("counselor")
                    or turn.get("counselor_response")
                    or turn.get("counselor_turn", {}).get("utterance")
                    or ""
                )

                projected_turns.append({
                    "turn_index": t_idx,
                    "client_utterance": client_text,
                    "counselor_response": counselor_text,
                    "counselor_plan_summary": planner_reasoning,
                    "chosen_skills": chosen_skills,
                    "skill_evidence": skill_evidence,
                    "safety_events": turn.get("output_safety", {}).get("evidence") or turn.get("counselor_turn", {}).get("safety_events", []),
                    "context_snapshot_available": bool(turn.get("context_payload") or turn.get("counselor_turn", {}).get("context_payload")),
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
        holistic_report = None
        if h_row and h_row["report_json"]:
            try:
                h_data = json.loads(h_row["report_json"])
                c_overall = next((h_data[key] for key in (
                    "counselor_overall", "holistic_score", "overall_score"
                ) if h_data.get(key) is not None), None)
                cl_overall = h_data.get("client_overall") if h_data.get("client_overall") is not None else h_data.get("client_score")
                h_data["holistic_score"] = c_overall
                h_data["client_score"] = cl_overall

                # 若无显式 summary，根据结构化量表自动组合多维度临床评估摘要
                if not h_data.get("summary"):
                    parts = []
                    if c_overall is not None:
                        parts.append(f"咨询师督导综合评分为 {c_overall:.2f}/10.0")
                    if cl_overall is not None:
                        parts.append(f"来访者综合评分为 {cl_overall:.2f}/10.0")

                    scale_scores = []
                    for item in h_data.get("counselor_specific", []):
                        if isinstance(item, dict) and "name" in item and "score" in item:
                            scale_scores.append(f"{item['name'].upper()}: {item['score']:.2f}")
                    for item in h_data.get("counselor_shared", []):
                        if isinstance(item, dict) and item.get("name") in ("wai", "htais", "rro") and "score" in item:
                            scale_scores.append(f"{item['name'].upper()}: {item['score']:.2f}")
                    for item in h_data.get("client_specific", []):
                        if isinstance(item, dict) and "name" in item and "score" in item:
                            scale_scores.append(f"{item['name'].upper()}: {item['score']:.2f}")

                    if scale_scores:
                        parts.append(f"核心量表表现（{', '.join(scale_scores)}）")
                    h_data["summary"] = "；".join(parts) + "。" if parts else "未记录督导评语。"
                holistic_report = h_data
            except Exception:
                holistic_report = None

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
