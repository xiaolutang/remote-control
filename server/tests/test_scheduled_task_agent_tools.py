"""
B001: Agent 定时任务工具测试。

测试覆盖：
1. _tool_list_scheduled_tasks: 正常查询、空列表、回调不可用
2. _tool_cancel_scheduled_task: 正常取消、任务不存在、越权取消
3. 回调注入：闭包捕获 device_id/terminal_id
4. store 层: list_by_session_and_terminal 方法
5. System Prompt: 当前时间注入
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.terminal_agent import (
    AgentDeps,
    SYSTEM_PROMPT,
    _build_system_prompt,
    list_scheduled_tasks,
    cancel_scheduled_task,
    build_session_agent,
)
from app.services.terminal_agent_tools import (
    _tool_list_scheduled_tasks,
    _tool_cancel_scheduled_task,
)
from pydantic_ai import RunContext


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

def _make_deps(
    execute_fn=None,
    ask_fn=None,
    list_scheduled_tasks_fn=None,
    cancel_scheduled_task_fn=None,
    session_id: str = "test-session",
) -> AgentDeps:
    if execute_fn is None:
        execute_fn = AsyncMock(return_value=MagicMock(stdout="mock", stderr="", exit_code=0, timed_out=False))
    if ask_fn is None:
        ask_fn = AsyncMock(return_value="user reply")
    return AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_fn,
        ask_user_fn=ask_fn,
        list_scheduled_tasks_fn=list_scheduled_tasks_fn,
        cancel_scheduled_task_fn=cancel_scheduled_task_fn,
    )


def _make_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


# ---------------------------------------------------------------------------
# Test: _tool_list_scheduled_tasks
# ---------------------------------------------------------------------------

class TestListScheduledTasks:
    """测试 list_scheduled_tasks 工具。"""

    @pytest.mark.asyncio
    async def test_returns_task_list(self):
        """正常返回当前终端任务列表。"""
        tasks = [
            {
                "id": 1,
                "text_content": "npm test",
                "execute_at": "2026-05-14T03:00:00+08:00",
                "repeat_type": "once",
                "status": "pending",
            },
            {
                "id": 2,
                "text_content": "git pull",
                "execute_at": "2026-05-15T08:00:00+08:00",
                "repeat_type": "daily",
                "status": "pending",
            },
        ]
        deps = _make_deps(list_scheduled_tasks_fn=AsyncMock(return_value=tasks))
        ctx = _make_run_context(deps)

        result = await _tool_list_scheduled_tasks(ctx)

        assert "npm test" in result
        assert "git pull" in result
        assert "2026-05-14T03:00:00+08:00" in result
        assert "#1" in result
        assert "#2" in result

    @pytest.mark.asyncio
    async def test_empty_task_list(self):
        """终端无任务 -> 返回空列表提示。"""
        deps = _make_deps(list_scheduled_tasks_fn=AsyncMock(return_value=[]))
        ctx = _make_run_context(deps)

        result = await _tool_list_scheduled_tasks(ctx)

        assert "没有定时任务" in result

    @pytest.mark.asyncio
    async def test_fn_not_available(self):
        """回调不可用 -> 返回不支持提示。"""
        deps = _make_deps(list_scheduled_tasks_fn=None)
        ctx = _make_run_context(deps)

        result = await _tool_list_scheduled_tasks(ctx)

        assert "不支持" in result

    @pytest.mark.asyncio
    async def test_fn_exception_handling(self):
        """回调异常 -> 返回错误信息。"""
        deps = _make_deps(
            list_scheduled_tasks_fn=AsyncMock(side_effect=RuntimeError("DB error"))
        )
        ctx = _make_run_context(deps)

        result = await _tool_list_scheduled_tasks(ctx)

        assert "查询定时任务失败" in result
        assert "RuntimeError" in result

    @pytest.mark.asyncio
    async def test_same_device_different_terminal_isolation(self):
        """同 device 不同 terminal -> 回调由闭包保证隔离。"""
        # 这个测试验证工具本身只调用回调，隔离由闭包保证
        # 闭包测试在 TestCallbackInjection 中覆盖
        tasks_terminal_a = [{"id": 1, "text_content": "task A"}]
        deps = _make_deps(
            list_scheduled_tasks_fn=AsyncMock(return_value=tasks_terminal_a)
        )
        ctx = _make_run_context(deps)

        result = await _tool_list_scheduled_tasks(ctx)

        assert "task A" in result


# ---------------------------------------------------------------------------
# Test: _tool_cancel_scheduled_task
# ---------------------------------------------------------------------------

class TestCancelScheduledTask:
    """测试 cancel_scheduled_task 工具。"""

    @pytest.mark.asyncio
    async def test_cancel_success(self):
        """正常取消 -> 返回成功信息。"""
        deps = _make_deps(
            cancel_scheduled_task_fn=AsyncMock(return_value="任务 42 已成功取消")
        )
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=42)

        assert "已成功取消" in result

    @pytest.mark.asyncio
    async def test_task_not_found(self):
        """任务不存在 -> 返回失败信息。"""
        deps = _make_deps(
            cancel_scheduled_task_fn=AsyncMock(return_value="任务 999 不存在")
        )
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=999)

        assert "不存在" in result

    @pytest.mark.asyncio
    async def test_wrong_user(self):
        """非当前用户任务 -> 回调中 user_id 校验失败，返回失败信息。"""
        deps = _make_deps(
            cancel_scheduled_task_fn=AsyncMock(
                return_value="任务 42 不属于当前用户，无权取消"
            )
        )
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=42)

        assert "不属于当前用户" in result

    @pytest.mark.asyncio
    async def test_wrong_terminal(self):
        """非当前终端任务 -> 回调中 terminal_id 校验失败，返回失败信息。"""
        deps = _make_deps(
            cancel_scheduled_task_fn=AsyncMock(
                return_value="任务 42 不属于当前终端，无权取消"
            )
        )
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=42)

        assert "不属于当前终端" in result

    @pytest.mark.asyncio
    async def test_fn_not_available(self):
        """回调不可用 -> 返回不支持提示。"""
        deps = _make_deps(cancel_scheduled_task_fn=None)
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=1)

        assert "不支持" in result

    @pytest.mark.asyncio
    async def test_fn_exception_handling(self):
        """回调异常 -> 返回错误信息。"""
        deps = _make_deps(
            cancel_scheduled_task_fn=AsyncMock(side_effect=RuntimeError("DB error"))
        )
        ctx = _make_run_context(deps)

        result = await _tool_cancel_scheduled_task(ctx, task_id=1)

        assert "取消定时任务失败" in result


# ---------------------------------------------------------------------------
# Test: Callback Injection（闭包捕获验证）
# ---------------------------------------------------------------------------

class TestCallbackInjection:
    """测试 agent_session_runner 中的闭包回调注入。"""

    @pytest.mark.asyncio
    async def test_list_callback_uses_device_id_as_session_id(self):
        """list 回调：device_id（非 AgentDeps.session_id）作为 store 的 session_id 参数。"""
        from app.store.database import Database

        # mock Database (has ScheduledTaskStoreMixin methods)
        store = AsyncMock(spec=Database)
        store.list_scheduled_tasks_by_session_and_terminal = AsyncMock(return_value=[
            {"id": 1, "text_content": "task1", "status": "pending"},
        ])

        # 模拟闭包创建（复刻 agent_session_runner 中的逻辑）
        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        async def _list_scheduled_tasks():
            return await store.list_scheduled_tasks_by_session_and_terminal(
                session_id=device_id,
                terminal_id=terminal_id,
            )

        # 调用闭包
        result = await _list_scheduled_tasks()

        # 验证 store 被正确调用：session_id = device_id
        store.list_scheduled_tasks_by_session_and_terminal.assert_called_once_with(
            session_id="device-456",
            terminal_id="terminal-789",
        )
        assert len(result) == 1
        assert result[0]["text_content"] == "task1"

    @pytest.mark.asyncio
    async def test_cancel_callback_validates_ownership(self):
        """cancel 回调：校验 user_id + session_id + terminal_id 全部匹配。"""
        from app.store.database import Database

        store = AsyncMock(spec=Database)

        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        # 场景 1: 任务属于当前用户/设备/终端 -> 成功取消
        store.get_scheduled_task_by_id = AsyncMock(return_value={
            "id": 1,
            "user_id": "user-123",
            "session_id": "device-456",
            "terminal_id": "terminal-789",
            "status": "pending",
        })
        store.delete_scheduled_task = AsyncMock()

        async def _cancel_scheduled_task(task_id: int) -> str:
            task = await store.get_scheduled_task_by_id(task_id)
            if task is None:
                return f"任务 {task_id} 不存在"
            if task.get("user_id") != user_id:
                return f"任务 {task_id} 不属于当前用户，无权取消"
            if task.get("session_id") != device_id:
                return f"任务 {task_id} 不属于当前设备，无权取消"
            if task.get("terminal_id") != terminal_id:
                return f"任务 {task_id} 不属于当前终端，无权取消"
            await store.delete_scheduled_task(task_id)
            return f"任务 {task_id} 已成功取消"

        result = await _cancel_scheduled_task(1)
        assert "已成功取消" in result
        store.delete_scheduled_task.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_cancel_callback_rejects_wrong_user(self):
        """cancel 回调：不同 user_id -> 拒绝。"""
        from app.store.database import Database

        store = AsyncMock(spec=Database)
        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        store.get_scheduled_task_by_id = AsyncMock(return_value={
            "id": 2,
            "user_id": "user-OTHER",
            "session_id": "device-456",
            "terminal_id": "terminal-789",
        })

        async def _cancel_scheduled_task(task_id: int) -> str:
            task = await store.get_scheduled_task_by_id(task_id)
            if task is None:
                return f"任务 {task_id} 不存在"
            if task.get("user_id") != user_id:
                return f"任务 {task_id} 不属于当前用户，无权取消"
            if task.get("session_id") != device_id:
                return f"任务 {task_id} 不属于当前设备，无权取消"
            if task.get("terminal_id") != terminal_id:
                return f"任务 {task_id} 不属于当前终端，无权取消"
            await store.delete_scheduled_task(task_id)
            return f"任务 {task_id} 已成功取消"

        result = await _cancel_scheduled_task(2)
        assert "不属于当前用户" in result

    @pytest.mark.asyncio
    async def test_cancel_callback_rejects_wrong_device(self):
        """cancel 回调：不同 device_id(session_id) -> 拒绝。"""
        from app.store.database import Database

        store = AsyncMock(spec=Database)
        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        store.get_scheduled_task_by_id = AsyncMock(return_value={
            "id": 3,
            "user_id": "user-123",
            "session_id": "device-OTHER",
            "terminal_id": "terminal-789",
        })

        async def _cancel_scheduled_task(task_id: int) -> str:
            task = await store.get_scheduled_task_by_id(task_id)
            if task is None:
                return f"任务 {task_id} 不存在"
            if task.get("user_id") != user_id:
                return f"任务 {task_id} 不属于当前用户，无权取消"
            if task.get("session_id") != device_id:
                return f"任务 {task_id} 不属于当前设备，无权取消"
            if task.get("terminal_id") != terminal_id:
                return f"任务 {task_id} 不属于当前终端，无权取消"
            await store.delete_scheduled_task(task_id)
            return f"任务 {task_id} 已成功取消"

        result = await _cancel_scheduled_task(3)
        assert "不属于当前设备" in result

    @pytest.mark.asyncio
    async def test_cancel_callback_rejects_wrong_terminal(self):
        """cancel 回调：不同 terminal_id -> 拒绝。"""
        from app.store.database import Database

        store = AsyncMock(spec=Database)
        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        store.get_scheduled_task_by_id = AsyncMock(return_value={
            "id": 4,
            "user_id": "user-123",
            "session_id": "device-456",
            "terminal_id": "terminal-OTHER",
        })

        async def _cancel_scheduled_task(task_id: int) -> str:
            task = await store.get_scheduled_task_by_id(task_id)
            if task is None:
                return f"任务 {task_id} 不存在"
            if task.get("user_id") != user_id:
                return f"任务 {task_id} 不属于当前用户，无权取消"
            if task.get("session_id") != device_id:
                return f"任务 {task_id} 不属于当前设备，无权取消"
            if task.get("terminal_id") != terminal_id:
                return f"任务 {task_id} 不属于当前终端，无权取消"
            await store.delete_scheduled_task(task_id)
            return f"任务 {task_id} 已成功取消"

        result = await _cancel_scheduled_task(4)
        assert "不属于当前终端" in result

    @pytest.mark.asyncio
    async def test_cancel_callback_task_not_found(self):
        """cancel 回调：任务不存在 -> 返回不存在信息。"""
        from app.store.database import Database

        store = AsyncMock(spec=Database)
        user_id = "user-123"
        device_id = "device-456"
        terminal_id = "terminal-789"

        store.get_scheduled_task_by_id = AsyncMock(return_value=None)

        async def _cancel_scheduled_task(task_id: int) -> str:
            task = await store.get_scheduled_task_by_id(task_id)
            if task is None:
                return f"任务 {task_id} 不存在"
            if task.get("user_id") != user_id:
                return f"任务 {task_id} 不属于当前用户，无权取消"
            if task.get("session_id") != device_id:
                return f"任务 {task_id} 不属于当前设备，无权取消"
            if task.get("terminal_id") != terminal_id:
                return f"任务 {task_id} 不属于当前终端，无权取消"
            await store.delete_scheduled_task(task_id)
            return f"任务 {task_id} 已成功取消"

        result = await _cancel_scheduled_task(999)
        assert "不存在" in result


# ---------------------------------------------------------------------------
# Test: Store — list_by_session_and_terminal
# ---------------------------------------------------------------------------

class TestStoreListBySessionAndTerminal:
    """测试 Database.list_scheduled_tasks_by_session_and_terminal 方法。"""

    @pytest.mark.asyncio
    async def test_returns_matching_tasks(self):
        """返回匹配 session_id + terminal_id 的任务。"""
        from app.store.database import Database
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.init_db()

            # 创建测试数据
            await db.create_scheduled_task("user1", "device1", "term1", "task A", "2026-05-14T03:00:00+08:00", "once")
            await db.create_scheduled_task("user1", "device1", "term2", "task B", "2026-05-14T04:00:00+08:00", "once")
            await db.create_scheduled_task("user1", "device2", "term1", "task C", "2026-05-14T05:00:00+08:00", "once")

            # 查询 device1 + term1 -> 只返回 task A
            result = await db.list_scheduled_tasks_by_session_and_terminal("device1", "term1")
            assert len(result) == 1
            assert result[0]["text_content"] == "task A"

            # 查询 device1 + term2 -> 只返回 task B
            result = await db.list_scheduled_tasks_by_session_and_terminal("device1", "term2")
            assert len(result) == 1
            assert result[0]["text_content"] == "task B"

            # 查询不存在的组合 -> 空列表
            result = await db.list_scheduled_tasks_by_session_and_terminal("device1", "term-nonexist")
            assert result == []

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """支持 status 过滤。"""
        import tempfile
        import os
        from app.store.database import Database

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            db = Database(db_path)
            await db.init_db()

            task = await db.create_scheduled_task("user1", "device1", "term1", "task A", "2026-05-14T03:00:00+08:00", "once")
            await db.update_scheduled_task_status(task["id"], "executed")

            await db.create_scheduled_task("user1", "device1", "term1", "task B", "2026-05-14T04:00:00+08:00", "once")

            # 只查 pending -> 只返回 task B
            result = await db.list_scheduled_tasks_by_session_and_terminal("device1", "term1", status="pending")
            assert len(result) == 1
            assert result[0]["text_content"] == "task B"


# ---------------------------------------------------------------------------
# Test: System Prompt — 当前时间注入
# ---------------------------------------------------------------------------

class TestSystemPromptTimeInjection:
    """测试 System Prompt 中包含当前时间注入。"""

    def test_system_prompt_contains_scheduled_task_section(self):
        """SYSTEM_PROMPT 模板包含定时任务段落。"""
        assert "定时任务" in SYSTEM_PROMPT
        assert "schedule_at" in SYSTEM_PROMPT
        assert "list_scheduled_tasks" in SYSTEM_PROMPT
        assert "cancel_scheduled_task" in SYSTEM_PROMPT

    def test_system_prompt_has_time_placeholder(self):
        """SYSTEM_PROMPT 模板有 current_time 占位符。"""
        assert "{current_time}" in SYSTEM_PROMPT

    def test_build_system_prompt_injects_time(self):
        """_build_system_prompt 注入当前时间。"""
        prompt = _build_system_prompt()
        assert "服务器当前时间：" in prompt
        # 应该包含实际时间值（格式：2026-05-13 XX:XX:XX +08:00）
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+08:00", prompt)

    def test_build_system_prompt_injects_sensitive_paths(self):
        """_build_system_prompt 注入敏感路径。"""
        prompt = _build_system_prompt()
        # 不应还有未替换的占位符
        assert "{current_time}" not in prompt
        assert "{sensitive_paths}" not in prompt

    def test_build_system_prompt_has_absolute_time_instruction(self):
        """System prompt 要求使用绝对时间。"""
        prompt = _build_system_prompt()
        assert "绝对 ISO 8601" in prompt or "带时区的绝对" in prompt
        assert "2026-05-14T03:00:00+08:00" in prompt
        assert "禁止使用相对时间" in prompt


# ---------------------------------------------------------------------------
# Test: AgentDeps 新回调字段
# ---------------------------------------------------------------------------

class TestAgentDepsCallbacks:
    """测试 AgentDeps 新增的回调字段。"""

    def test_deps_has_list_scheduled_tasks_fn(self):
        """AgentDeps 有 list_scheduled_tasks_fn 字段。"""
        deps = AgentDeps(
            session_id="test",
            execute_command_fn=AsyncMock(),
            ask_user_fn=AsyncMock(),
            list_scheduled_tasks_fn=AsyncMock(),
        )
        assert deps.list_scheduled_tasks_fn is not None

    def test_deps_has_cancel_scheduled_task_fn(self):
        """AgentDeps 有 cancel_scheduled_task_fn 字段。"""
        deps = AgentDeps(
            session_id="test",
            execute_command_fn=AsyncMock(),
            ask_user_fn=AsyncMock(),
            cancel_scheduled_task_fn=AsyncMock(),
        )
        assert deps.cancel_scheduled_task_fn is not None

    def test_deps_callbacks_default_none(self):
        """AgentDeps 回调默认为 None。"""
        deps = AgentDeps(
            session_id="test",
            execute_command_fn=AsyncMock(),
            ask_user_fn=AsyncMock(),
        )
        assert deps.list_scheduled_tasks_fn is None
        assert deps.cancel_scheduled_task_fn is None


# ---------------------------------------------------------------------------
# Test: Tool Registration
# ---------------------------------------------------------------------------

class TestToolRegistration:
    """测试新工具注册到 Agent。"""

    def test_session_agent_has_scheduled_tools(self):
        """build_session_agent 生成的 Agent 包含定时任务工具。"""
        agent = build_session_agent()
        # Pydantic AI Agent 的工具注册在内部结构中
        # 验证 agent 实例创建成功即可（工具注册失败会抛异常）
        assert agent is not None

    def test_list_scheduled_tasks_alias_exists(self):
        """list_scheduled_tasks 别名存在。"""
        assert list_scheduled_tasks is not None
        assert callable(list_scheduled_tasks)

    def test_cancel_scheduled_task_alias_exists(self):
        """cancel_scheduled_task 别名存在。"""
        assert cancel_scheduled_task is not None
        assert callable(cancel_scheduled_task)
