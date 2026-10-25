"""科研 Web 工作台技能实验室与演化闭环 (Skill Evolution & Laboratory)

严格遵守：
1. 原始五流派技能树只读；
2. 不可变技能发布快照 (SkillRelease) 与规范化 SHA-256 哈希；
3. 演化闭环：经验候选 -> 修改提案 -> 静态校验 -> 固定上下文单轮回放 -> 独立仿真 -> 专家审核 -> 批准发布 -> 回滚；
4. 真实专家审核制度（严格作者回避，禁止自动冒充专家，禁止按分数自动晋升）；
5. 固定上下文单轮对比与独立交互仿真明确分离，杜绝机械拼接旧台词冒充完整效果。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal
from pathlib import Path

from .db import db_transaction, get_connection
from .models import (
    SkillReleaseResponse,
    SkillProposalResponse,
    ExpertReviewResponse,
    ReplayValidationResponse,
)
from .events import get_event_hub
from ..domain import utc_now
from ..skills import SkillCatalog, SkillRegistry
from ..therapies import normalize_therapy_id


class EvolutionValidationError(Exception):
    """技能提案或操作校验失败"""
    pass


class SkillEvolutionLab:
    def __init__(self, db_path: str | None = None, assets_dir: Path | None = None):
        self.db_path = db_path
        self.assets_dir = assets_dir or Path("assets/skills/sect")
        self.events = get_event_hub(db_path)

    def compute_tree_hash(self, therapy: str, overlay: dict[str, Any] | None = None) -> str:
        """计算原始资产加扩展层的规范化哈希"""
        norm_therapy = normalize_therapy_id(therapy)
        tree_file = self.assets_dir / f"{norm_therapy}.json"
        raw_content = tree_file.read_bytes() if tree_file.exists() else b"{}"
        base_hash = hashlib.sha256(raw_content).hexdigest()
        overlay_str = json.dumps(overlay or {}, sort_keys=True, ensure_ascii=False)
        combined = f"{base_hash}:{hashlib.sha256(overlay_str.encode('utf-8')).hexdigest()}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def create_release(
        self,
        therapy: str,
        name: str,
        description: str,
        created_by: str,
        overlay_skills: dict[str, Any] | None = None,
        parent_release_id: str | None = None,
        set_active: bool = False,
    ) -> SkillReleaseResponse:
        norm_therapy = normalize_therapy_id(therapy)
        release_id = f"rel-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        tree_hash = self.compute_tree_hash(norm_therapy, overlay_skills)

        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT INTO skill_releases
                    (release_id, therapy, name, description, tree_hash, parent_release_id,
                     overlay_skills_json, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        release_id,
                        norm_therapy,
                        name,
                        description,
                        tree_hash,
                        parent_release_id,
                        json.dumps(overlay_skills or {}, ensure_ascii=False),
                        created_by,
                        now,
                    ),
                )
                if set_active:
                    cur.execute(
                        """INSERT OR REPLACE INTO active_skill_releases
                        (therapy, release_id, updated_at) VALUES (?, ?, ?)""",
                        (norm_therapy, release_id, now),
                    )

            self.events.emit(
                "skills",
                "release_created",
                {"release_id": release_id, "therapy": norm_therapy, "is_active": set_active},
            )
            return self.get_release(release_id)
        finally:
            conn.close()

    def get_release(self, release_id: str) -> SkillReleaseResponse | None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM skill_releases WHERE release_id = ?", (release_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "SELECT release_id FROM active_skill_releases WHERE therapy = ?",
                (row["therapy"],),
            )
            act_row = cur.fetchone()
            is_active = bool(act_row and act_row["release_id"] == release_id)

            return SkillReleaseResponse(
                release_id=row["release_id"],
                therapy=row["therapy"],
                name=row["name"],
                description=row["description"],
                tree_hash=row["tree_hash"],
                parent_release_id=row["parent_release_id"],
                overlay_skills=json.loads(row["overlay_skills_json"]),
                created_by=row["created_by"],
                created_at=row["created_at"],
                is_active=is_active,
            )
        finally:
            conn.close()

    def get_active_release(self, therapy: str) -> SkillReleaseResponse | None:
        norm_therapy = normalize_therapy_id(therapy)
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT release_id FROM active_skill_releases WHERE therapy = ?",
                (norm_therapy,),
            )
            row = cur.fetchone()
            if row:
                return self.get_release(row["release_id"])
            return None
        finally:
            conn.close()

    def list_releases(self, therapy: str | None = None) -> list[SkillReleaseResponse]:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            if therapy:
                norm_therapy = normalize_therapy_id(therapy)
                cur.execute(
                    "SELECT release_id FROM skill_releases WHERE therapy = ? ORDER BY created_at DESC",
                    (norm_therapy,),
                )
            else:
                cur.execute("SELECT release_id FROM skill_releases ORDER BY created_at DESC")
            return [self.get_release(r["release_id"]) for r in cur.fetchall()]
        finally:
            conn.close()

    def rollback_release(self, therapy: str, target_release_id: str) -> SkillReleaseResponse:
        """回滚活动技能版本指针到指定的历史发布"""
        norm_therapy = normalize_therapy_id(therapy)
        target = self.get_release(target_release_id)
        if not target or target.therapy != norm_therapy:
            raise EvolutionValidationError("Invalid target release for rollback")

        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT OR REPLACE INTO active_skill_releases
                    (therapy, release_id, updated_at) VALUES (?, ?, ?)""",
                    (norm_therapy, target_release_id, now),
                )
            self.events.emit(
                "skills",
                "release_rolled_back",
                {"therapy": norm_therapy, "active_release_id": target_release_id},
            )
            return self.get_release(target_release_id)
        finally:
            conn.close()

    def submit_proposal(
        self,
        therapy: str,
        base_release_id: str,
        title: str,
        target_skill_id: str | None,
        parent_meta_id: str,
        stage: str,
        content: dict[str, Any],
        justification: str,
        author: str,
    ) -> SkillProposalResponse:
        norm_therapy = normalize_therapy_id(therapy)
        # 静态结构校验
        required_fields = ["name", "description", "timing", "triggers"]
        for field in required_fields:
            if not content.get(field):
                raise EvolutionValidationError(f"Skill proposal content missing required field: {field}")

        if not justification or len(justification.strip()) < 5:
            raise EvolutionValidationError("Justification must contain at least 5 characters")

        if not author:
            raise EvolutionValidationError("Proposal author is required")

        proposal_id = f"prop-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT INTO skill_proposals
                    (proposal_id, therapy, base_release_id, title, target_skill_id,
                     parent_meta_id, stage, content_json, status, justification,
                     author, validation_summary_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, '{}', ?, ?)""",
                    (
                        proposal_id,
                        norm_therapy,
                        base_release_id,
                        title,
                        target_skill_id,
                        parent_meta_id,
                        stage,
                        json.dumps(content, ensure_ascii=False),
                        justification,
                        author,
                        now,
                        now,
                    ),
                )
            self.events.emit("skills", "proposal_created", {"proposal_id": proposal_id})
            return self.get_proposal(proposal_id)
        finally:
            conn.close()

    def get_proposal(self, proposal_id: str) -> SkillProposalResponse | None:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM skill_proposals WHERE proposal_id = ?", (proposal_id,))
            row = cur.fetchone()
            if not row:
                return None
            return SkillProposalResponse(
                proposal_id=row["proposal_id"],
                therapy=row["therapy"],
                base_release_id=row["base_release_id"],
                title=row["title"],
                target_skill_id=row["target_skill_id"],
                parent_meta_id=row["parent_meta_id"],
                stage=row["stage"],
                content=json.loads(row["content_json"]),
                status=row["status"],
                justification=row["justification"],
                author=row["author"],
                validation_summary=json.loads(row["validation_summary_json"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        finally:
            conn.close()

    def list_proposals(self, therapy: str | None = None) -> list[SkillProposalResponse]:
        conn = get_connection(self.db_path)
        try:
            cur = conn.cursor()
            if therapy:
                norm_therapy = normalize_therapy_id(therapy)
                cur.execute(
                    "SELECT proposal_id FROM skill_proposals WHERE therapy = ? ORDER BY created_at DESC",
                    (norm_therapy,),
                )
            else:
                cur.execute("SELECT proposal_id FROM skill_proposals ORDER BY created_at DESC")
            return [self.get_proposal(r["proposal_id"]) for r in cur.fetchall()]
        finally:
            conn.close()

    def record_replay_validation(
        self,
        proposal_id: str,
        replay_type: Literal["fixed_context", "simulation"],
        candidate_outputs: dict[str, Any],
        baseline_outputs: dict[str, Any],
        diff_summary: str,
    ) -> ReplayValidationResponse:
        """记录固定上下文回放或独立仿真验证结果"""
        val_id = f"val-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT INTO replay_validations
                    (validation_id, proposal_id, replay_type, status,
                     candidate_outputs_json, baseline_outputs_json, diff_summary, created_at)
                    VALUES (?, ?, ?, 'completed', ?, ?, ?, ?)""",
                    (
                        val_id,
                        proposal_id,
                        replay_type,
                        json.dumps(candidate_outputs, ensure_ascii=False),
                        json.dumps(baseline_outputs, ensure_ascii=False),
                        diff_summary,
                        now,
                    ),
                )
                target_status = "replayed" if replay_type == "fixed_context" else "simulated"
                cur.execute(
                    "UPDATE skill_proposals SET status = ?, updated_at = ? WHERE proposal_id = ?",
                    (target_status, now, proposal_id),
                )
            self.events.emit(
                "skills",
                "validation_recorded",
                {"proposal_id": proposal_id, "replay_type": replay_type},
            )
            return ReplayValidationResponse(
                validation_id=val_id,
                proposal_id=proposal_id,
                replay_type=replay_type,
                status="completed",
                candidate_outputs=candidate_outputs,
                baseline_outputs=baseline_outputs,
                diff_summary=diff_summary,
                created_at=now,
            )
        finally:
            conn.close()

    def submit_expert_review(
        self,
        proposal_id: str,
        reviewer_id: str,
        reviewer_name: str,
        verdict: Literal["approve", "reject", "revise"],
        rationale: str,
        checklist: dict[str, bool],
    ) -> ExpertReviewResponse:
        """提交真实专家审核记录。强制作者回避原则。"""
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise EvolutionValidationError("Proposal not found")

        # 严格回避原则：作者不能审核自己的提案
        if proposal.author.strip().lower() == reviewer_id.strip().lower() or proposal.author.strip().lower() == reviewer_name.strip().lower():
            raise EvolutionValidationError("Author cannot review their own proposal (conflict of interest)")

        if not rationale or len(rationale.strip()) < 10:
            raise EvolutionValidationError("Expert review rationale must be substantive (at least 10 chars)")

        review_id = f"rev-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    """INSERT INTO expert_reviews
                    (review_id, proposal_id, reviewer_id, reviewer_name, verdict, rationale, checklist_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        review_id,
                        proposal_id,
                        reviewer_id,
                        reviewer_name,
                        verdict,
                        rationale,
                        json.dumps(checklist, ensure_ascii=False),
                        now,
                    ),
                )
                # 更新提案状态
                if verdict == "approve":
                    new_status = "approved"
                elif verdict == "reject":
                    new_status = "rejected"
                else:
                    new_status = "draft"
                cur.execute(
                    "UPDATE skill_proposals SET status = ?, updated_at = ? WHERE proposal_id = ?",
                    (new_status, now, proposal_id),
                )
            self.events.emit(
                "skills",
                "review_submitted",
                {"proposal_id": proposal_id, "verdict": verdict, "reviewer": reviewer_name},
            )
            return ExpertReviewResponse(
                review_id=review_id,
                proposal_id=proposal_id,
                reviewer_id=reviewer_id,
                reviewer_name=reviewer_name,
                verdict=verdict,
                rationale=rationale,
                checklist=checklist,
                created_at=now,
            )
        finally:
            conn.close()

    def publish_approved_proposal(
        self,
        proposal_id: str,
        published_by: str,
        release_name: str,
    ) -> SkillReleaseResponse:
        """将已通过专家审核的提案合并到扩展层，并发布不可变新快照"""
        proposal = self.get_proposal(proposal_id)
        if not proposal or proposal.status != "approved":
            raise EvolutionValidationError("Only expert-approved proposals can be published")

        base_release = self.get_release(proposal.base_release_id)
        current_overlay = dict(base_release.overlay_skills) if base_release else {}

        target_id = proposal.target_skill_id or f"overlay:{proposal.therapy}:skill:{uuid.uuid4().hex[:8]}"
        current_overlay[target_id] = {
            "meta_id": proposal.parent_meta_id,
            "stage": proposal.stage,
            "data": proposal.content,
        }

        new_release = self.create_release(
            therapy=proposal.therapy,
            name=release_name,
            description=f"Published proposal: {proposal.title}",
            created_by=published_by,
            overlay_skills=current_overlay,
            parent_release_id=proposal.base_release_id,
            set_active=True,
        )

        now = utc_now()
        conn = get_connection(self.db_path)
        try:
            with db_transaction(conn) as cur:
                cur.execute(
                    "UPDATE skill_proposals SET status = 'published', updated_at = ? WHERE proposal_id = ?",
                    (now, proposal_id),
                )
            self.events.emit("skills", "proposal_published", {"proposal_id": proposal_id})
        finally:
            conn.close()

        return new_release
