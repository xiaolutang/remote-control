"""项目/设备/终端实体域 Store Mixin。

提供固定项目、扫描根目录、Planner 配置等数据库操作。
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class ProjectStoreMixin:
    """项目/设备相关数据库操作 Mixin。"""

    async def get_pinned_projects(self, username: str, device_id: str) -> List[Dict[str, Any]]:
        """获取指定用户设备的固定项目列表。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, label, cwd, created_at, updated_at
                FROM project_source_pinned_projects
                WHERE username = ? AND device_id = ?
                ORDER BY updated_at DESC, label ASC
                """,
                (username, device_id),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def replace_pinned_projects(
        self,
        username: str,
        device_id: str,
        projects: List[Dict[str, Any]],
    ) -> None:
        """覆盖指定用户设备的固定项目列表。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM project_source_pinned_projects
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            for project in projects:
                await db.execute(
                    """
                    INSERT INTO project_source_pinned_projects (
                        username, device_id, label, cwd, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        device_id,
                        project["label"],
                        project["cwd"],
                        now,
                        now,
                    ),
                )
            await db.commit()

    async def get_approved_scan_roots(self, username: str, device_id: str) -> List[Dict[str, Any]]:
        """获取指定用户设备的扫描根目录配置。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, root_path, scan_depth, enabled, created_at, updated_at
                FROM project_source_scan_roots
                WHERE username = ? AND device_id = ?
                ORDER BY updated_at DESC, root_path ASC
                """,
                (username, device_id),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def replace_approved_scan_roots(
        self,
        username: str,
        device_id: str,
        roots: List[Dict[str, Any]],
    ) -> None:
        """覆盖指定用户设备的扫描根目录配置。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM project_source_scan_roots
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            for root in roots:
                await db.execute(
                    """
                    INSERT INTO project_source_scan_roots (
                        username, device_id, root_path, scan_depth, enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        device_id,
                        root["root_path"],
                        int(root.get("scan_depth", 2)),
                        1 if root.get("enabled", True) else 0,
                        now,
                        now,
                    ),
                )
            await db.commit()

    async def get_planner_config(self, username: str, device_id: str) -> Optional[Dict[str, Any]]:
        """获取指定用户设备的 planner 配置。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, provider, llm_enabled, endpoint_profile,
                       credentials_mode, requires_explicit_opt_in, created_at, updated_at
                FROM project_source_planner_configs
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_planner_config(
        self,
        username: str,
        device_id: str,
        config: Dict[str, Any],
    ) -> None:
        """保存指定用户设备的 planner 配置。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO project_source_planner_configs (
                    username, device_id, provider, llm_enabled, endpoint_profile,
                    credentials_mode, requires_explicit_opt_in, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username, device_id) DO UPDATE SET
                    provider = excluded.provider,
                    llm_enabled = excluded.llm_enabled,
                    endpoint_profile = excluded.endpoint_profile,
                    credentials_mode = excluded.credentials_mode,
                    requires_explicit_opt_in = excluded.requires_explicit_opt_in,
                    updated_at = excluded.updated_at
                """,
                (
                    username,
                    device_id,
                    config.get("provider", "local_rules"),
                    1 if config.get("llm_enabled", False) else 0,
                    config.get("endpoint_profile", "openai_compatible"),
                    config.get("credentials_mode", "client_secure_storage"),
                    1 if config.get("requires_explicit_opt_in", True) else 0,
                    now,
                    now,
                ),
            )
            await db.commit()
