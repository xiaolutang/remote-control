"""
反馈存储服务

反馈提交和查询均通过 log-service Issues API。
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, status

from app.infra.http_client import get_shared_http_client

logger = logging.getLogger(__name__)

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


async def create_feedback(
    user_id: str,
    session_id: str,
    category: str,
    description: str,
    platform: Optional[str] = None,
    app_version: Optional[str] = None,
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
    """
    _validate_description(description)

    log_service_url = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")

    # 获取关联日志（best-effort）
    related_logs_text = ""
    try:
        log_response = await _call_log_service(
            "get",
            f"{log_service_url}/api/logs",
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
        "request_id": session_id,
        "component": f"feedback:{category}",
        "environment": environment,
    }

    response = await _call_log_service(
        "post",
        f"{log_service_url}/api/issues",
        json=issue_payload,
    )
    response.raise_for_status()

    issue = response.json()
    issue_id = str(issue.get("id", ""))
    created_at = issue.get("created_at", datetime.now(timezone.utc).isoformat())

    logger.info(
        "Feedback created via log-service: issue_id=%s user_id=%s category=%s",
        issue_id, user_id, category,
    )

    return {
        "feedback_id": issue_id,
        "created_at": created_at,
    }


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
    log_service_url = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")

    try:
        response = await _call_log_service(
            "get", f"{log_service_url}/api/issues/{feedback_id}",
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
