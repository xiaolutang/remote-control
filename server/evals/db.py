"""
Eval 数据库层 - 独立 evals.db

6 张表：eval_task_defs, eval_trials, eval_grader_results,
        eval_runs, quality_metrics, eval_task_candidates

使用与 server/app/database.py 相同的 aiosqlite 异步模式。
评估配置独立于业务 agent，使用 EVAL_AGENT_* 环境变量。
"""
import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List, Optional, Any

import aiosqlite

from evals.models import (
    EvalTaskDef,
    EvalTrial,
    EvalGraderResult,
    EvalRun,
    QualityMetric,
    EvalTaskCandidate,
    CandidateStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_EVAL_DB_PATH = "/data/evals.db"


# ── 配置检查 ──────────────────────────────────────────────────────────────


class EvalConfigError(Exception):
    """评估配置缺失错误"""


def get_eval_agent_config() -> Dict[str, str]:
    """获取评估 Agent 配置。

    必须设置：
      - EVAL_AGENT_MODEL
      - EVAL_AGENT_BASE_URL
      - EVAL_AGENT_API_KEY

    可选：
      - EVAL_JUDGE_MODEL
      - EVAL_JUDGE_BASE_URL（默认 EVAL_AGENT_BASE_URL）
      - EVAL_JUDGE_API_KEY（默认 EVAL_AGENT_API_KEY）

    缺失必填项时 raise EvalConfigError，不复用 ASSISTANT_LLM_* 或 LLM_MODEL。
    不允许任何默认模型回退。
    """
    model = os.environ.get("EVAL_AGENT_MODEL")
    base_url = os.environ.get("EVAL_AGENT_BASE_URL")
    api_key = os.environ.get("EVAL_AGENT_API_KEY")

    missing = []
    if not model:
        missing.append("EVAL_AGENT_MODEL")
    if not base_url:
        missing.append("EVAL_AGENT_BASE_URL")
    if not api_key:
        missing.append("EVAL_AGENT_API_KEY")

    if missing:
        raise EvalConfigError(
            f"评估 Agent 配置缺失: {', '.join(missing)}。"
            f"请设置 EVAL_AGENT_MODEL / EVAL_AGENT_BASE_URL / EVAL_AGENT_API_KEY 环境变量。"
            f"不可复用 ASSISTANT_LLM_* 或 LLM_MODEL 等业务变量。"
        )

    config: Dict[str, str] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }

    # Judge 配置（可选，有默认值）
    judge_model = os.environ.get("EVAL_JUDGE_MODEL")
    if judge_model:
        config["judge_model"] = judge_model
    config["judge_base_url"] = os.environ.get(
        "EVAL_JUDGE_BASE_URL", base_url
    )
    config["judge_api_key"] = os.environ.get(
        "EVAL_JUDGE_API_KEY", api_key
    )

    return config


# ── 数据库类 ──────────────────────────────────────────────────────────────


