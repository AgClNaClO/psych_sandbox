"""科研 Web 工作台 FastAPI 端到端 API 集成回归测试

涵盖：
1. 流派与受控案例投影 API (无未披露事实泄漏)；
2. 任务调度与会谈边界停止控制 API；
3. 人工多会谈疗程创建、版本乐观锁与消息发送 API；
4. 技能实验室扩展层提案、作者回避审核、发布与回滚 API；
5. 多源评测大盘与 SFT/DPO 合规导出审计 API；
6. 静态前端资源挂载与服务 API。
"""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from psychsandbox.workbench.api import create_app
from psychsandbox.workbench.db import init_db
from psychsandbox.runtime.storage import SQLiteStore
from tests.deterministic_gateway import DeterministicGateway


@pytest.fixture
def workbench_client(tmp_path: Path):
    db_path = str(tmp_path / "test_wb.sqlite3")
    sim_db_path = str(tmp_path / "test_sim.sqlite3")

    init_db(db_path)
    sim_store = SQLiteStore(sim_db_path)

    # 创建一条实验记录供评测大盘与导出读取
    cur = sim_store.connection.cursor()
    cur.execute(
        """INSERT INTO experiment_runs (run_id, case_id, therapy, provider, seed, status, config_json, created_at)
           VALUES ('run-api-test-01', 'case_depression_01', 'cbt', 'deterministic', 42, 'completed', '{}', datetime('now'))"""
    )
    sim_store.connection.commit()

    # 模拟前端 dist 目录与 index.html
    f_dir = tmp_path / "frontend_dist"
    f_dir.mkdir(parents=True, exist_ok=True)
    (f_dir / "index.html").write_text("<!DOCTYPE html><html><body>PsychSandbox Frontend</body></html>", encoding="utf-8")

    app = create_app(
        db_path=db_path,
        sim_db_path=Path(sim_db_path),
        frontend_dir=f_dir,
    )

    with TestClient(app) as client:
        yield client, db_path, sim_store


def test_api_therapies_and_cases(workbench_client):
    client, _, _ = workbench_client

    # 1. 查询流派列表
    resp = client.get("/api/therapies")
    assert resp.status_code == 200
    therapies = resp.json()
    assert len(therapies) == 5
    therapy_ids = [t["therapy_id"] for t in therapies]
    assert "cbt" in therapy_ids
    assert "behavioral" in therapy_ids

    # 2. 查询受控案例投影
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    cases = resp.json()
    assert len(cases) > 0
    first_case = cases[0]
    assert "case_id" in first_case
    assert "client_name" in first_case
    assert "client_gender" in first_case
    # 隐私保护断言：绝对不能直接暴露未披露的 private_notes 或内部全画像
    assert "private_notes" not in first_case
    assert "unconscious_conflict" not in first_case


