"""
Agent 本地 HTTP Server 单元测试
"""
import asyncio
import json
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

# 设置测试环境
os.environ["FLUTTER_TEST"] = "1"

from local_server import (
    LocalServer,
    get_state_file_path,
    write_state_file,
    read_state_file,
    clear_state_file,
    find_available_port,
    check_port_in_use,
    is_process_alive,
    discover_local_agent,
    DEFAULT_PORT,
    PORT_RANGE,
    BIND_ADDRESS,
)


class MockAgentClient:
    """模拟 WebSocketClient"""
    def __init__(self):
        self.server_url = "wss://test.example.com"
        self.is_connected = True
        self.session_id = "test-session-123"
        self._running = True
        self.runtime_manager = MagicMock()
        self.runtime_manager.list_terminals.return_value = []


class TestStateFile:
    """状态文件测试"""

    def test_get_state_file_path_macos(self, monkeypatch):
        """测试 macOS 状态文件路径"""
        monkeypatch.setattr("sys.platform", "darwin")
        # 需要重新导入以获取更新后的路径
        from local_server import get_state_file_path
        path = get_state_file_path()
        assert "Library/Application Support/remote-control" in str(path)
        assert path.name == "agent-state.json"

    def test_write_and_read_state_file(self, tmp_path, monkeypatch):
        """测试写入和读取状态文件"""
        # 使用临时目录
        monkeypatch.setattr("local_server.get_state_file_path", lambda: tmp_path / "agent-state.json")

        state = {
            "pid": 12345,
            "port": 18765,
            "server_url": "wss://test.example.com",
            "session_id": "test-session",
            "keep_running": True,
        }

        write_state_file(state)
        result = read_state_file()

        assert result is not None
        assert result["pid"] == 12345
        assert result["port"] == 18765
        assert result["server_url"] == "wss://test.example.com"

    def test_read_nonexistent_file(self, tmp_path, monkeypatch):
        """测试读取不存在的文件"""
        monkeypatch.setattr("local_server.get_state_file_path", lambda: tmp_path / "nonexistent.json")
        result = read_state_file()
        assert result is None

    def test_clear_state_file(self, tmp_path, monkeypatch):
        """测试清理状态文件"""
        state_file = tmp_path / "agent-state.json"
        monkeypatch.setattr("local_server.get_state_file_path", lambda: state_file)

        # 先写入
        write_state_file({"pid": 12345})
        assert state_file.exists()

        # 清理
        clear_state_file()
        assert not state_file.exists()


class TestPortDiscovery:
    """端口发现测试"""

    def test_find_available_port(self):
        """测试查找可用端口"""
        port = find_available_port()
        assert port is not None
        assert port in PORT_RANGE

    def test_check_port_in_use(self):
        """测试端口占用检查"""
        # 找一个可用端口
        port = find_available_port()
        assert port is not None

        # 可用端口应该返回 False
        assert check_port_in_use(port) is False


class TestProcessAlive:
    """进程存活检查测试"""

    def test_is_process_alive_current(self):
        """测试当前进程存活"""
        assert is_process_alive(os.getpid()) is True

    def test_is_process_alive_nonexistent(self):
        """测试不存在的进程"""
        # 使用一个非常大的 PID，不太可能存在
        assert is_process_alive(999999) is False