class EvalDatabase:
    """Eval SQLite 数据库管理器

    与 app/database.py 使用相同的模式：
    - aiosqlite 异步连接
    - _connect 上下文管理器
    - init_db 创建表
    - datetime 使用 ISO 格式 TEXT 存储
    - JSON 字段存储为 TEXT，读写时做 json.loads/dumps
    """

    def __init__(self, db_path: str = DEFAULT_EVAL_DB_PATH):
        self.db_path = db_path

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """内部连接管理器，启用 FK 约束。"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def init_db(self) -> None:
        """初始化数据库，创建 6 张表（如果不存在）。"""
        async with self._connect() as db:
            # 1. eval_task_defs
            await db.execute("""
                CREATE TABLE IF NOT EXISTS eval_task_defs (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    input_json TEXT NOT NULL,
                    expected_json TEXT NOT NULL DEFAULT '{}',
                    graders_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'yaml',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_task_defs_category
                ON eval_task_defs(category)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_task_defs_source
                ON eval_task_defs(source)
            """)

            # 2. eval_trials
            await db.execute("""
                CREATE TABLE IF NOT EXISTS eval_trials (
                    trial_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    transcript_json TEXT NOT NULL DEFAULT '[]',
                    agent_result_json TEXT,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    token_usage_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_trials_task_id
                ON eval_trials(task_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_trials_run_id
                ON eval_trials(run_id)
            """)

            # 3. eval_grader_results
            await db.execute("""
                CREATE TABLE IF NOT EXISTS eval_grader_results (
                    grader_id TEXT PRIMARY KEY,
                    trial_id TEXT NOT NULL,
                    grader_type TEXT NOT NULL,
                    passed INTEGER NOT NULL DEFAULT 0,
                    score REAL NOT NULL DEFAULT 0.0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_grader_results_trial_id
                ON eval_grader_results(trial_id)
            """)

            # 4. eval_runs
            await db.execute("""
                CREATE TABLE IF NOT EXISTS eval_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    total_tasks INTEGER NOT NULL DEFAULT 0,
                    passed_tasks INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL DEFAULT '{}'
                )
            """)

            # 5. quality_metrics
            await db.execute("""
                CREATE TABLE IF NOT EXISTS quality_metrics (
                    metric_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    device_id TEXT NOT NULL DEFAULT '',
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    computed_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_quality_metrics_session_id
                ON quality_metrics(session_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_quality_metrics_name
                ON quality_metrics(metric_name)
            """)

            # 6. eval_task_candidates
            await db.execute("""
                CREATE TABLE IF NOT EXISTS eval_task_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    source_feedback_id TEXT NOT NULL DEFAULT '',
                    suggested_intent TEXT NOT NULL,
                    suggested_category TEXT NOT NULL,
                    suggested_expected_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_task_candidates_status
                ON eval_task_candidates(status)
            """)

            await db.commit()

    # ── EvalTaskDef CRUD ──────────────────────────────────────────────────

    async def save_task_def(self, task_def: EvalTaskDef) -> None:
        """保存评估任务定义（upsert）"""
        data = task_def.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO eval_task_defs
                    (id, category, description, input_json, expected_json,
                     graders_json, metadata_json, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["category"],
                    data["description"],
                    data["input_json"],
                    data["expected_json"],
                    data["graders_json"],
                    data["metadata_json"],
                    data["source"],
                    data["created_at"],
                ),
            )
            await db.commit()

    async def get_task_def(self, task_id: str) -> Optional[EvalTaskDef]:
        """获取评估任务定义"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_task_defs WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_task_def(dict(row))

    async def list_task_defs(
        self, category: Optional[str] = None, source: Optional[str] = None
    ) -> List[EvalTaskDef]:
        """列出评估任务定义"""
        async with self._connect() as db:
            query = "SELECT * FROM eval_task_defs"
            conditions: List[str] = []
            params: List[Any] = []

            if category:
                conditions.append("category = ?")
                params.append(category)
            if source:
                conditions.append("source = ?")
                params.append(source)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC"

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_task_def(dict(r)) for r in rows]

    async def delete_task_def(self, task_id: str) -> bool:
        """删除评估任务定义"""
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM eval_task_defs WHERE id = ?", (task_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    def _row_to_task_def(self, row: Dict[str, Any]) -> EvalTaskDef:
        """数据库行转换为 EvalTaskDef"""
        from evals.models import EvalTaskInput, EvalTaskExpected, EvalTaskMetadata

        input_data = json.loads(row["input_json"])
        expected_data = json.loads(row.get("expected_json") or "{}")
        metadata_data = json.loads(row.get("metadata_json") or "{}")
        graders_data = json.loads(row.get("graders_json") or "[]")

        return EvalTaskDef(
            id=row["id"],
            category=row["category"],
            description=row.get("description", ""),
            input=EvalTaskInput(**input_data),
            expected=EvalTaskExpected(**expected_data),
            graders=graders_data,
            metadata=EvalTaskMetadata(**metadata_data),
        )

    # ── EvalTrial CRUD ────────────────────────────────────────────────────

    async def save_trial(self, trial: EvalTrial) -> None:
        """保存评估试验"""
        data = trial.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO eval_trials
                    (trial_id, task_id, run_id, transcript_json, agent_result_json,
                     duration_ms, token_usage_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["trial_id"],
                    data["task_id"],
                    data["run_id"],
                    data["transcript_json"],
                    data["agent_result_json"],
                    data["duration_ms"],
                    data["token_usage_json"],
                    data["created_at"],
                ),
            )
            await db.commit()

    async def get_trial(self, trial_id: str) -> Optional[EvalTrial]:
        """获取评估试验"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_trials WHERE trial_id = ?", (trial_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return EvalTrial.from_db_row(dict(row))

    async def list_trials_by_run(self, run_id: str) -> List[EvalTrial]:
        """列出指定运行的所有试验"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_trials WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            )
            rows = await cursor.fetchall()
            return [EvalTrial.from_db_row(dict(r)) for r in rows]

    async def list_trials_by_task(self, task_id: str) -> List[EvalTrial]:
        """列出指定任务的所有试验"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_trials WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            )
            rows = await cursor.fetchall()
            return [EvalTrial.from_db_row(dict(r)) for r in rows]

    # ── EvalGraderResult CRUD ────────────────────────────────────────────

    async def save_grader_result(self, result: EvalGraderResult) -> None:
        """保存评分结果"""
        data = result.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO eval_grader_results
                    (grader_id, trial_id, grader_type, passed, score,
                     details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["grader_id"],
                    data["trial_id"],
                    data["grader_type"],
                    data["passed"],
                    data["score"],
                    data["details_json"],
                    data["created_at"],
                ),
            )
            await db.commit()

    async def get_grader_results_by_trial(self, trial_id: str) -> List[EvalGraderResult]:
        """获取指定试验的所有评分结果"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_grader_results WHERE trial_id = ? ORDER BY created_at",
                (trial_id,),
            )
            rows = await cursor.fetchall()
            return [EvalGraderResult.from_db_row(dict(r)) for r in rows]

    # ── EvalRun CRUD ──────────────────────────────────────────────────────

    async def save_run(self, run: EvalRun) -> None:
        """保存评估运行"""
        data = run.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO eval_runs
                    (run_id, started_at, completed_at, total_tasks, passed_tasks, config_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["run_id"],
                    data["started_at"],
                    data["completed_at"],
                    data["total_tasks"],
                    data["passed_tasks"],
                    data["config_json"],
                ),
            )
            await db.commit()

    async def get_run(self, run_id: str) -> Optional[EvalRun]:
        """获取评估运行"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_runs WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return EvalRun.from_db_row(dict(row))

    async def update_run_completion(
        self, run_id: str, completed_at: str, total_tasks: int, passed_tasks: int
    ) -> None:
        """更新运行完成状态"""
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE eval_runs
                SET completed_at = ?, total_tasks = ?, passed_tasks = ?
                WHERE run_id = ?
                """,
                (completed_at, total_tasks, passed_tasks, run_id),
            )
            await db.commit()

    async def list_runs(self, limit: int = 20) -> List[EvalRun]:
        """列出最近的评估运行"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [EvalRun.from_db_row(dict(r)) for r in rows]

    # ── QualityMetric CRUD ────────────────────────────────────────────────

    async def save_quality_metric(self, metric: QualityMetric) -> None:
        """保存质量指标"""
        data = metric.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO quality_metrics
                    (metric_id, session_id, user_id, device_id, metric_name, value, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["metric_id"],
                    data["session_id"],
                    data["user_id"],
                    data["device_id"],
                    data["metric_name"],
                    data["value"],
                    data["computed_at"],
                ),
            )
            await db.commit()

    async def get_quality_metrics_by_session(
        self, session_id: str
    ) -> List[QualityMetric]:
        """获取指定 session 的所有质量指标"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM quality_metrics WHERE session_id = ? ORDER BY computed_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return [QualityMetric.from_db_row(dict(r)) for r in rows]

    async def get_quality_metrics_by_name(
        self, metric_name: str, limit: int = 100
    ) -> List[QualityMetric]:
        """获取指定名称的质量指标"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM quality_metrics WHERE metric_name = ? ORDER BY computed_at DESC LIMIT ?",
                (metric_name, limit),
            )
            rows = await cursor.fetchall()
            return [QualityMetric.from_db_row(dict(r)) for r in rows]

    # ── EvalTaskCandidate CRUD ────────────────────────────────────────────

    async def save_task_candidate(self, candidate: EvalTaskCandidate) -> None:
        """保存候选任务"""
        data = candidate.to_db_dict()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO eval_task_candidates
                    (candidate_id, source_feedback_id, suggested_intent, suggested_category,
                     suggested_expected_json, status, reviewed_by, reviewed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["candidate_id"],
                    data["source_feedback_id"],
                    data["suggested_intent"],
                    data["suggested_category"],
                    data["suggested_expected_json"],
                    data["status"],
                    data["reviewed_by"],
                    data["reviewed_at"],
                    data["created_at"],
                ),
            )
            await db.commit()

    async def get_task_candidate(
        self, candidate_id: str
    ) -> Optional[EvalTaskCandidate]:
        """获取候选任务"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM eval_task_candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return EvalTaskCandidate.from_db_row(dict(row))

    async def list_task_candidates(
        self, status: Optional[str] = None
    ) -> List[EvalTaskCandidate]:
        """列出候选任务"""
        async with self._connect() as db:
            if status:
                cursor = await db.execute(
                    "SELECT * FROM eval_task_candidates WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM eval_task_candidates ORDER BY created_at DESC"
                )
            rows = await cursor.fetchall()
            return [EvalTaskCandidate.from_db_row(dict(r)) for r in rows]

    async def update_candidate_status(
        self,
        candidate_id: str,
        status: CandidateStatus,
        reviewed_by: str,
    ) -> bool:
        """更新候选任务审核状态"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE eval_task_candidates
                SET status = ?, reviewed_by = ?, reviewed_at = ?
                WHERE candidate_id = ?
                """,
                (status.value, reviewed_by, now, candidate_id),
            )
            await db.commit()
            return cursor.rowcount > 0