def test_api_jobs_lifecycle(workbench_client):
    client, _, _ = workbench_client

    # 提交仿真长任务
    resp = client.post(
        "/api/jobs",
        json={
            "kind": "simulation",
            "lane": "long",
            "payload": {
                "case_id": "case_depression_01",
                "therapy": "cbt",
                "session_count": 2,
                "seed": 42,
            },
        },
    )
    assert resp.status_code == 200
    job = resp.json()
    job_id = job["job_id"]
    assert job["status"] == "queued"
    assert job["lane"] == "long"

    # 查询任务详情
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id

    # 请求会谈边界停止
    resp = client.post(f"/api/jobs/{job_id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stop_requested"


def test_api_interactive_courses_and_messages(workbench_client):
    client, _, _ = workbench_client

    # 1. 创建多会谈人工疗程
    resp = client.post(
        "/api/courses",
        json={
            "therapy": "cbt",
            "title": "API测试人工疗程",
            "input_mode": "natural",
        },
    )
    assert resp.status_code == 200
    course = resp.json()
    course_id = course["course_id"]
    assert course["version"] == 1
    assert course["status"] == "active"

    # 2. 查询疗程详情
    resp = client.get(f"/api/courses/{course_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["course_id"] == course_id

    # 3. 发送消息（带操作防重与乐观锁校验）
    msg_resp = client.post(
        f"/api/courses/{course_id}/sessions/1/messages",
        json={
            "message_id": "msg-api-01",
            "operation_id": "op-api-01",
            "expected_version": 1,
            "content": "您好，我最近总是感到非常压抑和绝望。",
            "source": "participant_natural",
        },
    )
    assert msg_resp.status_code == 200
    res_data = msg_resp.json()
    assert res_data["message"]["content"] == "您好，我最近总是感到非常压抑和绝望。"
    assert res_data["operation"]["status"] in ("pending", "processing", "completed")

    # 4. 幂等性测试：使用相同 message_id 再次发送，应立即返回原记录
    idemp_resp = client.post(
        f"/api/courses/{course_id}/sessions/1/messages",
        json={
            "message_id": "msg-api-01",
            "operation_id": "op-api-01",
            "expected_version": 1,
            "content": "您好，我最近总是感到非常压抑和绝望。",
            "source": "participant_natural",
        },
    )
    assert idemp_resp.status_code == 200
    assert idemp_resp.json()["message"]["message_id"] == "msg-api-01"

    # 5. 乐观锁冲突测试：错误的 expected_version 应被拒绝 (409 Conflict)
    conflict_resp = client.post(
        f"/api/courses/{course_id}/sessions/1/messages",
        json={
            "message_id": "msg-api-02",
            "operation_id": "op-api-02",
            "expected_version": 999,
            "content": "冲突测试消息",
        },
    )
    assert conflict_resp.status_code == 409


def test_api_skill_evolution_lifecycle(workbench_client):
    client, _, _ = workbench_client

    # 1. 提交技能修改提案
    prop_resp = client.post(
        "/api/skills/proposals",
        json={
            "therapy": "cbt",
            "title": "API测试新增思维日记技能",
            "parent_meta_id": "285",
            "stage": "intervention",
            "content": {
                "name": "自动思维日记记录法",
                "description": "通过情境、情绪、自动思维、替代认知四栏进行记录与检验",
                "timing": "在来访者识别情绪波动诱因后使用",
                "triggers": ["日记", "表格", "自动思维", "记录"],
            },
            "justification": "补充来访者在会谈间期的客观自我监察工具",
            "author": "Researcher_Alice",
        },
    )
    assert prop_resp.status_code == 200
    prop_data = prop_resp.json()
    proposal_id = prop_data["proposal_id"]
    assert prop_data["status"] == "draft"

    # 2. 专家审核回避测试：作者 Alice 尝试自审，后端必须强制拒绝 (400 Bad Request)
    self_review_resp = client.post(
        f"/api/skills/proposals/{proposal_id}/reviews",
        json={
            "reviewer_id": "Researcher_Alice",
            "reviewer_name": "爱丽丝 (作者自审)",
            "verdict": "approve",
            "rationale": "我自己觉得写得很好",
            "checklist": {"scientific_validity": True, "safety_aligned": True},
        },
    )
    assert self_review_resp.status_code == 400
    assert "回避" in self_review_resp.json()["detail"] or "Author cannot review" in self_review_resp.json()["detail"]

    # 3. 独立专家 Bob 审核批准
    valid_review_resp = client.post(
        f"/api/skills/proposals/{proposal_id}/reviews",
        json={
            "reviewer_id": "Supervisor_Bob",
            "reviewer_name": "鲍勃督导 (独立临床专家)",
            "verdict": "approve",
            "rationale": "符合 CBT 循证规范，适用时机明确，准予批准发布。",
            "checklist": {"scientific_validity": True, "safety_aligned": True},
        },
    )
    assert valid_review_resp.status_code == 200
    assert valid_review_resp.json()["verdict"] == "approve"
    prop_detail = client.get(f"/api/skills/proposals/{proposal_id}").json()
    assert prop_detail["status"] == "approved"

    # 4. 批准发布为不可变快照
    publish_resp = client.post(
        f"/api/skills/proposals/{proposal_id}/publish?published_by=Director_Charlie&release_name=CBT-Release-v1.1"
    )
    assert publish_resp.status_code == 200
    release = publish_resp.json()
    release_id = release["release_id"]
    assert release["is_active"] is True
    assert release["tree_hash"] is not None

    # 5. 一键安全回滚
    rollback_resp = client.post(f"/api/skills/releases/{release_id}/rollback?therapy=cbt")
    assert rollback_resp.status_code == 200


def test_api_analytics_and_audited_exports(workbench_client, tmp_path: Path):
    client, _, _ = workbench_client

    # 1. 评测中心横向对比大盘
    comp_resp = client.get("/api/analytics/comparisons")
    assert comp_resp.status_code == 200
    rows = comp_resp.json()
    assert len(rows) >= 1
    first_row = rows[0]
    assert first_row["run_id"] == "run-api-test-01"
    # 核心约束断言：未真实发生的人工评分或成本不能胡乱填 0，必须保持真实的 None
    assert first_row["human_feedback_score"] is None
    assert first_row["cost_estimate_cny"] is None

    # 2. SFT 合规导出
    sft_resp = client.post(
        "/api/exports/sft",
        json={
            "run_ids": ["run-api-test-01"],
            "output_filename": "api_test_sft.jsonl",
            "include_interactive": False,
        },
    )
    assert sft_resp.status_code == 200
    sft_audit = sft_resp.json()
    assert sft_audit["export_type"] == "sft"
    assert "sha256" in sft_audit
    assert "split_info" in sft_audit

    # 3. DPO 偏好对合规导出
    dpo_resp = client.post(
        "/api/exports/dpo",
        json={
            "run_ids": ["run-api-test-01"],
            "output_filename": "api_test_dpo.jsonl",
        },
    )
    assert dpo_resp.status_code == 200
    dpo_audit = dpo_resp.json()
    assert dpo_audit["export_type"] == "dpo"
    assert "sha256" in dpo_audit

    # 4. 查询导出审计记录列表
    audits_resp = client.get("/api/exports/audits")
    assert audits_resp.status_code == 200
    audits_list = audits_resp.json()
    assert len(audits_list) >= 2


def test_api_frontend_static_serving(workbench_client):
    client, _, _ = workbench_client

    # 验证静态单页应用首页托管
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PsychSandbox Frontend" in resp.text
