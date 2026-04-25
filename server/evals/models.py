"""
Pydantic 模型定义 - Eval 数据模型

包含：EvalTaskInput, EvalTaskExpected, EvalTaskMetadata, EvalTaskDef,
     EvalTrial, EvalGraderResult, EvalRun, QualityMetric, EvalTaskCandidate
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


# ── 枚举 ──────────────────────────────────────────────────────────────────


class EvalCategory(str, Enum):
    """评估任务类别"""
    INTENT_CLASSIFICATION = "intent_classification"
    COMMAND_GENERATION = "command_generation"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    SAFETY = "safety"
    MULTI_TURN = "multi_turn"


class EvalDifficulty(str, Enum):
    """评估任务难度"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class CandidateStatus(str, Enum):
    """候选任务审核状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── EvalTaskDef 嵌套模型 ──────────────────────────────────────────────────


class EvalTaskInput(BaseModel):
    """评估任务输入"""
    intent: str
    context: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class EvalTaskExpected(BaseModel):
    """评估任务预期输出"""
    response_type: List[str] = Field(default_factory=list)
    steps_contain: List[str] = Field(default_factory=list)
    steps_not_contain: List[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class EvalTaskMetadata(BaseModel):
    """评估任务元数据"""
    source: str = "yaml"
    difficulty: EvalDifficulty = EvalDifficulty.MEDIUM
    tags: List[str] = Field(default_factory=list)
    reference_solution: str = ""

    model_config = {"extra": "allow"}


# ── EvalTaskDef ───────────────────────────────────────────────────────────


class EvalTaskDef(BaseModel):
    """评估任务定义

    支持 YAML 加载，包含 id/category/description/input/expected/graders/metadata。
    """
    id: str
    category: EvalCategory
    description: str = ""
    input: EvalTaskInput
    expected: EvalTaskExpected = Field(default_factory=EvalTaskExpected)
    graders: List[str] = Field(default_factory=lambda: ["exact_match"])
    metadata: EvalTaskMetadata = Field(default_factory=EvalTaskMetadata)

    model_config = {"extra": "allow"}

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "EvalTaskDef":
        """从 YAML 解析后的字典创建实例"""
        return cls.model_validate(data)

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": self.id,
            "category": self.category.value,
            "description": self.description,
            "input_json": json.dumps(self.input.model_dump(), ensure_ascii=False),
            "expected_json": json.dumps(self.expected.model_dump(), ensure_ascii=False),
            "graders_json": json.dumps(self.graders, ensure_ascii=False),
            "metadata_json": json.dumps(self.metadata.model_dump(), ensure_ascii=False),
            "source": self.metadata.source,
            "created_at": now,
        }


# ── EvalTrial ─────────────────────────────────────────────────────────────


class EvalTrial(BaseModel):
    """评估试验记录"""
    trial_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    run_id: str
    transcript_json: List[Dict[str, Any]] = Field(default_factory=list)
    agent_result_json: Optional[Dict[str, Any]] = None
    duration_ms: int = 0
    token_usage_json: Dict[str, int] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        return {
            "trial_id": self.trial_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "transcript_json": json.dumps(self.transcript_json, ensure_ascii=False),
            "agent_result_json": json.dumps(
                self.agent_result_json, ensure_ascii=False
            )
            if self.agent_result_json
            else None,
            "duration_ms": self.duration_ms,
            "token_usage_json": json.dumps(self.token_usage_json, ensure_ascii=False),
            "created_at": self.created_at,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "EvalTrial":
        """从数据库行反序列化"""
        return cls(
            trial_id=row["trial_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            transcript_json=json.loads(row["transcript_json"])
            if row.get("transcript_json")
            else [],
            agent_result_json=json.loads(row["agent_result_json"])
            if row.get("agent_result_json")
            else None,
            duration_ms=row["duration_ms"],
            token_usage_json=json.loads(row["token_usage_json"])
            if row.get("token_usage_json")
            else {},
            created_at=row["created_at"],
        )


# ── EvalGraderResult ─────────────────────────────────────────────────────


class EvalGraderResult(BaseModel):
    """评分结果"""
    grader_id: str = Field(default_factory=lambda: uuid4().hex)
    trial_id: str
    grader_type: str
    passed: bool = False
    score: float = 0.0
    details_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        return {
            "grader_id": self.grader_id,
            "trial_id": self.trial_id,
            "grader_type": self.grader_type,
            "passed": 1 if self.passed else 0,
            "score": self.score,
            "details_json": json.dumps(self.details_json, ensure_ascii=False),
            "created_at": self.created_at,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "EvalGraderResult":
        """从数据库行反序列化"""
        return cls(
            grader_id=row["grader_id"],
            trial_id=row["trial_id"],
            grader_type=row["grader_type"],
            passed=bool(row["passed"]),
            score=row["score"],
            details_json=json.loads(row["details_json"])
            if row.get("details_json")
            else {},
            created_at=row["created_at"],
        )


# ── EvalRun ───────────────────────────────────────────────────────────────


class EvalRun(BaseModel):
    """评估运行记录"""
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    total_tasks: int = 0
    passed_tasks: int = 0
    config_json: Dict[str, Any] = Field(default_factory=dict)

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_tasks": self.total_tasks,
            "passed_tasks": self.passed_tasks,
            "config_json": json.dumps(self.config_json, ensure_ascii=False),
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "EvalRun":
        """从数据库行反序列化"""
        return cls(
            run_id=row["run_id"],
            started_at=row["started_at"],
            completed_at=row.get("completed_at"),
            total_tasks=row["total_tasks"],
            passed_tasks=row["passed_tasks"],
            config_json=json.loads(row["config_json"])
            if row.get("config_json")
            else {},
        )


# ── QualityMetric ─────────────────────────────────────────────────────────


class QualityMetric(BaseModel):
    """质量指标"""
    metric_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    user_id: str = ""
    device_id: str = ""
    metric_name: str
    value: float
    computed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        return {
            "metric_id": self.metric_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "device_id": self.device_id,
            "metric_name": self.metric_name,
            "value": self.value,
            "computed_at": self.computed_at,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "QualityMetric":
        """从数据库行反序列化"""
        return cls(
            metric_id=row["metric_id"],
            session_id=row["session_id"],
            user_id=row.get("user_id", ""),
            device_id=row.get("device_id", ""),
            metric_name=row["metric_name"],
            value=row["value"],
            computed_at=row["computed_at"],
        )


# ── EvalTaskCandidate ─────────────────────────────────────────────────────


class EvalTaskCandidate(BaseModel):
    """反馈闭环的候选任务"""
    candidate_id: str = Field(default_factory=lambda: uuid4().hex)
    source_feedback_id: str = ""
    suggested_intent: str
    suggested_category: str = EvalCategory.COMMAND_GENERATION.value
    suggested_expected_json: Dict[str, Any] = Field(default_factory=dict)
    status: CandidateStatus = CandidateStatus.PENDING
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_db_dict(self) -> Dict[str, Any]:
        """序列化为数据库存储格式"""
        return {
            "candidate_id": self.candidate_id,
            "source_feedback_id": self.source_feedback_id,
            "suggested_intent": self.suggested_intent,
            "suggested_category": self.suggested_category,
            "suggested_expected_json": json.dumps(
                self.suggested_expected_json, ensure_ascii=False
            ),
            "status": self.status.value,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "EvalTaskCandidate":
        """从数据库行反序列化"""
        return cls(
            candidate_id=row["candidate_id"],
            source_feedback_id=row.get("source_feedback_id", ""),
            suggested_intent=row["suggested_intent"],
            suggested_category=row["suggested_category"],
            suggested_expected_json=json.loads(row["suggested_expected_json"])
            if row.get("suggested_expected_json")
            else {},
            status=CandidateStatus(row["status"]),
            reviewed_by=row.get("reviewed_by"),
            reviewed_at=row.get("reviewed_at"),
            created_at=row["created_at"],
        )
