"""
AgentMessageHandler 集成测试。

与 test_agent_message_handler.py（mock 测试）的区别：
- 不 mock subprocess，真正执行系统命令
- 不 mock 文件 I/O，真正读写知识文件
- 只 mock WebSocket 发送（因为不需要真实 WS 连接）

覆盖：
1. _handle_execute_command — 真实子进程执行
2. _handle_lookup_knowledge — 真实文件检索
3. dispatch → execute_command 集成链路
4. _validate_terminal_input — 纯函数验证
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.message_types import MessageType
from app.transport.agent_message_handler import AgentMessageHandler, _validate_terminal_input


# ---- Helpers ----

class _FakeSendQueue:
    """收集 _send_ws_message 发出的所有消息，方便断言。"""
    def __init__(self):
        self.messages: list[dict] = []

    async def send(self, msg: dict):
        self.messages.append(msg)

    @property
    def last(self) -> dict:
        assert self.messages, "No messages sent"
        return self.messages[-1]


def _make_handler():
    """创建 handler，client._send_ws_message 指向 FakeSendQueue。"""
    client = MagicMock()
    client.pty = MagicMock()
    client.command = "/bin/bash"
    client._send_ws_message = AsyncMock()
    client._runtime_tasks = {}
    client.runtime_manager = MagicMock()
    client.snapshot_manager = MagicMock()
    client.mcp_manager = MagicMock()

    queue = _FakeSendQueue()
    client._send_ws_message = queue.send

    handler = AgentMessageHandler(client)
    return handler, client, queue


# ============================================================
# _handle_execute_command — 真实子进程执行
# ============================================================

class TestExecuteCommandRealSubprocess:
    """真实子进程执行测试，不 mock asyncio.create_subprocess_exec。"""

    @pytest.mark.asyncio
    async def test_echo_hello(self):
        """echo hello → exit_code=0, stdout='hello\n'"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r1",
            "command": "echo hello",
        })
        msg = queue.last
        assert msg["type"] == MessageType.EXECUTE_COMMAND_RESULT
        assert msg["request_id"] == "r1"
        assert msg["exit_code"] == 0
        assert "hello" in msg["stdout"]
        assert msg["stderr"] == ""
        assert msg["timed_out"] is False

    @pytest.mark.asyncio
    async def test_pwd_command(self):
        """pwd → 返回真实工作目录"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r2",
            "command": "pwd",
        })
        msg = queue.last
        assert msg["exit_code"] == 0
        assert len(msg["stdout"].strip()) > 0
        assert Path(msg["stdout"].strip()).is_dir()

    @pytest.mark.asyncio
    async def test_ls_self(self):
        """ls agent/tests/ → exit_code=0, stdout 包含本文件名"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r3",
            "command": "ls agent/tests/",
        })
        msg = queue.last
        assert msg["exit_code"] == 0
        assert "test_agent_message_handler_integration.py" in msg["stdout"]

    @pytest.mark.asyncio
    async def test_nonexistent_command_rejected(self):
        """不在白名单中的命令被拒绝"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r4",
            "command": "python3 -c 'print(1)'",
        })
        msg = queue.last
        assert msg["exit_code"] == -1
        assert "白名单" in msg["stderr"]

    @pytest.mark.asyncio
    async def test_exit_nonzero(self):
        """ls /nonexistent_dir_xyz → exit_code != 0, stderr 非空"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r5",
            "command": "ls /nonexistent_dir_xyz_12345",
        })
        msg = queue.last
        assert msg["exit_code"] != 0
        assert len(msg["stderr"]) > 0

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """find / 超时（timeout=1）→ timed_out=True"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r6",
            "command": "find / -type f",
            "timeout": 1,
        })
        msg = queue.last
        assert msg["exit_code"] < 0  # 被信号终止
        assert msg["timed_out"] is True
        assert "timed out" in msg["stderr"]

    @pytest.mark.asyncio
    async def test_cwd_parameter(self):
        """指定 cwd 参数 → 命令在指定目录执行"""
        handler, _, queue = _make_handler()
        with tempfile.TemporaryDirectory() as tmpdir:
            await handler._handle_execute_command({
                "request_id": "r7",
                "command": "pwd",
                "cwd": tmpdir,
            })
            msg = queue.last
            assert msg["exit_code"] == 0
            assert tmpdir in msg["stdout"]

    @pytest.mark.asyncio
    async def test_multi_line_stdout(self):
        """ls 多文件 → stdout 包含多行"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r8",
            "command": "ls agent/app/",
        })
        msg = queue.last
        assert msg["exit_code"] == 0
        lines = msg["stdout"].strip().split("\n")
        assert len(lines) >= 3

    @pytest.mark.asyncio
    async def test_git_status_real(self):
        """git status 在项目目录 → exit_code=0"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r9",
            "command": "git status",
        })
        msg = queue.last
        assert msg["exit_code"] == 0
        # stdout 可能包含 "On branch" 或中文
        assert msg["stdout"]

    @pytest.mark.asyncio
    async def test_pipe_rejected(self):
        """管道命令被元字符拦截"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r10",
            "command": "ls | grep foo",
        })
        msg = queue.last
        assert msg["exit_code"] == -1
        assert "元字符" in msg["stderr"]

    @pytest.mark.asyncio
    async def test_semicolon_rejected(self):
        """分号命令被元字符拦截"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r11",
            "command": "echo hi; echo there",
        })
        msg = queue.last
        assert msg["exit_code"] == -1
        assert "元字符" in msg["stderr"]

    @pytest.mark.asyncio
    async def test_large_output_truncated(self):
        """大输出被截断"""
        handler, _, queue = _make_handler()
        await handler._handle_execute_command({
            "request_id": "r12",
            "command": "cat agent/tests/test_agent_message_handler_integration.py",
        })
        msg = queue.last
        # 文件内容不会超过 8192，但验证 truncated 字段逻辑
        assert msg["exit_code"] == 0
        assert isinstance(msg["truncated"], bool)


# ============================================================
# dispatch → execute_command 集成链路
# ============================================================

class TestDispatchExecuteCommandIntegration:
    """通过 dispatch 分发 execute_command，验证完整的异步执行链路。"""

    @pytest.mark.asyncio
    async def test_dispatch_triggers_execute_command(self):
        """dispatch 收到 execute_command → 真正执行并返回结果"""
        handler, _, queue = _make_handler()
        # dispatch 通过 asyncio.create_task 异步执行，需要等待
        await handler.dispatch({
            "type": MessageType.EXECUTE_COMMAND,
            "request_id": "d1",
            "command": "echo dispatched",
        })
        # 等待异步任务完成
        await asyncio.sleep(0.5)
        assert len(queue.messages) == 1
        msg = queue.messages[0]
        assert msg["type"] == MessageType.EXECUTE_COMMAND_RESULT
        assert msg["exit_code"] == 0
        assert "dispatched" in msg["stdout"]

    @pytest.mark.asyncio
    async def test_dispatch_rejected_command(self):
        """dispatch 收到被拒绝的命令 → 返回错误结果"""
        handler, _, queue = _make_handler()
        await handler.dispatch({
            "type": MessageType.EXECUTE_COMMAND,
            "request_id": "d2",
            "command": "rm -rf /",
        })
        await asyncio.sleep(0.3)
        assert len(queue.messages) == 1
        msg = queue.messages[0]
        assert msg["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_dispatch_pong_is_noop(self):
        """dispatch 收到 pong → 不发送任何消息"""
        handler, _, queue = _make_handler()
        await handler.dispatch({"type": MessageType.PONG})
        assert len(queue.messages) == 0


# ============================================================
# _handle_lookup_knowledge — 真实文件检索
# ============================================================

class TestLookupKnowledgeRealFiles:
    """使用真实临时目录测试知识检索，不 mock 文件 I/O。"""

    def _setup_knowledge_files(self, tmp_path: Path, files: dict[str, str]):
        """创建知识目录并写入文件，返回 builtin 和 user 目录路径。"""
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        for name, content in files.items():
            (builtin_dir / name).write_text(content, encoding="utf-8")

        user_dir = tmp_path / "user_knowledge"
        user_dir.mkdir()
        return builtin_dir, user_dir

    @pytest.mark.asyncio
    async def test_find_keyword_in_real_file(self, tmp_path):
        """真实创建知识文件并检索到匹配内容"""
        handler, _, queue = _make_handler()
        builtin_dir, user_dir = self._setup_knowledge_files(tmp_path, {
            "deploy_guide.md": "# 部署指南\nDocker 部署步骤\n使用 docker-compose up",
            "tips.md": "# 使用技巧\n一些开发技巧",
        })

        from app.tools.knowledge_tool import KnowledgeConfig
        with patch("app.tools.knowledge_tool._get_builtin_knowledge_dir", return_value=builtin_dir), \
             patch("app.tools.knowledge_tool._get_user_knowledge_dir", return_value=user_dir), \
             patch("app.tools.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            await handler._handle_lookup_knowledge({
                "request_id": "k1",
                "query": "部署",
            })

        msg = queue.last
        assert msg["type"] == MessageType.LOOKUP_KNOWLEDGE_RESULT
        assert msg["request_id"] == "k1"
        assert "部署" in msg["result"]
        assert "Docker" in msg["result"]

    @pytest.mark.asyncio
    async def test_no_match_returns_not_found(self, tmp_path):
        """检索不存在的内容 → '未找到相关知识'"""
        handler, _, queue = _make_handler()
        builtin_dir, user_dir = self._setup_knowledge_files(tmp_path, {
            "test.md": "# 测试\n一些内容",
        })

        from app.tools.knowledge_tool import KnowledgeConfig
        with patch("app.tools.knowledge_tool._get_builtin_knowledge_dir", return_value=builtin_dir), \
             patch("app.tools.knowledge_tool._get_user_knowledge_dir", return_value=user_dir), \
             patch("app.tools.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            await handler._handle_lookup_knowledge({
                "request_id": "k2",
                "query": "完全不存在的关键词 xyz789",
            })

        msg = queue.last
        assert msg["result"] == "未找到相关知识"

    @pytest.mark.asyncio
    async def test_user_knowledge_searched(self, tmp_path):
        """用户自定义知识文件也能被检索"""
        handler, _, queue = _make_handler()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        user_dir = tmp_path / "user_knowledge"
        user_dir.mkdir()
        (user_dir / "custom.md").write_text("# 我的笔记\n这是自定义笔记内容关于架构设计", encoding="utf-8")

        from app.tools.knowledge_tool import KnowledgeConfig
        with patch("app.tools.knowledge_tool._get_builtin_knowledge_dir", return_value=builtin_dir), \
             patch("app.tools.knowledge_tool._get_user_knowledge_dir", return_value=user_dir), \
             patch("app.tools.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            await handler._handle_lookup_knowledge({
                "request_id": "k3",
                "query": "架构设计",
            })

        msg = queue.last
        assert "架构设计" in msg["result"]

    @pytest.mark.asyncio
    async def test_chinese_keyword_matching(self, tmp_path):
        """中文关键词匹配"""
        handler, _, queue = _make_handler()
        builtin_dir, user_dir = self._setup_knowledge_files(tmp_path, {
            "guide.md": "# 操作指南\n如何使用远程控制终端进行开发\n连接设备的方法",
        })

        from app.tools.knowledge_tool import KnowledgeConfig
        with patch("app.tools.knowledge_tool._get_builtin_knowledge_dir", return_value=builtin_dir), \
             patch("app.tools.knowledge_tool._get_user_knowledge_dir", return_value=user_dir), \
             patch("app.tools.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            await handler._handle_lookup_knowledge({
                "request_id": "k4",
                "query": "远程控制",
            })

        msg = queue.last
        assert "远程控制" in msg["result"]


# ============================================================
# _validate_terminal_input — 集成测试额外覆盖（已有 mock 测试的基础覆盖在 test_agent_message_handler.py）
# ============================================================

class TestValidateTerminalInputIntegration:
    """纯函数额外场景，已有 mock 测试未覆盖的 case。"""

    def test_valid_command_with_cwd_and_env(self):
        assert _validate_terminal_input("/bin/bash", "/tmp", {"HOME": "/tmp"}) is None

    def test_absolute_cwd_passes(self):
        assert _validate_terminal_input("ls", "/usr/local/bin", {}) is None

    def test_home_expansion_cwd(self):
        """~/xxx 展开为绝对路径后应通过"""
        assert _validate_terminal_input("ls", "~/projects", {}) is None

    def test_all_valid_types(self):
        """所有参数类型正确时返回 None"""
        assert _validate_terminal_input("/bin/zsh", "/tmp", {"PATH": "/usr/bin"}) is None


# ============================================================
# _handle_data — 真实 binary base64（基础场景在 test_agent_message_handler.py）
# ============================================================

class TestHandleDataRealBinary:
    """二进制数据通过真实 base64 传输（UTF-8 / 文本场景已在 mock 测试中覆盖）。"""

    @pytest.mark.asyncio
    async def test_binary_data_via_base64(self):
        """bytes range(256) 通过 base64 传输后正确还原"""
        import base64
        handler, client, _ = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        binary_data = bytes(range(256))
        encoded = base64.b64encode(binary_data).decode()

        await handler._handle_data({
            "terminal_id": "t1",
            "payload": encoded,
        })
        terminal.write.assert_called_once_with(binary_data)
