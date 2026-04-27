"""
F098: Agent 执行结果回写端点测试。

测试覆盖：
1. 成功回写（含别名持久化）
2. 失败回写（不更新别名）
3. 幂等保护（同一 session 不重复处理）
4. 会话不存在 / 权限校验
5. 别名保存异常不影响回写
6. 数据库层 CRUD 操作
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.infra.auth import generate_token
from app.services.agent_session_manager import (
    AgentSession,
    AgentSessionManager,
    AgentSessionState,
    get_agent_session_manager,
)
from app.services.terminal_agent import AgentResult, CommandSequenceStep


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_SESSION = {
    "session_id": "test-session-report",
    "user_id": "user-report-test",
    "owner": "user-report-test",
}

SAMPLE_USER_ID = "user-report-test"
SAMPLE_DEVICE_ID = "device-001"
SAMPLE_SESSION_ID = "agent-sess-001"


@pytest.fixture(autouse=True)
def _reset_global_manager():
    """每个测试前后重置全局 AgentSessionManager 单例。"""
    import app.services.agent_session_manager as _mod
    _mod._manager = None
    yield
    _mod._manager = None


@pytest.fixture
def client():
    """创建 TestClient。"""
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效 JWT token 的 Authorization headers。"""
    token = generate_token("test-session-report", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def manager():
    """获取 AgentSessionManager 实例。"""
    return get_agent_session_manager()


def _auth_patches():
    """Mock auth 链路：get_token_version + get_session。"""
    return [
        patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
        patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
    ]


def _make_completed_session(
    session_id: str = SAMPLE_SESSION_ID,
    user_id: str = SAMPLE_USER_ID,
    device_id: str = SAMPLE_DEVICE_ID,
    aliases: dict | None = None,
) -> AgentSession:
    """构造一个已完成（COMPLETED）状态的 AgentSession。"""
    now = datetime.now(timezone.utc)
    _aliases = aliases if aliases is not None else {"project-a": "/Users/test/project-a"}
    session = AgentSession(
        id=session_id,
        intent="进入项目",
        device_id=device_id,
        user_id=user_id,
        state=AgentSessionState.COMPLETED,
        created_at=now,
        last_active_at=now,
        result=AgentResult(
            summary="已进入项目A",
            steps=[
                CommandSequenceStep(
                    id="s1",
                    label="进入目录",
                    command="cd ~/project-a",
                ),
            ],
            provider="agent",
            source="recommended",
            need_confirm=False,
            aliases=_aliases,
        ),
    )
    return session


# ---------------------------------------------------------------------------
# API 端点测试
# ---------------------------------------------------------------------------

class TestReportAgentExecution:
    """report_agent_execution 端点测试。"""

    def test_success_report_with_aliases(self, client, auth_headers, manager):
        """成功回写：记录保存 + 别名持久化。"""
        session = _make_completed_session()
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            with patch("app.api.runtime_api.save_agent_execution_report", new_callable=AsyncMock) as mock_save, \
                 patch("app.api.runtime_api.get_agent_execution_report", new_callable=AsyncMock, return_value=None), \
                 patch("app.api.runtime_api._get_alias_store") as mock_alias_store_fn:
                mock_save.return_value = True
                mock_store = AsyncMock()
                mock_alias_store_fn.return_value = mock_store

                response = client.post(
                    f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/{SAMPLE_SESSION_ID}/report",
                    headers=auth_headers,
                    json={
                        "success": True,
                        "executed_command": "cd ~/project-a && claude",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"
                assert data["session_id"] == SAMPLE_SESSION_ID
                assert data["idempotent"] is False

                mock_save.assert_called_once()
                call_kwargs = mock_save.call_args
                assert call_kwargs.kwargs["success"] is True
                assert call_kwargs.kwargs["aliases"] == {"project-a": "/Users/test/project-a"}
                mock_store.save_batch.assert_called_once_with(
                    SAMPLE_USER_ID,
                    SAMPLE_DEVICE_ID,
                    {"project-a": "/Users/test/project-a"},
                )
        finally:
            for m in auth_mocks:
                m.stop()

    def test_failure_report_no_alias_update(self, client, auth_headers, manager):
        """失败回写：记录保存但不更新别名。"""
        session = _make_completed_session()
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            with patch("app.api.runtime_api.save_agent_execution_report", new_callable=AsyncMock) as mock_save, \
                 patch("app.api.runtime_api.get_agent_execution_report", new_callable=AsyncMock, return_value=None), \
                 patch("app.api.runtime_api._get_alias_store") as mock_alias_store_fn:
                mock_save.return_value = True
                mock_store = AsyncMock()
                mock_alias_store_fn.return_value = mock_store

                response = client.post(
                    f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/{SAMPLE_SESSION_ID}/report",
                    headers=auth_headers,
                    json={
                        "success": False,
                        "executed_command": "cd ~/project-b",
                        "failure_step": "step-2",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"

                # 失败时不应调用别名保存
                mock_store.save_batch.assert_not_called()
                # 但仍然保存了 report 记录
                mock_save.assert_called_once()
        finally:
            for m in auth_mocks:
                m.stop()

    def test_idempotent_report(self, client, auth_headers, manager):
        """幂等保护：同一 session_id 不重复处理。"""
        session = _make_completed_session()
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            with patch("app.api.runtime_api.get_agent_execution_report", new_callable=AsyncMock) as mock_get:
                # 模拟已有 report 记录
                mock_get.return_value = {"session_id": SAMPLE_SESSION_ID, "success": 1}

                with patch("app.api.runtime_api.save_agent_execution_report") as mock_save:
                    response = client.post(
                        f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/{SAMPLE_SESSION_ID}/report",
                        headers=auth_headers,
                        json={"success": True},
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["idempotent"] is True
                    # 不应再保存
                    mock_save.assert_not_called()
        finally:
            for m in auth_mocks:
                m.stop()

    def test_session_not_found(self, client, auth_headers, manager):
        """会话不存在返回 404。"""
        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            response = client.post(
                f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/nonexistent-session/report",
                headers=auth_headers,
                json={"success": True},
            )

            assert response.status_code == 404
        finally:
            for m in auth_mocks:
                m.stop()

    def test_device_id_mismatch(self, client, auth_headers, manager):
        """设备 ID 不匹配返回 400。"""
        session = _make_completed_session()
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            response = client.post(
                f"/api/runtime/devices/wrong-device/assistant/agent/{SAMPLE_SESSION_ID}/report",
                headers=auth_headers,
                json={"success": True},
            )

            assert response.status_code == 400
        finally:
            for m in auth_mocks:
                m.stop()

    def test_alias_save_failure_does_not_block_report(self, client, auth_headers, manager):
        """别名保存异常不影响回写。"""
        session = _make_completed_session()
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            with patch("app.api.runtime_api.save_agent_execution_report", new_callable=AsyncMock) as mock_save, \
                 patch("app.api.runtime_api.get_agent_execution_report", new_callable=AsyncMock, return_value=None), \
                 patch("app.api.runtime_api._get_alias_store") as mock_alias_store_fn:
                mock_save.return_value = True
                mock_store = AsyncMock()
                mock_store.save_batch.side_effect = RuntimeError("DB error")
                mock_alias_store_fn.return_value = mock_store

                response = client.post(
                    f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/{SAMPLE_SESSION_ID}/report",
                    headers=auth_headers,
                    json={"success": True, "executed_command": "cd ~/project-a"},
                )

                # 即使别名保存失败，回写本身应成功
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
        finally:
            for m in auth_mocks:
                m.stop()

    def test_success_report_no_aliases(self, client, auth_headers, manager):
        """成功回写但 result 没有 aliases，不触发别名保存。"""
        session = _make_completed_session(aliases={})
        manager._sessions[session.id] = session

        auth_mocks = _auth_patches()
        for m in auth_mocks:
            m.start()

        try:
            with patch("app.api.runtime_api.save_agent_execution_report", new_callable=AsyncMock) as mock_save, \
                 patch("app.api.runtime_api.get_agent_execution_report", new_callable=AsyncMock, return_value=None), \
                 patch("app.api.runtime_api._get_alias_store") as mock_alias_store_fn:
                mock_save.return_value = True
                mock_store = AsyncMock()
                mock_alias_store_fn.return_value = mock_store

                response = client.post(
                    f"/api/runtime/devices/{SAMPLE_DEVICE_ID}/assistant/agent/{SAMPLE_SESSION_ID}/report",
                    headers=auth_headers,
                    json={"success": True},
                )

                assert response.status_code == 200
                # 没有 aliases，不应调用 save_batch
                mock_store.save_batch.assert_not_called()
        finally:
            for m in auth_mocks:
                m.stop()


# ---------------------------------------------------------------------------
# 数据库层测试
# ---------------------------------------------------------------------------

class TestDatabaseAgentExecutionReport:
    """数据库层 agent_execution_reports 操作测试。"""

    @pytest.fixture
    def db(self, tmp_path):
        """创建临时数据库。"""
        from app.store.database import Database
        import asyncio
        database = Database(str(tmp_path / "test.db"))
        asyncio.get_event_loop().run_until_complete(database.init_db())
        return database

    @pytest.mark.asyncio
    async def test_save_and_get_report(self, db):
        """保存并读取 report。"""
        inserted = await db.save_agent_execution_report(
            session_id="sess-1",
            user_id="user-1",
            device_id="dev-1",
            success=True,
            executed_command="cd ~/project",
            aliases={"proj": "/path/to/proj"},
        )
        assert inserted is True

        report = await db.get_agent_execution_report("sess-1")
        assert report is not None
        assert report["session_id"] == "sess-1"
        assert report["success"] == 1
        assert report["executed_command"] == "cd ~/project"
        assert json.loads(report["aliases_json"]) == {"proj": "/path/to/proj"}

    @pytest.mark.asyncio
    async def test_idempotent_save(self, db):
        """幂等保存：第二次保存返回 False。"""
        inserted1 = await db.save_agent_execution_report(
            session_id="sess-2",
            user_id="user-1",
            device_id="dev-1",
            success=True,
        )
        assert inserted1 is True

        inserted2 = await db.save_agent_execution_report(
            session_id="sess-2",
            user_id="user-1",
            device_id="dev-1",
            success=True,
        )
        assert inserted2 is False

    @pytest.mark.asyncio
    async def test_get_nonexistent_report(self, db):
        """查询不存在的 report 返回 None。"""
        report = await db.get_agent_execution_report("nonexistent")
        assert report is None

    @pytest.mark.asyncio
    async def test_failure_report_stored(self, db):
        """失败报告也能正确存储。"""
        inserted = await db.save_agent_execution_report(
            session_id="sess-fail",
            user_id="user-1",
            device_id="dev-1",
            success=False,
            executed_command="cd ~/bad-project",
            failure_step="step-2",
        )
        assert inserted is True

        report = await db.get_agent_execution_report("sess-fail")
        assert report is not None
        assert report["success"] == 0
        assert report["failure_step"] == "step-2"
        assert report["executed_command"] == "cd ~/bad-project"