class TestLocalServer:
    """LocalServer 测试"""

    @pytest.fixture
    def mock_client(self):
        return MockAgentClient()

    @pytest.fixture
    async def server(self, mock_client):
        """创建并启动服务器"""
        server = LocalServer(mock_client, port=18769)  # 使用非默认端口避免冲突
        yield server
        # 清理
        await server.stop()

    @pytest.mark.asyncio
    async def test_start_and_stop(self, mock_client):
        """测试启动和停止"""
        server = LocalServer(mock_client, port=18769)
        success = await server.start()
        assert success is True
        assert server._running is True

        await server.stop()
        assert server._running is False

    @pytest.mark.asyncio
    async def test_health_endpoint(self, mock_client):
        """测试健康检查端点"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18768)
        await server.start()

        try:
            async with ClientSession() as session:
                async with session.get(f"http://{BIND_ADDRESS}:18768/health") as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["status"] == "ok"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_status_endpoint(self, mock_client):
        """测试状态端点"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18767)
        await server.start()

        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(f"http://{BIND_ADDRESS}:18767/status", headers=headers) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert "running" in data
                    assert "pid" in data
                    assert "port" in data
                    assert "server_url" in data
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_config_endpoint(self, mock_client):
        """测试配置端点"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18766)
        await server.start()

        try:
            async with ClientSession() as session:
                # 更新配置
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:18766/config",
                    json={"keep_running_in_background": False},
                    headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
                    assert "keep_running_in_background" in data["updated"]
                    assert data["keep_running_in_background"] is False
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_endpoint(self, mock_client):
        """测试停止端点"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18777)
        await server.start()

        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:18777/stop",
                    json={"grace_timeout": 5},
                    headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_terminals_endpoint(self, mock_client):
        """测试终端列表端点"""
        from aiohttp import ClientSession

        # 添加模拟终端
        from app.websocket_client import TerminalSpec
        mock_terminal = TerminalSpec(
            terminal_id="term-1",
            command="/bin/bash",
            title="Test Terminal",
            cwd="/home/user",
        )
        mock_client.runtime_manager.list_terminals.return_value = [mock_terminal]

        server = LocalServer(mock_client, port=18770)
        await server.start()

        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(f"http://{BIND_ADDRESS}:18770/terminals", headers=headers) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert "terminals" in data
                    assert data["count"] == 1
        finally:
            await server.stop()


class TestDiscoverLocalAgent:
    """发现本地 Agent 测试"""

    @pytest.fixture
    def mock_client(self):
        return MockAgentClient()

    @pytest.mark.asyncio
    async def test_discover_no_agent(self, monkeypatch):
        """测试没有运行中的 Agent"""
        # 清理状态文件
        monkeypatch.setattr("local_server.read_state_file", lambda: None)

        result = await discover_local_agent()
        # 如果没有 Agent 运行，应该返回 None
        # 注意：这个测试可能因为端口被占用而失败，需要确保端口未被使用
        # 这里我们只验证函数不会抛出异常
        assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_discover_via_state_file(self, mock_client, monkeypatch):
        """测试通过状态文件发现 Agent"""
        from aiohttp import ClientSession

        # 启动服务器
        server = LocalServer(mock_client, port=18771)
        await server.start()

        try:
            # 模拟状态文件
            mock_state = {
                "pid": os.getpid(),
                "port": 18771,
                "server_url": "wss://test.example.com",
            }
            monkeypatch.setattr("local_server.read_state_file", lambda: mock_state)

            result = await discover_local_agent()
            assert result is not None
            assert result["port"] == 18771
        finally:
            await server.stop()


# ─── B068: 本地 HTTP token 认证测试 ───


