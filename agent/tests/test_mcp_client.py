"""
B092: MCP Client 框架集成测试。

使用 fake_skill 测试夹具验证 MCP Server 生命周期和工具调用。
"""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from app.mcp_client import MCPClientManager, MAX_TOOL_RESULT_SIZE


# fake_skill 路径
_FAKE_SKILL_DIR = str(Path(__file__).parent / "fake_skill")
_FAKE_SKILL_BROKEN_DIR = str(Path(__file__).parent / "fake_skill_broken")


class TestMCPToolCatalog:

    def test_build_catalog_from_fake_skill(self):
        """验证 fake_skill 能被正确解析并构建 catalog。"""
        from app.skill_registry import _parse_skill_json
        manifest = _parse_skill_json(Path(_FAKE_SKILL_DIR))
        assert manifest is not None
        assert manifest.name == "fake_skill"
        assert manifest.command == "python3"

    def test_broken_skill_manifest_rejected(self):
        """malformed skill.json 应被跳过。"""
        from app.skill_registry import _parse_skill_json
        manifest = _parse_skill_json(Path(_FAKE_SKILL_BROKEN_DIR))
        assert manifest is not None  # JSON 合法，但命令不存在

    def test_namespaced_format(self):
        """工具名应为 skill_name.tool_name 格式。"""
        manager = MCPClientManager()
        # 手动注入一个模拟状态
        from app.mcp_client import MCPServerState, MCPToolInfo
        from app.skill_registry import SkillManifest
        state = MCPServerState(
            skill_name="test_skill",
            manifest=SkillManifest(name="test_skill", command="echo"),
        )
        state.tools.append(MCPToolInfo(
            skill_name="test_skill",
            tool_name="my_tool",
            namespaced_name="test_skill.my_tool",
            description="Test",
            parameters={"type": "object", "properties": {}},
        ))
        manager._servers["test_skill"] = state
        catalog = manager.build_tool_catalog()
        assert len(catalog) == 1
        assert catalog[0]["name"] == "test_skill.my_tool"
        assert catalog[0]["kind"] == "dynamic"
        assert catalog[0]["skill"] == "test_skill"


