"""
反馈存储服务

反馈提交和查询均通过 log-service Issues API。
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.infra.http_client import get_shared_http_client
from app.services.agent_session_manager import generate_terminal_session_id

logger = logging.getLogger(__name__)

# log-service 基地址（模块级常量，避免每处重复读取环境变量）
_LOG_SERVICE_URL = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")

# description 最大长度
MAX_DESCRIPTION_LENGTH = 10000

# category → severity 映射
SEVERITY_MAP = {
    "connection": "high",
    "terminal": "medium",
    "crash": "critical",
    "suggestion": "low",
    "other": "low",
}


def _validate_description(description: str) -> str:
    """验证描述内容"""
    if not description or not description.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="描述不能为空",
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"描述过长，最大 {MAX_DESCRIPTION_LENGTH} 字符",
        )
    return description


async def _verify_terminal_ownership(user_id: str, terminal_id: str) -> str:
    """验证 terminal_id 归属于当前用户，返回派生的 session_id。

    遍历用户的所有 device session，查找包含该 terminal_id 的 session。
    如果未找到，抛出 403 错误。

    Returns:
        从 terminal_id 派生的 session_id（使用 generate_terminal_session_id）。
    """
    from app.store.session import list_sessions_for_user

    sessions = await list_sessions_for_user(user_id)
    for session in sessions:
        terminals = session.get("terminals", [])
        if any(t.get("terminal_id") == terminal_id for t in terminals):
            return generate_terminal_session_id(terminal_id)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="terminal_id 不属于当前用户",
    )


async def _call_log_service(method: str, url: str, **kwargs):
    """执行 log-service HTTP 请求并统一处理 httpx 异常。

    Returns response on success. Raises HTTPException on transport errors.
    """
    try:
        client = get_shared_http_client()
        response = await getattr(client, method)(url, **kwargs)
        return response
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="反馈服务不可用",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="反馈服务超时",
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="反馈服务错误",
            )
        raise


async def _fetch_feedback_issues(
    user_id: str, max_pages: int = 3, page_size: int = 50,
) -> list[dict]:
    """查询 log-service 中该用户的所有 feedback issues（分页遍历）。

    逐页获取直到取完或达到 max_pages 上限（默认最多 150 条）。
    Best-effort: 查询失败返回已获取的部分。
    """
    all_issues: list[dict] = []
    try:
        for page in range(1, max_pages + 1):
            response = await _call_log_service(
                "get",
                f"{_LOG_SERVICE_URL}/api/issues",
                params={
                    "reporter": user_id,
                    "service_name": "remote-control",
                    "page": page,
                    "page_size": page_size,
                },
            )
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", []) if isinstance(data, dict) else data
            issues = [i for i in issues if isinstance(i, dict)]
            all_issues.extend(issues)
            if len(issues) < page_size:
                break
        return all_issues
    except Exception as e:
        logger.warning("Feedback issues 查询失败（best-effort）: user_id=%s error=%s", user_id, e)
        return all_issues


async def _find_existing_feedback(
    user_id: str, result_event_id: str, feedback_type: Optional[str],
) -> Optional[dict]:
    """查询 log-service 是否已有相同 reporter + result_event_id（+ feedback_type）的反馈。

    使用 GET /api/issues?reporter={user_id} 查询，再在本地匹配 result_event_id。
    找到时返回 issue dict，否则返回 None。
    """
    issues = await _fetch_feedback_issues(user_id)
    for issue in issues:
        if issue.get("result_event_id") != result_event_id:
            continue
        if feedback_type and issue.get("feedback_type") != feedback_type:
            continue
        return issue
    return None


async def batch_query_feedback_status(
    user_id: str,
    event_ids: list[str],
) -> dict[str, str]:
    """批量查询多个 event_id 的 feedback status。

    Args:
        user_id: 用户 ID
        event_ids: 需要查询的 event_id 列表

    Returns:
        {event_id: feedback_type} 映射，未找到的不包含在结果中。

    Best-effort: 查询失败返回空 dict。
    """
    if not event_ids:
        return {}
    issues = await _fetch_feedback_issues(user_id)
    result: dict[str, str] = {}
    event_id_set = set(event_ids)
    for issue in issues:
        rid = issue.get("result_event_id", "")
        ftype = issue.get("feedback_type", "")
        if rid and rid in event_id_set and ftype:
            # 同一个 event_id 可能有多次 feedback，取最新的（后面的覆盖前面的）
            result[rid] = ftype
    return result


async def create_feedback(
    user_id: str,
    session_id: str,
    category: str,
    description: str,
    platform: Optional[str] = None,
    app_version: Optional[str] = None,
    terminal_id: Optional[str] = None,
    result_event_id: Optional[str] = None,
    feedback_type: Optional[str] = None,
) -> dict:
    """
    创建反馈 —— 调用 log-service POST /api/issues 持久化。

    映射：
    - category → severity（SEVERITY_MAP）
    - category 存入 component 字段（'feedback:{category}'）
    - user_id → reporter
    - session_id → request_id
    - platform + app_version → environment
    - description + related_logs → description

    B052 新增:
    - terminal_id → environment 中追加
    - result_event_id → 透传到 log-service
    - feedback_type → 透传到 log-service
    - 创建后异步调用 analyze_feedback()

    R051 幂等性:
    - 有 result_event_id 时，先查询是否已有相同 reporter + result_event_id + feedback_type 的 issue
    - 找到则直接返回已有记录，不创建新的
    - 无 result_event_id 的 error_report 不去重（每次提交独立记录）
    """
    _validate_description(description)

    # B052 + R051: 并发执行 terminal 归属校验和幂等去重
    verified_session_id = session_id
    ownership_task = asyncio.create_task(
        _verify_terminal_ownership(user_id, terminal_id),
    ) if terminal_id else None
    dedup_task = asyncio.create_task(
        _find_existing_feedback(user_id, result_event_id, feedback_type),
    ) if result_event_id else None

    # 等待归属校验
    if ownership_task is not None:
        try:
            verified_session_id = await ownership_task
        except Exception:
            # 归属校验失败 → 取消 dedup task
            if dedup_task and not dedup_task.done():
                dedup_task.cancel()
            raise

    # 等待去重检查
    if dedup_task is not None:
        existing = await dedup_task
        if existing is not None:
            logger.info(
                "Feedback dedup hit: existing_issue_id=%s user_id=%s result_event_id=%s",
                existing.get("id"), user_id, result_event_id,
            )
            return {
                "feedback_id": str(existing.get("id", "")),
                "created_at": existing.get("created_at", datetime.now(timezone.utc).isoformat()),
            }

    # 获取关联日志（best-effort）
    related_logs_text = ""
    try:
        log_response = await _call_log_service(
            "get",
            f"{_LOG_SERVICE_URL}/api/logs",
            params={
                "uid": user_id,
                "service_name": "remote-control",
                "component": "client",
                "page_size": 50,
            },
        )
        log_response.raise_for_status()
        log_data = log_response.json()
        logs = log_data.get("logs", [])
        session_logs = [
            l for l in logs
            if l.get("extra", {}).get("session_id") == session_id
        ]
        if session_logs:
            lines = [
                f"[{l.get('level', 'info').upper()}] {l.get('message', '')}"
                for l in session_logs[:20]
            ]
            related_logs_text = "\n\n--- Related Logs ---\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("获取关联日志失败（best-effort）: user_id=%s error=%s", user_id, e)

    # 构建 environment 字段
    environment = ""
    if platform or app_version:
        parts = [p for p in [platform, app_version] if p]
        environment = " / ".join(parts)

    # 调用 log-service POST /api/issues
    issue_payload = {
        "service_name": "remote-control",
        "title": f"[feedback] {category}: {description[:100]}",
        "description": description + related_logs_text,
        "severity": SEVERITY_MAP.get(category, "low"),
        "reporter": user_id,
        "request_id": verified_session_id,
        "component": f"feedback:{category}",
        "environment": environment,
    }
    # B052: 透传新字段
    if terminal_id:
        issue_payload["terminal_id"] = terminal_id
    if result_event_id:
        issue_payload["result_event_id"] = result_event_id
    if feedback_type:
        issue_payload["feedback_type"] = feedback_type

    response = await _call_log_service(
        "post",
        f"{_LOG_SERVICE_URL}/api/issues",
        json=issue_payload,
    )
    response.raise_for_status()

    issue = response.json()
    issue_id = str(issue.get("id", ""))
    created_at = issue.get("created_at", datetime.now(timezone.utc).isoformat())

    logger.info(
        "Feedback created via log-service: issue_id=%s user_id=%s category=%s terminal_id=%s",
        issue_id, user_id, category, terminal_id,
    )

    # B052: 异步触发 analyze_feedback（best-effort，不阻塞响应）
    try:
        from evals.feedback_loop import analyze_feedback
        from evals.db import EvalDatabase

        eval_db_path = os.environ.get("EVAL_DB_PATH", "/data/evals.db")
        eval_db = EvalDatabase(eval_db_path)

        # 不 await —— 分析失败不影响反馈提交
        asyncio.ensure_future(_run_analyze_feedback(
            eval_db, issue_id, category, description,
        ))
    except Exception as e:
        logger.info("analyze_feedback 触发跳过: %s", e)

    return {
        "feedback_id": issue_id,
        "created_at": created_at,
    }


async def _run_analyze_feedback(
    eval_db, feedback_id: str, category: str, description: str,
) -> None:
    """包装 analyze_feedback 调用，捕获所有异常。"""
    try:
        await eval_db.init_db()
        from evals.feedback_loop import analyze_feedback
        candidate_id = await analyze_feedback(
            eval_db,
            feedback_id=feedback_id,
            category=category,
            description=description,
        )
        if candidate_id:
            logger.info("Feedback→Candidate: feedback_id=%s candidate_id=%s", feedback_id, candidate_id)
    except Exception as e:
        logger.warning("analyze_feedback 执行失败（best-effort）: feedback_id=%s error=%s", feedback_id, e)


async def get_feedback(feedback_id: str, user_id: str) -> Optional[dict]:
    """
    获取反馈详情 —— 调用 log-service GET /api/issues/{id}。

    反向映射：
    - issue.component（'feedback:connection'）→ category（'connection'）
    - issue.reporter → user_id
    - issue.environment → platform + app_version
    - issue.request_id → session_id

    归属校验：reporter ≠ 当前 user_id → 返回 None（404）。
    """
    try:
        response = await _call_log_service(
            "get", f"{_LOG_SERVICE_URL}/api/issues/{feedback_id}",
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise

    issue = response.json()

    # 归属校验
    reporter = issue.get("reporter", "")
    if reporter != user_id:
        return None

    # 从 component 提取 category（'feedback:connection' → 'connection'）
    component = issue.get("component", "")
    if component.startswith("feedback:"):
        category = component[len("feedback:"):]
    else:
        category = component

    # 从 environment 解析 platform + app_version
    environment = issue.get("environment", "")
    platform = ""
    app_version = ""
    if " / " in environment:
        parts = environment.split(" / ", 1)
        platform = parts[0]
        app_version = parts[1]
    elif environment:
        platform = environment

    return {
        "feedback_id": str(issue.get("id", "")),
        "user_id": reporter,
        "session_id": issue.get("request_id", ""),
        "category": category,
        "description": issue.get("description", ""),
        "platform": platform,
        "app_version": app_version,
        "created_at": issue.get("created_at", ""),
        "logs": [],
    }