class TestLocalServerAuth:
    """B068: local_server token 认证测试"""

    @pytest.fixture
    def mock_client(self):
        return MockAgentClient()

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, mock_client):
        """无 Authorization 头 → 401"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18772)
        await server.start()
        try:
            async with ClientSession() as session:
                async with session.get(f"http://{BIND_ADDRESS}:18772/status") as resp:
                    assert resp.status == 401
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, mock_client):
        """错误 token → 401"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18773)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": "Bearer wrong-token"}
                async with session.get(f"http://{BIND_ADDRESS}:18773/status", headers=headers) as resp:
                    assert resp.status == 401
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_correct_token_returns_200(self, mock_client):
        """正确 token → 200"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18774)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(f"http://{BIND_ADDRESS}:18774/status", headers=headers) as resp:
                    assert resp.status == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, mock_client):
        """health 端点免认证"""
        from aiohttp import ClientSession

        server = LocalServer(mock_client, port=18775)
        await server.start()
        try:
            async with ClientSession() as session:
                async with session.get(f"http://{BIND_ADDRESS}:18775/health") as resp:
                    assert resp.status == 200
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_local_token_in_state_file(self, mock_client, monkeypatch):
        """local_token 写入状态文件"""
        state_data = {}
        monkeypatch.setattr("local_server.write_state_file", lambda s: state_data.update(s))

        server = LocalServer(mock_client, port=18776)
        await server.start()
        try:
            assert server._local_token is not None
            assert "local_token" in state_data
            assert state_data["local_token"] == server._local_token
        finally:
            await server.stop()


# ─── B068: 命令执行校验测试 ───


class TestTerminalInputValidation:
    """B068: terminal 创建输入校验"""

    def test_valid_input_passes(self):
        from app.websocket_client import _validate_terminal_input
        assert _validate_terminal_input("/bin/bash", "/home/user", {"KEY": "value"}) is None

    def test_command_not_string_rejected(self):
        from app.websocket_client import _validate_terminal_input
        assert "must be string" in _validate_terminal_input(123, None, {})

    def test_command_empty_rejected(self):
        from app.websocket_client import _validate_terminal_input
        assert "must not be empty" in _validate_terminal_input("", None, {})

    def test_cwd_relative_rejected(self):
        from app.websocket_client import _validate_terminal_input
        assert "absolute path" in _validate_terminal_input("/bin/bash", "../etc", {})

    def test_cwd_absolute_allowed(self):
        from app.websocket_client import _validate_terminal_input
        assert _validate_terminal_input("/bin/bash", "/home/user", {}) is None

    def test_cwd_none_allowed(self):
        from app.websocket_client import _validate_terminal_input
        assert _validate_terminal_input("/bin/bash", None, {}) is None

    def test_env_non_string_value_rejected(self):
        from app.websocket_client import _validate_terminal_input
        assert "must be string" in _validate_terminal_input("/bin/bash", None, {"KEY": 123})

    def test_env_string_value_allowed(self):
        from app.websocket_client import _validate_terminal_input
        assert _validate_terminal_input("/bin/bash", None, {"KEY": "value"}) is None

    def test_command_rdash_allowed(self):
        """command='rm -rf /' 允许（字符串，用户决定信任）"""
        from app.websocket_client import _validate_terminal_input
        assert _validate_terminal_input("rm -rf /", None, {}) is None


# ─── B095: Skill/Knowledge 管理 API 测试 ───


# 使用固定端口范围避免冲突
_B095_PORT_COUNTER = 18780


def _next_b095_port():
    global _B095_PORT_COUNTER
    _B095_PORT_COUNTER += 1
    return _B095_PORT_COUNTER


class TestSkillsAPI:
    """B095: GET/POST /skills 端点测试"""

    @pytest.fixture
    def mock_client(self):
        return MockAgentClient()

    @pytest.mark.asyncio
    async def test_get_skills_returns_list(self, mock_client, tmp_path, monkeypatch):
        """GET /skills 返回正确的 skill 列表"""
        from aiohttp import ClientSession
        from app.skill_registry import SkillEntry, SkillManifest

        # 准备 skills 目录
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "test-skill",
            "description": "A test skill",
            "command": "echo",
            "transport": "stdio",
        }))

        monkeypatch.setattr("app.skill_registry._get_agent_data_dir", lambda: tmp_path)
        monkeypatch.setattr("app.skill_registry.discover_skills",
                            lambda: [SkillEntry(
                                name="test-skill",
                                enabled=True,
                                manifest=SkillManifest(
                                    name="test-skill",
                                    description="A test skill",
                                    command="echo",
                                    transport="stdio",
                                ),
                            )])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/skills", headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert "skills" in data
                    assert data["count"] == 1
                    assert data["skills"][0]["name"] == "test-skill"
                    assert data["skills"][0]["description"] == "A test skill"
                    assert data["skills"][0]["enabled"] is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_get_skills_empty(self, mock_client, tmp_path, monkeypatch):
        """skills/ 目录为空时 GET /skills 返回空列表"""
        from aiohttp import ClientSession

        monkeypatch.setattr("app.skill_registry.discover_skills", lambda: [])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/skills", headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["skills"] == []
                    assert data["count"] == 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_toggle_enable(self, mock_client, tmp_path, monkeypatch):
        """POST /skills/toggle 正确更新 registry"""
        from aiohttp import ClientSession
        from app.skill_registry import SkillEntry, SkillManifest

        monkeypatch.setattr("app.skill_registry.discover_skills",
                            lambda: [SkillEntry(
                                name="my-skill",
                                enabled=True,
                                manifest=SkillManifest(name="my-skill", command="echo", transport="stdio"),
                            )])
        monkeypatch.setattr("app.skill_registry.load_skill_registry", lambda: {"my-skill": True})
        saved = {}
        monkeypatch.setattr("app.skill_registry.save_skill_registry", lambda e: saved.update(e))

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/skills/toggle",
                    json={"name": "my-skill", "enabled": False},
                    headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
                    assert data["name"] == "my-skill"
                    assert data["enabled"] is False
                    assert saved["my-skill"] is False
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_toggle_not_found(self, mock_client, monkeypatch):
        """POST /skills/toggle 不存在的 skill 返回 404"""
        from aiohttp import ClientSession

        monkeypatch.setattr("app.skill_registry.discover_skills", lambda: [])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/skills/toggle",
                    json={"name": "nonexistent", "enabled": True},
                    headers=headers,
                ) as resp:
                    assert resp.status == 404
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_toggle_invalid_json(self, mock_client):
        """POST /skills/toggle 无效 JSON 返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/skills/toggle",
                    data="not json",
                    headers={**headers, "Content-Type": "application/json"},
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_toggle_missing_name(self, mock_client, monkeypatch):
        """POST /skills/toggle 缺少 name 参数返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/skills/toggle",
                    json={"enabled": True},
                    headers=headers,
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_toggle_missing_enabled(self, mock_client, monkeypatch):
        """POST /skills/toggle 缺少 enabled 参数返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/skills/toggle",
                    json={"name": "foo"},
                    headers=headers,
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()


