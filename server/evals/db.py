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

    优先使用 EVAL_AGENT_*，未设置时 fallback 到 LLM_*。
    Judge 模型默认 gpt-5.4。

    环境变量：
      - EVAL_AGENT_MODEL（fallback LLM_MODEL）
      - EVAL_AGENT_BASE_URL（fallback LLM_BASE_URL）
      - EVAL_AGENT_API_KEY（fallback LLM_API_KEY）
      - EVAL_JUDGE_MODEL（默认 gpt-5.4）
      - EVAL_JUDGE_BASE_URL（fallback EVAL_AGENT_BASE_URL → LLM_BASE_URL）
      - EVAL_JUDGE_API_KEY（fallback EVAL_AGENT_API_KEY → LLM_API_KEY）
    """
    model = (
        os.environ.get("EVAL_AGENT_MODEL")
        or os.environ.get("LLM_MODEL")
        or ""
    )
    base_url = (
        os.environ.get("EVAL_AGENT_BASE_URL")
        or os.environ.get("LLM_BASE_URL")
        or ""
    )
    api_key = (
        os.environ.get("EVAL_AGENT_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or ""
    )

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
            f"请设置 EVAL_AGENT_MODEL / EVAL_AGENT_BASE_URL / EVAL_AGENT_API_KEY "
            f"或 LLM_MODEL / LLM_BASE_URL / LLM_API_KEY 环境变量。"
        )

    config: Dict[str, str] = {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }

    # Judge 配置：默认 gpt-5.4，URL/KEY fallback 到 eval agent 配置
    judge_model = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def init_db(self) -> None:
        """初始化数据库，创建 6 张表（如果不存在）。"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
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
        """保存评估任务定义（upsert，保留已有记录的 created_at）。"""
        data = task_def.to_db_dict()
        async with self._connect() as db:
            # 保留已有记录的 created_at，避免重复 run 覆盖原始时间
            existing = await db.execute(
                "SELECT created_at FROM eval_task_defs WHERE id = ?",
                (data["id"],),
            )
            row = await existing.fetchone()
            if row:
                data["created_at"] = row["created_at"]
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

    async def query_task_trend(self, task_id: str, limit: int = 20) -> List[Dict]:
        """单条 SQL 查询 task 的历史 pass_rate 趋势（避免 N+1）。

        先查询 eval_trials 中 task_id=? 的所有 run_id + agent_result_json，
        然后在 Python 中聚合，不依赖 SQLite 的 json_extract。

        Args:
            task_id: 任务 ID
            limit: 返回记录数量限制

        Returns:
            [{run_id, started_at, pass_rate, total_tasks, passed_tasks}]
        """
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT r.run_id, r.started_at, t.agent_result_json
                FROM eval_runs r
                JOIN eval_trials t ON r.run_id = t.run_id
                WHERE t.task_id = ?
                ORDER BY r.started_at DESC
                """,
                (task_id,),
            )
            rows = await cursor.fetchall()

        # 在 Python 中按 run_id 聚合
        from collections import OrderedDict
        runs: "OrderedDict[str, Dict]" = OrderedDict()
        for r in rows:
            d = dict(r)
            rid = d["run_id"]
            if rid not in runs:
                runs[rid] = {
                    "run_id": rid,
                    "started_at": d["started_at"],
                    "total": 0,
                    "passed": 0,
                }
            runs[rid]["total"] += 1
            arj = d.get("agent_result_json") or "{}"
            if isinstance(arj, str):
                try:
                    arj = json.loads(arj)
                except (json.JSONDecodeError, TypeError):
                    arj = {}
            if isinstance(arj, dict) and arj.get("response_type") != "error":
                runs[rid]["passed"] += 1

        result = []
        for v in list(runs.values())[:limit]:
            total = v["total"]
            passed = v["passed"]
            result.append({
                "run_id": v["run_id"],
                "started_at": v["started_at"],
                "pass_rate": passed / total if total > 0 else 0.0,
                "total_tasks": total,
                "passed_tasks": passed,
            })
        return result

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

    @staticmethod
    def _build_metric_conditions(
        metric_name=None, user_id=None, device_id=None,
        start_time=None, end_time=None,
    ) -> tuple:
        """构建 quality_metrics 查询的共享 WHERE 条件。"""
        conditions: List[str] = []
        params: List[Any] = []
        if metric_name is not None:
            conditions.append("metric_name = ?")
            params.append(metric_name)
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if device_id is not None:
            conditions.append("device_id = ?")
            params.append(device_id)
        if start_time is not None:
            conditions.append("computed_at >= ?")
            params.append(start_time)
        if end_time is not None:
            conditions.append("computed_at <= ?")
            params.append(end_time)
        return conditions, params

    async def query_quality_metrics(
        self,
        *,
        metric_name: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[QualityMetric]:
        """多条件过滤查询质量指标。

        动态构建 WHERE 子句，只添加有值的过滤条件。
        ORDER BY computed_at DESC, LIMIT 防止大查询。
        """
        conditions, params = self._build_metric_conditions(
            metric_name, user_id, device_id, start_time, end_time
        )

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)

        query = "SELECT * FROM quality_metrics"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY computed_at DESC LIMIT ?"
        params.append(limit)

        async with self._connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [QualityMetric.from_db_row(dict(r)) for r in rows]

    async def aggregate_quality_metrics(
        self,
        *,
        metric_name: Optional[str] = None,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        group_by: str = "day",
    ) -> List[Dict]:
        """按时间窗口聚合质量指标。

        group_by: "day" / "week" / "month"
        返回 group_key, metric_name, count, avg_value, min_value, max_value。
        """
        if group_by == "day":
            group_expr = "strftime('%Y-%m-%d', computed_at)"
        elif group_by == "week":
            group_expr = "strftime('%Y-W%W', computed_at)"
        elif group_by == "month":
            group_expr = "strftime('%Y-%m', computed_at)"
        else:
            group_expr = "strftime('%Y-%m-%d', computed_at)"

        conditions, params = self._build_metric_conditions(
            metric_name, user_id, device_id, start_time, end_time
        )

        query = (
            f"SELECT {group_expr} as group_key, metric_name, "
            f"COUNT(*) as count, AVG(value) as avg_value, "
            f"MIN(value) as min_value, MAX(value) as max_value "
            f"FROM quality_metrics"
        )
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY group_key, metric_name"
        query += " ORDER BY group_key DESC, metric_name"

        async with self._connect() as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [
                {k: d[k] for k in ("group_key", "metric_name", "count", "avg_value", "min_value", "max_value")}
                for d in (dict(r) for r in rows)
            ]

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
