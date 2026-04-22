"""
集成测试 - 验证双端共控核心功能

测试场景：
1. Agent 连接和状态更新
2. Client 连接和状态同步
3. 多视图 presence 同步
4. 消息双向转发
5. 契约消息格式验证
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app import app
from app.auth import generate_token, get_current_user_id


async def _mock_user_id():
    """测试用 mock：直接返回 user1"""
    return "user1"


async def _cancelled_iter_text():
    if False:
        yield ""
    raise asyncio.CancelledError


def _build_mock_websocket(auth_message: dict) -> AsyncMock:
    """构造默认走安全传输分支的 WebSocket mock。"""
    mock_ws = AsyncMock()
    mock_ws.receive_text = AsyncMock(return_value=json.dumps(auth_message))
    mock_ws.iter_text = MagicMock(return_value=_cancelled_iter_text())
    mock_ws.accept = AsyncMock()
    mock_ws.scope = {"scheme": "wss"}
    mock_ws.headers = {}
    return mock_ws


class TestIntegrationAgentConnection:
    """Agent 连接集成测试"""

    @pytest.mark.asyncio
    async def test_agent_connect_with_valid_token(self):
        """Agent 使用有效 token 连接"""
        from app.ws_agent import active_agents, AgentConnection
        from app.auth import generate_token

        # 清理
        active_agents.clear()

        # 创建测试 token（含 token_version + view_type，符合 B062 校验）
        test_token = generate_token(session_id="test-session-1", token_version=1, view_type="mobile")

        mock_ws = _build_mock_websocket({"type": "auth", "token": test_token})

        with patch('app.ws_agent.get_session', return_value={"session_id": "test-session-1", "owner": "test-user"}):
            with patch('app.ws_agent.set_session_online', new_callable=AsyncMock):
                with patch('app.ws_client.get_view_counts', return_value={"mobile": 0, "desktop": 0}):
                    with patch('app.auth.get_token_version', new_callable=AsyncMock, return_value=1):
                        try:
                            from app.ws_agent import agent_websocket_handler
                            await agent_websocket_handler(mock_ws)
                        except asyncio.CancelledError:
                            pass

        # 验证 connected 消息被发送
        mock_ws.send_json.assert_called()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "connected"
        assert call_args["session_id"] == "test-session-1"
        assert "owner" in call_args
        assert "views" in call_args


class TestIntegrationClientConnection:
    """Client 连接集成测试"""

    @pytest.mark.asyncio
    async def test_client_connect_with_valid_token(self):
        """Client 使用有效 token 连接"""
        from app.ws_client import active_clients
        from app.auth import generate_token

        # 清理
        active_clients.clear()

        # 创建测试 token（含 token_version + view_type，符合 B062 校验）
        test_token = generate_token(session_id="test-session-2", token_version=1, view_type="mobile")

        mock_ws = _build_mock_websocket({"type": "auth", "token": test_token})

        with patch('app.ws_client.get_session', return_value={"session_id": "test-session-2", "owner": "test-user"}):
            with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                    with patch('app.auth.get_token_version', new_callable=AsyncMock, return_value=1):
                        try:
                            from app.ws_client import client_websocket_handler
                            await client_websocket_handler(mock_ws, "test-session-2", view="mobile")
                        except asyncio.CancelledError:
                            pass

        # 验证 connected 消息被发送
        mock_ws.send_json.assert_called()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "connected"
        assert call_args["session_id"] == "test-session-2"
        assert "agent_online" in call_args
        assert "owner" in call_args

    @pytest.mark.asyncio
    async def test_client_connect_desktop_view(self):
        """Client 使用 desktop 视图连接"""
        from app.ws_client import active_clients
        from app.auth import generate_token

        # 清理
        active_clients.clear()

        # 创建测试 token（含 token_version + view_type，符合 B062 校验）
        test_token = generate_token(session_id="test-session-3", token_version=1, view_type="desktop")

        mock_ws = _build_mock_websocket({"type": "auth", "token": test_token})

        with patch('app.ws_client.get_session', return_value={"session_id": "test-session-3", "owner": "test-user"}):
            with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                    with patch('app.auth.get_token_version', new_callable=AsyncMock, return_value=1):
                        try:
                            from app.ws_client import client_websocket_handler
                            await client_websocket_handler(mock_ws, "test-session-3", view="desktop")
                        except asyncio.CancelledError:
                            pass

        # 验证 view 类型为 desktop
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["view"] == "desktop"


class TestIntegrationMultiView:
    """多视图 presence 测试"""

    @pytest.mark.asyncio
    async def test_presence_sync_between_views(self):
        """测试多视图 presence 同步"""
        from app.ws_client import (
            active_clients,
            ClientConnection,
            get_view_counts,
            _broadcast_presence,
        )

        active_clients.clear()

        # 创建两个模拟客户端
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_ws1, "mobile"),
            ClientConnection("session-1", mock_ws2, "desktop"),
        ]

        # 验证视图计数
        counts = get_view_counts("session-1")
        assert counts["mobile"] == 1
        assert counts["desktop"] == 1

        # 广播 presence
        with patch('app.ws_agent.get_agent_connection', return_value=None):
            await _broadcast_presence("session-1")

        # 验证两个客户端都收到 presence 消息
        assert mock_ws1.send_json.called
        assert mock_ws2.send_json.called


class TestIntegrationMessageForwarding:
    """消息转发测试"""

    @pytest.mark.asyncio
    async def test_agent_output_broadcasts_to_clients(self):
        """Agent 输出广播到所有客户端"""
        from app.ws_agent import active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection, broadcast_to_clients

        active_agents.clear()
        active_clients.clear()

        # 创建模拟 Agent
        mock_agent_ws = AsyncMock()
        agent_conn = AgentConnection("session-1", mock_agent_ws, "test-user")
        active_agents["session-1"] = agent_conn

        # 创建两个模拟客户端
        mock_client_ws1 = AsyncMock()
        mock_client_ws2 = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws1, "mobile"),
            ClientConnection("session-1", mock_client_ws2, "desktop"),
        ]

        # 广播消息
        test_message = {"type": "data", "payload": "SGVsbG8gV29ybGQ="}
        await broadcast_to_clients("session-1", test_message)

        # 验证两个客户端都收到消息
        mock_client_ws1.send_json.assert_called_once_with(test_message)
        mock_client_ws2.send_json.assert_called_once_with(test_message)

    @pytest.mark.asyncio
    async def test_client_input_forwards_to_agent(self):
        """Client 输入转发到 Agent"""
        from app.ws_agent import active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        # 创建模拟 Agent
        mock_agent_ws = AsyncMock()
        agent_conn = AgentConnection("session-1", mock_agent_ws, "test-user")
        active_agents["session-1"] = agent_conn

        # 创建模拟客户端
        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        # 客户端发送输入消息
        from app.ws_client import _handle_client_message
        message = {"type": "data", "payload": "dGVNsbGl0"}
        await _handle_client_message(
            mock_client_ws, "session-1", message, view="mobile"
        )

        # 验证 Agent 收到消息
        mock_agent_ws.send_json.assert_called_once()
        call_args = mock_agent_ws.send_json.call_args[0][0]


class TestRuntimeDeviceApi:
    """多 terminal runtime API 测试"""

    def setup_method(self):
        self.client = TestClient(app)
        self.token = generate_token("runtime-session-1")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        # 覆盖鉴权依赖，跳过 JWT + Redis 验证
        app.dependency_overrides[get_current_user_id] = _mock_user_id

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_id, None)

    def test_list_runtime_devices_returns_owned_devices(self):
        """查询在线 device 列表"""
        sessions = [
            {
                "session_id": "runtime-session-1",
                "owner": "user1",
                "agent_online": True,
                "device": {
                    "device_id": "mbp-01",
                    "name": "Tang MacBook Pro",
                    "last_heartbeat_at": "2026-03-29T02:00:00Z",
                    "max_terminals": 3,
                },
                "terminals": [
                    {"status": "attached"},
                    {"status": "closed"},
                ],
            }
        ]

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.list_sessions_for_user", new=AsyncMock(return_value=sessions)):
                response = self.client.get("/api/runtime/devices", headers=self.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["devices"][0]["device_id"] == "mbp-01"
        assert data["devices"][0]["agent_online"] is True
        assert data["devices"][0]["active_terminals"] == 1

    def test_list_runtime_devices_uses_live_agent_connection_for_online_state(self):
        """设备在线态以当前活跃 agent 连接为准，而不是 Redis 历史字段。"""
        sessions = [
            {
                "session_id": "runtime-session-1",
                "owner": "user1",
                "agent_online": False,
                "device": {
                    "device_id": "mbp-01",
                    "name": "Tang MacBook Pro",
                    "last_heartbeat_at": "2026-03-29T02:00:00Z",
                    "max_terminals": 3,
                },
                "terminals": [],
            }
        ]

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.list_sessions_for_user", new=AsyncMock(return_value=sessions)):
                response = self.client.get("/api/runtime/devices", headers=self.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["devices"][0]["agent_online"] is True

    def test_list_runtime_terminals_uses_live_agent_connection_for_device_online(self):
        """terminal 列表里的 device_online 以活跃 agent 连接为准。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": False,
            "device": {"device_id": "mbp-01"},
        }
        terminals = [{
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "detached",
            "disconnect_reason": None,
            "updated_at": "2026-03-29T02:00:00Z",
            "views": {"mobile": 0, "desktop": 0},
        }]

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=terminals)):
                    with patch("app.runtime_api.get_view_counts", return_value={"mobile": 1, "desktop": 0}):
                        response = self.client.get("/api/runtime/devices/mbp-01/terminals", headers=self.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["device_online"] is True
        assert data["terminals"][0]["views"]["mobile"] == 1

    def test_get_runtime_project_context_includes_recent_terminal_candidates(self):
        """项目候选快照会读取当前设备 recent terminal。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }
        terminals = [
            {
                "terminal_id": "term-1",
                "title": "Claude / remote-control",
                "cwd": "/Users/demo/project/remote-control",
                "command": "claude",
                "status": "live",
                "updated_at": "2026-04-22T12:00:00+00:00",
            }
        ]

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=terminals)):
                with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                    with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "mbp-01"
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["cwd"] == "/Users/demo/project/remote-control"
        assert data["candidates"][0]["source"] == "recent_terminal"
        assert data["candidates"][0]["tool_hints"] == ["claude_code", "shell"]

    def test_get_runtime_project_context_includes_pinned_projects_and_dedupes_cwd(self):
        """固定项目会补入候选，重复 cwd 只保留一份。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }
        terminals = [
            {
                "terminal_id": "term-1",
                "title": "Codex / remote-control",
                "cwd": "/Users/demo/project/remote-control",
                "command": "codex",
                "status": "live",
                "updated_at": "2026-04-22T12:00:00+00:00",
            }
        ]
        pinned_projects = [
            {
                "label": "remote-control pinned",
                "cwd": "/Users/demo/project/remote-control",
                "updated_at": "2026-04-22T11:00:00+00:00",
                "created_at": "2026-04-22T11:00:00+00:00",
            },
            {
                "label": "ai_rules",
                "cwd": "/Users/demo/project/ai_rules",
                "updated_at": "2026-04-22T10:00:00+00:00",
                "created_at": "2026-04-22T10:00:00+00:00",
            },
        ]

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=terminals)):
                with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=pinned_projects)):
                    with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert [candidate["cwd"] for candidate in data["candidates"]] == [
            "/Users/demo/project/remote-control",
            "/Users/demo/project/ai_rules",
        ]
        assert data["candidates"][1]["source"] == "pinned_project"

    def test_get_runtime_project_context_returns_empty_candidates(self):
        """无候选时返回 200 + 空列表。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=[])):
                with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                    with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == "mbp-01"
        assert data["candidates"] == []

    def test_refresh_runtime_project_context_recomputes_snapshot(self):
        """refresh 直接返回新的轻量快照，不改 terminal 主链路。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }
        pinned_projects = [
            {
                "label": "remote-control",
                "cwd": "/Users/demo/project/remote-control",
                "updated_at": "2026-04-22T12:30:00+00:00",
                "created_at": "2026-04-22T12:00:00+00:00",
            }
        ]
        list_terminals = AsyncMock(return_value=[])
        get_pinned = AsyncMock(return_value=pinned_projects)
        get_scan_roots = AsyncMock(return_value=[{"root_path": "/Users/demo/project", "enabled": 1}])

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.list_session_terminals", new=list_terminals):
                with patch("app.runtime_api.get_pinned_projects", new=get_pinned):
                    with patch("app.runtime_api.get_approved_scan_roots", new=get_scan_roots):
                        response = self.client.post(
                            "/api/runtime/devices/mbp-01/project-context:refresh",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["candidates"][0]["label"] == "remote-control"
        list_terminals.assert_awaited_once_with("runtime-session-1")
        get_pinned.assert_awaited_once_with("user1", "mbp-01")
        get_scan_roots.assert_awaited_once_with("user1", "mbp-01")

    def test_get_runtime_project_context_settings(self):
        """settings 接口返回项目来源和 planner 配置。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch(
                "app.runtime_api.get_pinned_projects",
                new=AsyncMock(
                    return_value=[
                        {"label": "remote-control", "cwd": "/Users/demo/project/remote-control"},
                    ],
                ),
            ):
                with patch(
                    "app.runtime_api.get_approved_scan_roots",
                    new=AsyncMock(
                        return_value=[
                            {"root_path": "/Users/demo/project", "scan_depth": 2, "enabled": 1},
                        ],
                    ),
                ):
                    with patch(
                        "app.runtime_api.get_planner_config",
                        new=AsyncMock(
                            return_value={
                                "provider": "llm",
                                "llm_enabled": 1,
                                "endpoint_profile": "openai_compatible",
                                "credentials_mode": "client_secure_storage",
                                "requires_explicit_opt_in": 1,
                            },
                        ),
                    ):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context/settings",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["pinned_projects"][0]["cwd"] == "/Users/demo/project/remote-control"
        assert data["approved_scan_roots"][0]["root_path"] == "/Users/demo/project"
        assert data["planner_config"]["provider"] == "llm"
        assert data["planner_config"]["llm_enabled"] is True

    def test_get_runtime_project_context_settings_defaults_to_enabled_smart_planner(self):
        """未保存 planner 配置时，默认返回已开启的智能规划。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                    with patch(
                        "app.runtime_api.get_planner_config",
                        new=AsyncMock(return_value=None),
                    ):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context/settings",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["planner_config"]["provider"] == "claude_cli"
        assert data["planner_config"]["llm_enabled"] is True
        assert data["planner_config"]["requires_explicit_opt_in"] is False

    def test_get_runtime_project_context_settings_upgrades_legacy_disabled_default(self):
        """历史默认关闭配置在读取时自动升级为智能默认开启。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                    with patch(
                        "app.runtime_api.get_planner_config",
                        new=AsyncMock(
                            return_value={
                                "provider": "local_rules",
                                "llm_enabled": 0,
                                "endpoint_profile": "openai_compatible",
                                "credentials_mode": "client_secure_storage",
                                "requires_explicit_opt_in": 1,
                            },
                        ),
                    ):
                        response = self.client.get(
                            "/api/runtime/devices/mbp-01/project-context/settings",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["planner_config"]["provider"] == "claude_cli"
        assert data["planner_config"]["llm_enabled"] is True
        assert data["planner_config"]["requires_explicit_opt_in"] is False

    def test_put_runtime_project_context_settings(self):
        """settings 保存会分别写入 pinned/scan_root/planner。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }
        replace_pinned = AsyncMock()
        replace_scan_roots = AsyncMock()
        save_planner = AsyncMock()

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.replace_pinned_projects", new=replace_pinned):
                with patch("app.runtime_api.replace_approved_scan_roots", new=replace_scan_roots):
                    with patch("app.runtime_api.save_planner_config", new=save_planner):
                        with patch(
                            "app.runtime_api.get_pinned_projects",
                            new=AsyncMock(
                                return_value=[
                                    {"label": "remote-control", "cwd": "/Users/demo/project/remote-control"},
                                ],
                            ),
                        ):
                            with patch(
                                "app.runtime_api.get_approved_scan_roots",
                                new=AsyncMock(
                                    return_value=[
                                        {"root_path": "/Users/demo/project", "scan_depth": 2, "enabled": 1},
                                    ],
                                ),
                            ):
                                with patch(
                                    "app.runtime_api.get_planner_config",
                                    new=AsyncMock(
                                        return_value={
                                            "provider": "llm",
                                            "llm_enabled": 1,
                                            "endpoint_profile": "openai_compatible",
                                            "credentials_mode": "client_secure_storage",
                                            "requires_explicit_opt_in": 1,
                                        },
                                    ),
                                ):
                                    response = self.client.put(
                                        "/api/runtime/devices/mbp-01/project-context/settings",
                                        headers=self.headers,
                                        json={
                                            "pinned_projects": [
                                                {
                                                    "label": "remote-control",
                                                    "cwd": "/Users/demo/project/remote-control",
                                                }
                                            ],
                                            "approved_scan_roots": [
                                                {
                                                    "root_path": "/Users/demo/project",
                                                    "scan_depth": 2,
                                                    "enabled": True,
                                                }
                                            ],
                                            "planner_config": {
                                                "provider": "llm",
                                                "llm_enabled": True,
                                                "endpoint_profile": "openai_compatible",
                                                "credentials_mode": "client_secure_storage",
                                                "requires_explicit_opt_in": True,
                                            },
                                        },
                                    )

        assert response.status_code == 200
        replace_pinned.assert_awaited_once()
        replace_scan_roots.assert_awaited_once()
        save_planner.assert_awaited_once_with(
            "user1",
            "mbp-01",
            {
                "provider": "llm",
                "llm_enabled": True,
                "endpoint_profile": "openai_compatible",
                "credentials_mode": "client_secure_storage",
                "requires_explicit_opt_in": True,
            },
        )

    def test_create_assistant_plan_success(self):
        """assistant/plan 成功返回 trace + command_sequence，并落库规划记录。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "name": "Tang MacBook Pro",
                "platform": "macos",
                "hostname": "demo-mbp",
                "max_terminals": 3,
            },
        }
        planner_mock = AsyncMock(
            return_value={
                "assistant_messages": [
                    {"type": "assistant", "text": "我先帮你定位目标项目。"},
                ],
                "trace": [
                    {
                        "stage": "planner",
                        "title": "调用服务端 LLM",
                        "status": "completed",
                        "summary": "已生成合法命令序列",
                    }
                ],
                "command_sequence": {
                    "summary": "进入 remote-control 并启动 Claude",
                    "provider": "service_llm",
                    "source": "intent",
                    "need_confirm": True,
                    "steps": [
                        {
                            "id": "step_1",
                            "label": "进入项目目录",
                            "command": "cd /Users/demo/project/remote-control",
                        },
                        {
                            "id": "step_2",
                            "label": "启动 Claude",
                            "command": "claude",
                        },
                    ],
                },
                "fallback_used": False,
                "fallback_reason": None,
                "evaluation_context": {"tool_calls": 2},
            }
        )
        save_run = AsyncMock()

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch(
                    "app.runtime_api.list_session_terminals",
                    new=AsyncMock(
                        return_value=[
                            {
                                "terminal_id": "term-1",
                                "title": "Claude / remote-control",
                                "cwd": "/Users/demo/project/remote-control",
                                "command": "claude",
                                "status": "attached",
                                "updated_at": "2026-04-22T12:00:00+00:00",
                            }
                        ]
                    ),
                ):
                    with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                        with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                            with patch("app.runtime_api.get_planner_config", new=AsyncMock(return_value=None)):
                                with patch("app.runtime_api.list_assistant_planner_memory", new=AsyncMock(return_value=[])):
                                    with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=None)):
                                        with patch("app.runtime_api.plan_with_service_llm", new=planner_mock):
                                            with patch("app.runtime_api.save_assistant_planner_run", new=save_run):
                                                response = self.client.post(
                                                    "/api/runtime/devices/mbp-01/assistant/plan",
                                                    headers=self.headers,
                                                    json={
                                                        "intent": "进入 remote-control 修登录问题",
                                                        "conversation_id": "assistant-session-001",
                                                        "message_id": "msg-001",
                                                        "fallback_policy": {
                                                            "allow_claude_cli": True,
                                                            "allow_local_rules": True,
                                                        },
                                                    },
                                                )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "assistant-session-001"
        assert data["command_sequence"]["provider"] == "service_llm"
        assert data["command_sequence"]["steps"][0]["command"] == "cd /Users/demo/project/remote-control"
        assert data["evaluation_context"]["matched_cwd"] == "/Users/demo/project/remote-control"
        save_run.assert_awaited_once()

    def test_create_assistant_plan_stream_success(self):
        """assistant/plan/stream 应返回增量事件和最终结果。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "name": "Tang MacBook Pro",
                "platform": "macos",
                "hostname": "demo-mbp",
                "max_terminals": 3,
            },
        }
        planner_mock = AsyncMock(
            return_value={
                "assistant_messages": [
                    {"type": "assistant", "text": "我先帮你定位目标项目。"},
                ],
                "trace": [
                    {
                        "stage": "planner",
                        "title": "调用服务端 LLM",
                        "status": "completed",
                        "summary": "已生成合法命令序列",
                    }
                ],
                "command_sequence": {
                    "summary": "进入 remote-control 并启动 Claude",
                    "provider": "service_llm",
                    "source": "intent",
                    "need_confirm": True,
                    "steps": [
                        {
                            "id": "step_1",
                            "label": "进入项目目录",
                            "command": "cd /Users/demo/project/remote-control",
                        },
                        {
                            "id": "step_2",
                            "label": "启动 Claude",
                            "command": "claude",
                        },
                    ],
                },
                "fallback_used": False,
                "fallback_reason": None,
                "evaluation_context": {"tool_calls": 2},
            }
        )
        save_run = AsyncMock()

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch(
                    "app.runtime_api.list_session_terminals",
                    new=AsyncMock(
                        return_value=[
                            {
                                "terminal_id": "term-1",
                                "title": "Claude / remote-control",
                                "cwd": "/Users/demo/project/remote-control",
                                "command": "claude",
                                "status": "attached",
                                "updated_at": "2026-04-22T12:00:00+00:00",
                            }
                        ]
                    ),
                ):
                    with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                        with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                            with patch("app.runtime_api.get_planner_config", new=AsyncMock(return_value=None)):
                                with patch("app.runtime_api.list_assistant_planner_memory", new=AsyncMock(return_value=[])):
                                    with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=None)):
                                        with patch("app.runtime_api.plan_with_service_llm", new=planner_mock):
                                            with patch("app.runtime_api.save_assistant_planner_run", new=save_run):
                                                response = self.client.post(
                                                    "/api/runtime/devices/mbp-01/assistant/plan/stream",
                                                    headers=self.headers,
                                                    json={
                                                        "intent": "进入 remote-control 修登录问题",
                                                        "conversation_id": "assistant-session-001",
                                                        "message_id": "msg-001",
                                                        "fallback_policy": {
                                                            "allow_claude_cli": True,
                                                            "allow_local_rules": True,
                                                        },
                                                    },
                                                )

        assert response.status_code == 200
        lines = [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]
        assert lines[0]["type"] in {"status_update", "assistant_message", "trace", "tool_call"}
        assert any(line.get("type") == "status_update" for line in lines)
        assert any(line.get("type") == "tool_call" for line in lines)
        assert any(line.get("type") == "trace" for line in lines)
        assert any(
            line.get("type") == "trace"
            and line.get("trace_item", {}).get("title") == "匹配项目"
            for line in lines
        )
        assert any(
            line.get("type") == "tool_call"
            and line.get("tool_call", {}).get("tool_name") == "plan_with_service_llm"
            and line.get("tool_call", {}).get("status") == "completed"
            for line in lines
        )
        assert any(
            line.get("type") == "status_update"
            and line.get("status_update", {}).get("title") == "生成命令序列"
            for line in lines
        )
        assert any(
            line.get("type") == "assistant_message"
            and line.get("assistant_message", {}).get("text") == "我先帮你定位目标项目。"
            for line in lines
        )
        assert lines[-1]["type"] == "result"
        assert lines[-1]["plan"]["command_sequence"]["provider"] == "service_llm"
        assert (
            lines[-1]["plan"]["evaluation_context"]["matched_cwd"]
            == "/Users/demo/project/remote-control"
        )
        save_run.assert_awaited_once()

    def test_create_assistant_plan_stream_supports_rizhi_intent(self):
        """真实意图“我想进入日知项目”应命中日知候选并返回对应 cwd。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "name": "Tang MacBook Pro",
                "platform": "macos",
                "hostname": "demo-mbp",
                "max_terminals": 3,
            },
        }
        planner_mock = AsyncMock(
            return_value={
                "assistant_messages": [
                    {"type": "assistant", "text": "已定位日知项目，准备进入对应目录。"},
                ],
                "trace": [
                    {
                        "stage": "planner",
                        "title": "调用服务端 LLM",
                        "status": "completed",
                        "summary": "已生成进入日知项目的命令序列",
                    }
                ],
                "command_sequence": {
                    "summary": "进入日知项目并启动 Claude",
                    "provider": "service_llm",
                    "source": "intent",
                    "need_confirm": True,
                    "steps": [
                        {
                            "id": "step_1",
                            "label": "进入项目目录",
                            "command": "cd /Users/demo/project/rizhi",
                        },
                        {
                            "id": "step_2",
                            "label": "启动 Claude",
                            "command": "claude",
                        },
                    ],
                },
                "fallback_used": False,
                "fallback_reason": None,
                "evaluation_context": {"tool_calls": 2},
            }
        )
        save_run = AsyncMock()

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=[])):
                    with patch(
                        "app.runtime_api.get_pinned_projects",
                        new=AsyncMock(
                            return_value=[
                                {
                                    "label": "日知",
                                    "cwd": "/Users/demo/project/rizhi",
                                    "updated_at": "2026-04-22T12:00:00+00:00",
                                }
                            ]
                        ),
                    ):
                        with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                            with patch("app.runtime_api.get_planner_config", new=AsyncMock(return_value=None)):
                                with patch("app.runtime_api.list_assistant_planner_memory", new=AsyncMock(return_value=[])):
                                    with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=None)):
                                        with patch("app.runtime_api.plan_with_service_llm", new=planner_mock):
                                            with patch("app.runtime_api.save_assistant_planner_run", new=save_run):
                                                response = self.client.post(
                                                    "/api/runtime/devices/mbp-01/assistant/plan/stream",
                                                    headers=self.headers,
                                                    json={
                                                        "intent": "我想进入日知项目",
                                                        "conversation_id": "assistant-session-002",
                                                        "message_id": "msg-002",
                                                        "fallback_policy": {
                                                            "allow_claude_cli": True,
                                                            "allow_local_rules": True,
                                                        },
                                                    },
                                                )

        assert response.status_code == 200
        lines = [
            json.loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]
        assert any(line.get("type") == "status_update" for line in lines)
        assert any(line.get("type") == "tool_call" for line in lines)
        assert any(
            line.get("type") == "assistant_message"
            and line.get("assistant_message", {}).get("text")
            == "已定位日知项目，准备进入对应目录。"
            for line in lines
        )
        result = lines[-1]
        assert result["type"] == "result"
        assert result["plan"]["command_sequence"]["summary"] == "进入日知项目并启动 Claude"
        assert result["plan"]["evaluation_context"]["matched_label"] == "日知"
        assert result["plan"]["evaluation_context"]["matched_cwd"] == "/Users/demo/project/rizhi"
        assert (
            result["plan"]["command_sequence"]["steps"][0]["command"]
            == "cd /Users/demo/project/rizhi"
        )
        save_run.assert_awaited_once()

    def test_create_assistant_plan_requires_online_device(self):
        """assistant/plan 在设备离线时返回 409。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": False,
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=False):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                response = self.client.post(
                    "/api/runtime/devices/mbp-01/assistant/plan",
                    headers=self.headers,
                    json={
                        "intent": "进入 remote-control",
                        "conversation_id": "assistant-session-001",
                        "message_id": "msg-001",
                    },
                )

        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "device_offline"

    def test_create_assistant_plan_handles_user_rate_limit(self):
        """assistant/plan 用户级限流返回 429 + Retry-After。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=60)):
                    response = self.client.post(
                        "/api/runtime/devices/mbp-01/assistant/plan",
                        headers=self.headers,
                        json={
                            "intent": "进入 remote-control",
                            "conversation_id": "assistant-session-001",
                            "message_id": "msg-001",
                        },
                    )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        assert response.json()["detail"]["reason"] == "assistant_plan_rate_limited"

    def test_create_assistant_plan_handles_budget_block(self):
        """provider 预算或配额受限时返回稳定的 429。"""
        from app.assistant_planner import AssistantPlannerRateLimited

        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {"device_id": "mbp-01", "max_terminals": 3},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=[])):
                    with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                        with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                            with patch("app.runtime_api.get_planner_config", new=AsyncMock(return_value=None)):
                                with patch("app.runtime_api.list_assistant_planner_memory", new=AsyncMock(return_value=[])):
                                    with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=None)):
                                        with patch(
                                            "app.runtime_api.plan_with_service_llm",
                                            new=AsyncMock(
                                                side_effect=AssistantPlannerRateLimited(
                                                    "service_llm_budget_blocked",
                                                    "服务端智能规划当前预算或配额受限",
                                                    retry_after=3600,
                                                )
                                            ),
                                        ):
                                            response = self.client.post(
                                                "/api/runtime/devices/mbp-01/assistant/plan",
                                                headers=self.headers,
                                                json={
                                                    "intent": "进入 remote-control",
                                                    "conversation_id": "assistant-session-001",
                                                    "message_id": "msg-001",
                                                },
                                            )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "3600"
        assert response.json()["detail"]["reason"] == "service_llm_budget_blocked"

    def test_create_assistant_plan_handles_provider_timeout(self):
        """provider timeout 返回 504，而不是无限等待。"""
        from app.assistant_planner import AssistantPlannerTimeout

        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {"device_id": "mbp-01", "max_terminals": 3},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.list_session_terminals", new=AsyncMock(return_value=[])):
                    with patch("app.runtime_api.get_pinned_projects", new=AsyncMock(return_value=[])):
                        with patch("app.runtime_api.get_approved_scan_roots", new=AsyncMock(return_value=[])):
                            with patch("app.runtime_api.get_planner_config", new=AsyncMock(return_value=None)):
                                with patch("app.runtime_api.list_assistant_planner_memory", new=AsyncMock(return_value=[])):
                                    with patch("app.runtime_api._check_assistant_plan_rate_limit", new=AsyncMock(return_value=None)):
                                        with patch(
                                            "app.runtime_api.plan_with_service_llm",
                                            new=AsyncMock(
                                                side_effect=AssistantPlannerTimeout(
                                                    "service_llm_timeout",
                                                    "服务端 LLM planner 调用超时",
                                                )
                                            ),
                                        ):
                                            response = self.client.post(
                                                "/api/runtime/devices/mbp-01/assistant/plan",
                                                headers=self.headers,
                                                json={
                                                    "intent": "进入 remote-control",
                                                    "conversation_id": "assistant-session-001",
                                                    "message_id": "msg-001",
                                                },
                                            )

        assert response.status_code == 504
        assert response.json()["detail"]["reason"] == "service_llm_timeout"

    def test_create_assistant_execution_report_success(self):
        """executions/report 成功回写后返回 ack。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch(
                "app.runtime_api.get_assistant_planner_run",
                new=AsyncMock(return_value={"execution_status": "planned"}),
            ):
                with patch(
                    "app.runtime_api.report_assistant_execution",
                    new=AsyncMock(return_value={"execution_status": "succeeded"}),
                ) as report_mock:
                    response = self.client.post(
                        "/api/runtime/devices/mbp-01/assistant/executions/report",
                        headers=self.headers,
                        json={
                            "conversation_id": "assistant-session-001",
                            "message_id": "msg-001",
                            "terminal_id": "term-1",
                            "execution_status": "succeeded",
                            "failed_step_id": None,
                            "output_summary": "已进入 remote-control 并启动 Claude",
                            "command_sequence": {
                                "summary": "进入 remote-control 并启动 Claude",
                                "provider": "service_llm",
                                "source": "intent",
                                "need_confirm": True,
                                "steps": [
                                    {
                                        "id": "step_1",
                                        "label": "进入项目目录",
                                        "command": "cd /Users/demo/project/remote-control",
                                    },
                                    {
                                        "id": "step_2",
                                        "label": "启动 Claude",
                                        "command": "claude",
                                    },
                                ],
                            },
                        },
                    )

        assert response.status_code == 200
        assert response.json() == {
            "acknowledged": True,
            "memory_updated": True,
            "evaluation_recorded": True,
        }
        report_mock.assert_awaited_once()

    def test_create_assistant_execution_report_returns_404_when_plan_missing(self):
        """没有对应规划记录时返回 404。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_assistant_planner_run", new=AsyncMock(return_value=None)):
                response = self.client.post(
                    "/api/runtime/devices/mbp-01/assistant/executions/report",
                    headers=self.headers,
                    json={
                        "conversation_id": "assistant-session-001",
                        "message_id": "msg-001",
                        "terminal_id": "term-1",
                        "execution_status": "failed",
                        "failed_step_id": "step_1",
                        "output_summary": "目录不存在",
                        "command_sequence": {
                            "summary": "进入 remote-control 并启动 Claude",
                            "provider": "service_llm",
                            "source": "intent",
                            "need_confirm": True,
                            "steps": [
                                {
                                    "id": "step_1",
                                    "label": "进入项目目录",
                                    "command": "cd /Users/demo/project/remote-control",
                                }
                            ],
                        },
                    },
                )

        assert response.status_code == 404
        assert response.json()["detail"]["reason"] == "assistant_plan_not_found"

    def test_runtime_device_listing_falls_back_to_session_user_id(self):
        """owner 为空时，runtime 鉴权回退到 session.user_id。"""
        sessions = [
            {
                "session_id": "runtime-session-1",
                "owner": "",
                "user_id": "user1",
                "agent_online": True,
                "device": {
                    "device_id": "mbp-01",
                    "name": "Tang MacBook Pro",
                    "last_heartbeat_at": "2026-03-29T02:00:00Z",
                    "max_terminals": 3,
                },
                "terminals": [],
            }
        ]

        with patch("app.runtime_api.list_sessions_for_user", new=AsyncMock(return_value=sessions)):
            response = self.client.get("/api/runtime/devices", headers=self.headers)

        assert response.status_code == 200
        data = response.json()
        assert data["devices"][0]["device_id"] == "mbp-01"

    def test_update_runtime_device_settings(self):
        """更新 device 配置成功。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "name": "Old Name",
                "last_heartbeat_at": "2026-03-29T02:00:00Z",
                "max_terminals": 3,
            },
            "terminals": [],
        }
        updated = {
            **session,
            "device": {
                **session["device"],
                "name": "New Name",
            },
        }

        update_mock = AsyncMock(return_value=updated)

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.update_session_device_metadata", new=update_mock):
                response = self.client.patch(
                    "/api/runtime/devices/mbp-01",
                    headers=self.headers,
                    json={"name": "New Name", "max_terminals": 5},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["max_terminals"] == 3
        update_mock.assert_awaited_once_with(
            "runtime-session-1",
            name="New Name",
        )

    def test_update_runtime_device_requires_at_least_one_field(self):
        """空更新请求会被拒绝。"""
        session = {
            "session_id": "runtime-session-1",
            "owner": "user1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "name": "Old Name",
                "last_heartbeat_at": "2026-03-29T02:00:00Z",
                "max_terminals": 3,
            },
            "terminals": [],
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            response = self.client.patch(
                "/api/runtime/devices/mbp-01",
                headers=self.headers,
                json={},
            )

        assert response.status_code == 400
        assert "至少需要提供一个可更新字段" in response.json()["detail"]

    def test_create_runtime_terminal_requires_online_device(self):
        """device offline 时不允许创建 terminal"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": False,
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=False):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                response = self.client.post(
                    "/api/runtime/devices/mbp-01/terminals",
                    headers=self.headers,
                    json={
                        "terminal_id": "term-1",
                        "title": "Claude / ai_rules",
                        "cwd": "./",
                        "command": "claude code",
                        "env": {},
                    },
                )

        assert response.status_code == 409
        assert "offline" in response.json()["detail"]

    def test_create_runtime_terminal_uses_live_agent_connection_when_session_flag_is_stale(self):
        """session.agent_online 为 false 但 agent 当前在线时仍允许创建。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": False,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "pending",
            "disconnect_reason": None,
            "views": {"mobile": 0, "desktop": 0},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.create_session_terminal", new=AsyncMock(return_value=terminal)):
                    with patch(
                        "app.runtime_api.request_agent_create_terminal",
                        new=AsyncMock(return_value={**terminal, "status": "detached"}),
                    ):
                        response = self.client.post(
                            "/api/runtime/devices/mbp-01/terminals",
                            headers=self.headers,
                            json={
                                "terminal_id": "term-1",
                                "title": "Claude / ai_rules",
                                "cwd": "./",
                                "command": "claude code",
                                "env": {},
                            },
                        )

        assert response.status_code == 200

    def test_create_runtime_terminal_marks_device_offline_when_agent_disconnects(self):
        """创建过程如果 agent 已离线，terminal 应收口为 device_offline。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.create_session_terminal", new=AsyncMock(return_value={"terminal_id": "term-1"})):
                    with patch(
                        "app.runtime_api.request_agent_create_terminal",
                        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="device offline")),
                    ):
                        with patch("app.runtime_api.update_session_terminal_status", new=AsyncMock()) as mock_update:
                            response = self.client.post(
                                "/api/runtime/devices/mbp-01/terminals",
                                headers=self.headers,
                                json={
                                    "terminal_id": "term-1",
                                    "title": "Claude / ai_rules",
                                    "cwd": "./",
                                    "command": "claude code",
                                    "env": {},
                                },
                            )

        assert response.status_code == 409
        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["disconnect_reason"] == "device_offline"

    def test_create_runtime_terminal_when_device_online(self):
        """device online 时创建 terminal 成功"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "pending",
            "disconnect_reason": None,
            "views": {"mobile": 0, "desktop": 0},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.create_session_terminal", new=AsyncMock(return_value=terminal)):
                    with patch(
                        "app.runtime_api.request_agent_create_terminal",
                        new=AsyncMock(return_value={**terminal, "status": "detached"}),
                    ):
                        response = self.client.post(
                            "/api/runtime/devices/mbp-01/terminals",
                            headers=self.headers,
                            json={
                                "terminal_id": "term-1",
                                "title": "Claude / ai_rules",
                                "cwd": "./",
                                "command": "claude code",
                                "env": {"TERM": "xterm-256color"},
                            },
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["terminal_id"] == "term-1"
        assert data["status"] == "detached"

    def test_create_runtime_terminal_ignores_closed_history_for_capacity(self):
        """closed terminal 历史记录不应阻塞新的 create。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {
                "device_id": "mbp-01",
                "max_terminals": 1,
            },
            "terminals": [
                {
                    "terminal_id": "term-closed",
                    "status": "closed",
                }
            ],
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "pending",
            "disconnect_reason": None,
            "views": {"mobile": 0, "desktop": 0},
        }

        with patch("app.runtime_api.is_agent_connected", return_value=True):
            with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
                with patch("app.runtime_api.create_session_terminal", new=AsyncMock(return_value=terminal)):
                    with patch(
                        "app.runtime_api.request_agent_create_terminal",
                        new=AsyncMock(return_value={**terminal, "status": "detached"}),
                    ):
                        response = self.client.post(
                            "/api/runtime/devices/mbp-01/terminals",
                            headers=self.headers,
                            json={
                                "terminal_id": "term-1",
                                "title": "Claude / ai_rules",
                                "cwd": "./",
                                "command": "claude code",
                                "env": {},
                            },
                        )

        assert response.status_code == 200
        assert response.json()["terminal_id"] == "term-1"

    def test_close_runtime_terminal_when_no_active_views(self):
        """无活跃视图时允许关闭 terminal。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "detached",
            "disconnect_reason": "network_lost",
            "updated_at": "2026-03-29T02:00:00Z",
            "views": {"mobile": 0, "desktop": 0},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_session_terminal", new=AsyncMock(return_value=terminal)):
                with patch("app.runtime_api.request_agent_close_terminal_with_ack", new=AsyncMock()):
                    with patch(
                        "app.runtime_api.update_session_terminal_status",
                        new=AsyncMock(return_value={**terminal, "status": "closed", "disconnect_reason": "server_forced_close"}),
                    ):
                        response = self.client.delete(
                            "/api/runtime/devices/mbp-01/terminals/term-1",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["terminal_id"] == "term-1"
        assert data["status"] == "closed"

    def test_update_runtime_terminal_title(self):
        """更新 terminal 标题成功。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "New Title",
            "cwd": "./",
            "command": "claude code",
            "status": "detached",
            "disconnect_reason": None,
            "updated_at": "2026-03-29T02:00:00Z",
            "views": {"mobile": 0, "desktop": 0},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.update_session_terminal_metadata", new=AsyncMock(return_value=terminal)):
                response = self.client.patch(
                    "/api/runtime/devices/mbp-01/terminals/term-1",
                    headers=self.headers,
                    json={"title": "New Title"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title"

    def test_close_runtime_terminal_allows_forced_close_with_active_views(self):
        """terminal 即使仍有活跃视图也允许被主动关闭。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "attached",
            "views": {"mobile": 1, "desktop": 0},
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_session_terminal", new=AsyncMock(return_value=terminal)):
                with patch("app.runtime_api.request_agent_close_terminal_with_ack", new=AsyncMock()) as request_close:
                    with patch(
                        "app.runtime_api.update_session_terminal_status",
                        new=AsyncMock(return_value={**terminal, "status": "closed", "disconnect_reason": "server_forced_close"}),
                    ):
                        response = self.client.delete(
                            "/api/runtime/devices/mbp-01/terminals/term-1",
                            headers=self.headers,
                        )

        assert response.status_code == 200
        request_close.assert_awaited_once()
        assert response.json()["status"] == "closed"

    def test_close_runtime_terminal_allows_stale_attached_without_views(self):
        """stale attached 且 views=0 时允许关闭。"""
        session = {
            "session_id": "runtime-session-1",
            "agent_online": True,
            "device": {"device_id": "mbp-01"},
        }
        terminal = {
            "terminal_id": "term-1",
            "title": "Claude / ai_rules",
            "cwd": "./",
            "command": "claude code",
            "status": "attached",
            "views": {"mobile": 0, "desktop": 0},
            "updated_at": "2026-03-29T02:00:00Z",
            "disconnect_reason": None,
        }

        with patch("app.runtime_api.get_session_by_device_id", new=AsyncMock(return_value=session)):
            with patch("app.runtime_api.get_session_terminal", new=AsyncMock(return_value=terminal)):
                with patch("app.runtime_api.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                    with patch("app.runtime_api.request_agent_close_terminal_with_ack", new=AsyncMock()):
                        with patch(
                            "app.runtime_api.update_session_terminal_status",
                            new=AsyncMock(return_value={**terminal, "status": "closed", "disconnect_reason": "server_forced_close"}),
                        ):
                            response = self.client.delete(
                                "/api/runtime/devices/mbp-01/terminals/term-1",
                                headers=self.headers,
                            )

        assert response.status_code == 200
        assert response.json()["status"] == "closed"


class TestIntegrationContracts:
    """契约验证测试"""

    @pytest.mark.asyncio
    async def test_contract_002_agent_connected_message(self):
        """验证 CONTRACT-002: Agent connected 消息格式"""
        from app.ws_agent import active_agents
        from app.auth import generate_token

        active_agents.clear()
        test_token = generate_token(session_id="contract-test-1", token_version=1, view_type="mobile")

        mock_ws = _build_mock_websocket({"type": "auth", "token": test_token})

        with patch('app.ws_agent.get_session', return_value={"session_id": "contract-test-1", "owner": "owner-1"}):
            with patch('app.ws_agent.set_session_online', new_callable=AsyncMock):
                with patch('app.ws_client.get_view_counts', return_value={"mobile": 1, "desktop": 0}):
                    with patch('app.auth.get_token_version', new_callable=AsyncMock, return_value=1):
                        try:
                            from app.ws_agent import agent_websocket_handler
                            await agent_websocket_handler(mock_ws)
                        except asyncio.CancelledError:
                            pass

        # 验证消息格式符合 CONTRACT-002
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "connected"
        assert "session_id" in call_args
        assert "owner" in call_args
        assert "views" in call_args
        assert "timestamp" in call_args

    @pytest.mark.asyncio
    async def test_contract_003_client_connected_message(self):
        """验证 CONTRACT-003: Client connected 消息格式"""
        from app.ws_client import active_clients
        from app.auth import generate_token

        active_clients.clear()
        test_token = generate_token(session_id="contract-test-2", token_version=1, view_type="mobile")

        mock_ws = _build_mock_websocket({"type": "auth", "token": test_token})

        with patch('app.ws_client.get_session', return_value={"session_id": "contract-test-2", "owner": "owner-2"}):
            with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                    with patch('app.auth.get_token_version', new_callable=AsyncMock, return_value=1):
                        try:
                            from app.ws_client import client_websocket_handler
                            await client_websocket_handler(mock_ws, "contract-test-2", view="mobile")
                        except asyncio.CancelledError:
                            pass

        # 验证消息格式符合 CONTRACT-003
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "connected"
        assert "session_id" in call_args
        assert "agent_online" in call_args
        assert "view" in call_args
        assert "owner" in call_args
        assert "timestamp" in call_args


class TestTerminalsChangedBroadcastIntegration:
    """终端变化广播集成测试"""

    @pytest.mark.asyncio
    async def test_terminal_created_broadcasts_to_all_session_clients(self):
        """terminal_created 应广播到 session 级别的所有客户端"""
        from app.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        # 设置 Agent 连接
        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 设置多个客户端连接（模拟手机端和桌面端）
        mock_mobile_ws = AsyncMock()
        mock_desktop_ws = AsyncMock()
        mock_other_terminal_ws = AsyncMock()

        # session 级别的客户端（关键：这些客户端没有绑定特定终端）
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_mobile_ws, "mobile"),
            ClientConnection("session-1", mock_desktop_ws, "desktop"),
        ]
        # 终端级别的客户端（绑定到其他终端）
        active_clients["session-1:term-other"] = [
            ClientConnection("session-1", mock_other_terminal_ws, "mobile", terminal_id="term-other"),
        ]

        with patch("app.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # 验证 session 级别的客户端都收到了 terminals_changed 消息
        mobile_received = False
        desktop_received = False
        other_terminal_received = False

        for call in mock_mobile_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "created"
                assert msg["terminal_id"] == "term-new"
                assert "timestamp" in msg
                mobile_received = True

        for call in mock_desktop_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                desktop_received = True

        for call in mock_other_terminal_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                other_terminal_received = True

        assert mobile_received, "Mobile client should receive terminals_changed"
        assert desktop_received, "Desktop client should receive terminals_changed"
        # broadcast_to_clients(session_id, msg, terminal_id=None) 会广播到该 session 下所有频道
        # 所以终端级别的客户端也会收到
        assert other_terminal_received, "Other terminal client should also receive session-level broadcast"

    @pytest.mark.asyncio
    async def test_terminal_closed_broadcasts_to_session_clients(self):
        """terminal_closed 应广播到 session 级别的所有客户端"""
        from app.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        with patch("app.ws_agent.update_session_terminal_status", new=AsyncMock()):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-1", "reason": "terminal_exit"},
            )

        received = False
        for call in mock_client_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "closed"
                assert msg["terminal_id"] == "term-1"
                assert msg["reason"] == "terminal_exit"
                assert "timestamp" in msg
                received = True

        assert received, "Client should receive terminals_changed on terminal close"

    @pytest.mark.asyncio
    async def test_broadcast_isolation_between_sessions(self):
        """广播应该隔离在不同 session 之间"""
        from app.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        # 设置两个不同的 session
        mock_agent_ws1 = AsyncMock()
        mock_agent_ws2 = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws1, "user1")
        active_agents["session-2"] = AgentConnection("session-2", mock_agent_ws2, "user2")

        # 每个 session 有自己的客户端
        mock_client_ws1 = AsyncMock()
        mock_client_ws2 = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws1, "mobile"),
        ]
        active_clients["session-2"] = [
            ClientConnection("session-2", mock_client_ws2, "mobile"),
        ]

        with patch("app.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            # session-1 创建终端
            await _handle_agent_message(
                mock_agent_ws1,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # session-1 的客户端应该收到
        session1_received = False
        for call in mock_client_ws1.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                session1_received = True

        # session-2 的客户端不应该收到
        session2_received = False
        for call in mock_client_ws2.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                session2_received = True

        assert session1_received, "session-1 client should receive broadcast"
        assert not session2_received, "session-2 client should NOT receive broadcast"

    @pytest.mark.asyncio
    async def test_terminal_closed_clears_pending_futures(self):
        """terminal_closed 应该正确处理 pending futures"""
        from app.ws_agent import (
            _handle_agent_message,
            active_agents,
            AgentConnection,
            pending_terminal_creates,
            pending_terminal_closes,
        )
        from app.ws_client import active_clients

        active_agents.clear()
        active_clients.clear()
        pending_terminal_creates.clear()
        pending_terminal_closes.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 创建 pending futures
        loop = asyncio.get_running_loop()
        create_future = loop.create_future()
        close_future = loop.create_future()
        pending_terminal_creates[("session-1", "term-1")] = create_future
        pending_terminal_closes[("session-1", "term-2")] = close_future

        with patch("app.ws_agent.update_session_terminal_status", new=AsyncMock()):
            # 关闭 term-1（有 pending create）
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-1", "reason": "create_failed"},
            )

            # 关闭 term-2（有 pending close）
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-2", "reason": "terminal_exit"},
            )

        # 验证 futures 被正确处理
        assert create_future.done()
        assert close_future.done()
        with pytest.raises(RuntimeError):
            create_future.result()
        assert close_future.result()["terminal_id"] == "term-2"

        # 验证 futures 被清理
        assert ("session-1", "term-1") not in pending_terminal_creates
        assert ("session-1", "term-2") not in pending_terminal_closes

    @pytest.mark.asyncio
    async def test_terminals_changed_message_format(self):
        """验证 terminals_changed 消息格式"""
        from app.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        with patch("app.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # 验证消息格式
        for call in mock_client_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                # 必需字段
                assert "action" in msg
                assert "terminal_id" in msg
                assert "timestamp" in msg
                # action 应该是有效值
                assert msg["action"] in ["created", "closed"]
                # timestamp 应该是 ISO 格式
                assert "T" in msg["timestamp"]  # ISO 8601 格式包含 T
                break

    @pytest.mark.asyncio
    async def test_no_broadcast_when_terminal_id_missing(self):
        """terminal_id 缺失时不应广播"""
        from app.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        # 发送没有 terminal_id 的消息
        await _handle_agent_message(
            mock_agent_ws,
            "session-1",
            {"type": "terminal_created"},  # 缺少 terminal_id
        )

        # 不应该有任何 send_json 调用（没有广播）
        received_broadcast = False
        for call in mock_client_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                received_broadcast = True

        assert not received_broadcast, "Should not broadcast when terminal_id is missing"