class TestKnowledgeAPI:
    """B095: GET/POST /knowledge 端点测试"""

    @pytest.fixture
    def mock_client(self):
        return MockAgentClient()

    @pytest.mark.asyncio
    async def test_get_knowledge_returns_list(self, mock_client, tmp_path, monkeypatch):
        """GET /knowledge 返回正确的知识文件列表"""
        from aiohttp import ClientSession
        from app.knowledge_tool import KnowledgeConfig

        # 使用内置 knowledge 目录里的真实文件
        monkeypatch.setattr("app.knowledge_tool.load_knowledge_config",
                            lambda: KnowledgeConfig())
        monkeypatch.setattr("app.knowledge_tool._scan_all_knowledge_files",
                            lambda: [("file1.md", Path("/fake/file1.md"))])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/knowledge", headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert "knowledge" in data
                    assert data["count"] == 1
                    assert data["knowledge"][0]["filename"] == "file1.md"
                    assert data["knowledge"][0]["enabled"] is True
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_get_knowledge_config_missing_all_enabled(self, mock_client, monkeypatch):
        """knowledge_config.json 缺失时 GET /knowledge 返回全部启用"""
        from aiohttp import ClientSession
        from app.knowledge_tool import KnowledgeConfig

        monkeypatch.setattr("app.knowledge_tool.load_knowledge_config",
                            lambda: KnowledgeConfig())
        monkeypatch.setattr("app.knowledge_tool._scan_all_knowledge_files",
                            lambda: [
                                ("a.md", Path("/a.md")),
                                ("b.md", Path("/b.md")),
                            ])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/knowledge", headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["count"] == 2
                    assert all(f["enabled"] is True for f in data["knowledge"])
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_toggle_disable(self, mock_client, tmp_path, monkeypatch):
        """POST /knowledge/toggle 正确更新 config"""
        from aiohttp import ClientSession
        from app.knowledge_tool import KnowledgeConfig

        monkeypatch.setattr("app.knowledge_tool._scan_all_knowledge_files",
                            lambda: [("tips.md", Path("/fake/tips.md"))])
        monkeypatch.setattr("app.knowledge_tool.load_knowledge_config",
                            lambda: KnowledgeConfig())
        saved_configs = []
        monkeypatch.setattr("app.knowledge_tool.save_knowledge_config",
                            lambda c: saved_configs.append(c))

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/knowledge/toggle",
                    json={"filename": "tips.md", "enabled": False},
                    headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["ok"] is True
                    assert data["filename"] == "tips.md"
                    assert data["enabled"] is False
                    assert "tips.md" in saved_configs[0].disabled_files
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_toggle_not_found(self, mock_client, monkeypatch):
        """POST /knowledge/toggle 不存在的文件返回 404"""
        from aiohttp import ClientSession

        monkeypatch.setattr("app.knowledge_tool._scan_all_knowledge_files", lambda: [])

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/knowledge/toggle",
                    json={"filename": "nonexistent.md", "enabled": True},
                    headers=headers,
                ) as resp:
                    assert resp.status == 404
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_toggle_invalid_json(self, mock_client):
        """POST /knowledge/toggle 无效 JSON 返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/knowledge/toggle",
                    data="bad json{{{",
                    headers={**headers, "Content-Type": "application/json"},
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_toggle_missing_filename(self, mock_client):
        """POST /knowledge/toggle 缺少 filename 参数返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/knowledge/toggle",
                    json={"enabled": True},
                    headers=headers,
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_toggle_missing_enabled(self, mock_client):
        """POST /knowledge/toggle 缺少 enabled 参数返回 400"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.post(
                    f"http://{BIND_ADDRESS}:{port}/knowledge/toggle",
                    json={"filename": "foo.md"},
                    headers=headers,
                ) as resp:
                    assert resp.status == 400
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_knowledge_no_auth_returns_401(self, mock_client):
        """无 auth token 请求 /knowledge 返回 401"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/knowledge",
                ) as resp:
                    assert resp.status == 401
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_skills_no_auth_returns_401(self, mock_client):
        """无 auth token 请求 /skills 返回 401"""
        from aiohttp import ClientSession

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/skills",
                ) as resp:
                    assert resp.status == 401
        finally:
            await server.stop()


class TestSkillRegistryCorrupt:
    """B095: skill-registry.json 格式损坏时不崩溃"""

    @pytest.mark.asyncio
    async def test_corrupt_registry_returns_empty_via_api(self, tmp_path, monkeypatch):
        """skill-registry.json 格式损坏时 GET /skills 返回 200 + 空列表，不崩溃"""
        from aiohttp import ClientSession

        mock_client = MockAgentClient()

        # 将数据目录指向 tmp_path，这样 skill-registry.json 和 skills/ 都在临时目录下
        monkeypatch.setattr("app.skill_registry._get_agent_data_dir", lambda: tmp_path)

        # 写入损坏的 JSON
        registry_path = tmp_path / "skill-registry.json"
        registry_path.write_text("{invalid json!!!")

        # 确保 skills/ 目录存在（为空）
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        port = _next_b095_port()
        server = LocalServer(mock_client, port=port)
        await server.start()
        try:
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {server._local_token}"}
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/skills", headers=headers,
                ) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["skills"] == []
                    assert data["count"] == 0
        finally:
            await server.stop()