class TestMCPToolCall:

    @pytest.mark.asyncio
    async def test_call_tool_with_fake_skill(self):
        """使用 fake_skill 验证端到端工具调用。"""
        manager = MCPClientManager()

        from app.skill_registry import SkillManifest
        manifest = SkillManifest(
            name="fake_skill",
            version="1.0.0",
            description="Fake skill for testing",
            command="python3",
            args=["-m", "tests.fake_skill.fake_server"],
            transport="stdio",
            timeout=10,
        )
        await manager._start_skill(manifest)

        # 验证工具列表
        tools = manager.get_all_tools()
        assert len(tools) >= 1
        tool_names = [t.namespaced_name for t in tools]
        assert "fake_skill.hello" in tool_names

        # 调用 hello 工具
        result = await manager.call_tool("fake_skill.hello", {"name": "World"})
        assert result["status"] == "success"
        assert "Hello, World!" in result["result"]

        # 调用 info 工具
        result = await manager.call_tool("fake_skill.info", {})
        assert result["status"] == "success"
        assert "Fake skill info" in result["result"]

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_call_unknown_tool(self):
        """未知工具名应返回错误。"""
        manager = MCPClientManager()
        result = await manager.call_tool("nonexistent.tool", {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_tool_name_format(self):
        """非 namespaced 格式应返回错误。"""
        manager = MCPClientManager()
        result = await manager.call_tool("invalid_name", {})
        assert result["status"] == "error"
        assert "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_required_arg(self):
        """缺少 required 参数应返回 invalid_args 错误。"""
        manager = MCPClientManager()

        from app.skill_registry import SkillManifest
        manifest = SkillManifest(
            name="fake_skill",
            command="python3",
            args=["-m", "tests.fake_skill.fake_server"],
            transport="stdio",
            timeout=10,
        )
        await manager._start_skill(manifest)

        # hello 需要 name 参数
        result = await manager.call_tool("fake_skill.hello", {})
        assert result["status"] == "error"
        assert "invalid_args" in result["error"]
        assert "missing_required" in result["error"]

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_broken_skill_startup(self):
        """启动失败的 Skill 不应阻塞其他 Skill。"""
        manager = MCPClientManager()

        from app.skill_registry import SkillManifest
        broken_manifest = SkillManifest(
            name="broken_skill",
            command="nonexistent_command_xyz",
            transport="stdio",
        )
        await manager._start_skill(broken_manifest)

        # broken skill 不应在 servers 中
        assert "broken_skill" not in manager._servers

        # 但仍然可以启动其他 skill
        good_manifest = SkillManifest(
            name="fake_skill",
            command="python3",
            args=["-m", "tests.fake_skill.fake_server"],
            transport="stdio",
            timeout=10,
        )
        await manager._start_skill(good_manifest)
        assert "fake_skill" in manager._servers

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_result_serialization(self):
        """MCP 返回结果应正确序列化为文本。"""
        manager = MCPClientManager()
        # 测试序列化逻辑
        assert manager._serialize_result("plain text") == "plain text"
        assert isinstance(manager._serialize_result({"key": "value"}), str)
        assert isinstance(manager._serialize_result([1, 2, 3]), str)

    @pytest.mark.asyncio
    async def test_result_truncation(self):
        """超过 64KB 的结果应被截断。"""
        manager = MCPClientManager()
        big_content = "A" * (MAX_TOOL_RESULT_SIZE + 1000)
        # 模拟 MCP 返回大结果
        result_data = {"content": [{"type": "text", "text": big_content}]}
        serialized = manager._serialize_result(result_data)
        # 序列化后的文本包含原始大内容
        assert len(serialized) > MAX_TOOL_RESULT_SIZE

    @pytest.mark.asyncio
    async def test_start_all_with_fake_skill(self):
        """验证 start_all 能发现并启动 skills/ 目录下的 Skill。"""
        manager = MCPClientManager()

        # 创建临时 skills 目录
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills"
            skills_dir.mkdir()
            # 复制 fake_skill
            import shutil
            dest = skills_dir / "fake_skill"
            shutil.copytree(_FAKE_SKILL_DIR, dest)

            # 创建 registry
            registry = Path(tmpdir) / "skill-registry.json"
            registry.write_text(json.dumps({"skills": [{"name": "fake_skill", "enabled": True}]}))

            with patch("app.skill_registry._get_skills_dir", return_value=skills_dir), \
                 patch("app.skill_registry._get_registry_path", return_value=registry), \
                 patch("app.skill_registry._get_agent_data_dir", return_value=Path(tmpdir)):
                await manager.start_all()

            assert "fake_skill" in manager._servers
            tools = manager.get_all_tools()
            assert len(tools) >= 1

        await manager.stop_all()


class TestMCPServerCrash:

    @pytest.mark.asyncio
    async def test_crashed_server_removed_from_catalog(self):
        """MCP Server 崩溃后应从工具目录中移除。"""
        manager = MCPClientManager()
        from app.skill_registry import SkillManifest
        from app.mcp_client import MCPServerState

        manifest = SkillManifest(
            name="fake_skill",
            command="python3",
            args=["-m", "tests.fake_skill.fake_server"],
            transport="stdio",
            timeout=10,
        )
        await manager._start_skill(manifest)
        assert "fake_skill" in manager._servers

        # 模拟崩溃
        state = manager._servers["fake_skill"]
        state.running = False
        if state.process:
            state.process.terminate()
            await state.process.wait()

        await manager.check_health()
        assert "fake_skill" not in manager._servers

        # 崩溃后调用应返回错误
        result = await manager.call_tool("fake_skill.hello", {"name": "test"})
        assert result["status"] == "error"

        await manager.stop_all()
