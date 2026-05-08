"""
S418: AgentMessageHandler 单元测试。

覆盖 dispatch、_handle_data、_handle_resize、_handle_create_terminal、
_handle_close_terminal、_handle_snapshot_request、_handle_execute_command、
_handle_lookup_knowledge、_handle_tool_call。
"""
import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.message_types import MessageType
from app.transport.agent_message_handler import AgentMessageHandler, _validate_terminal_input


# ---- Helpers ----

def _make_client():
    """创建 mock client，预置 runtime_manager / snapshot_manager / mcp_manager。"""
    client = MagicMock()
    client.pty = MagicMock()
    client.command = "/bin/bash"
    client._send_ws_message = AsyncMock()
    client._runtime_tasks = {}
    client.runtime_manager = MagicMock()
    client.snapshot_manager = MagicMock()
    client.mcp_manager = MagicMock()
    return client


def _make_handler(client=None):
    client = client or _make_client()
    return AgentMessageHandler(client), client


# ---- _validate_terminal_input ----

class TestValidateTerminalInput:
    def test_valid_command(self):
        assert _validate_terminal_input("/bin/bash", None, {}) is None

    def test_command_not_string(self):
        assert _validate_terminal_input(123, None, {}) is not None

    def test_empty_command(self):
        assert _validate_terminal_input("  ", None, {}) is not None

    def test_cwd_relative(self):
        assert _validate_terminal_input("ls", "relative/path", {}) is not None

    def test_cwd_not_string(self):
        assert _validate_terminal_input("ls", 42, {}) is not None

    def test_env_not_dict(self):
        assert _validate_terminal_input("ls", None, "bad") is not None

    def test_env_value_not_string(self):
        assert _validate_terminal_input("ls", None, {"K": 123}) is not None


# ---- dispatch ----

class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_data(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        await handler.dispatch({
            "type": MessageType.DATA,
            "terminal_id": "t1",
            "payload": base64.b64encode(b"hello").decode(),
        })
        terminal.write.assert_called_once_with(b"hello")

    @pytest.mark.asyncio
    async def test_dispatch_resize(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        await handler.dispatch({
            "type": MessageType.RESIZE,
            "terminal_id": "t1",
            "rows": 40,
            "cols": 120,
        })
        terminal.resize.assert_called_once_with(40, 120)

    @pytest.mark.asyncio
    async def test_dispatch_pong(self):
        handler, _ = _make_handler()
        # PONG is a no-op, should not raise
        await handler.dispatch({"type": MessageType.PONG})

    @pytest.mark.asyncio
    async def test_dispatch_unknown_type(self):
        handler, _ = _make_handler()
        # Unknown type should not raise
        await handler.dispatch({"type": "unknown_type"})


# ---- _handle_data ----

class TestHandleData:
    @pytest.mark.asyncio
    async def test_write_to_specific_terminal(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        await handler._handle_data({
            "terminal_id": "t1",
            "payload": base64.b64encode(b"input").decode(),
        })
        terminal.write.assert_called_once_with(b"input")
        client.runtime_manager.get_terminal.assert_called_once_with("t1")

    @pytest.mark.asyncio
    async def test_write_to_default_pty(self):
        handler, client = _make_handler()
        client.runtime_manager.get_terminal.return_value = None

        await handler._handle_data({
            "payload": base64.b64encode(b"input").decode(),
        })
        client.pty.write.assert_called_once_with(b"input")

    @pytest.mark.asyncio
    async def test_invalid_base64_falls_back_to_utf8(self):
        handler, client = _make_handler()
        client.runtime_manager.get_terminal.return_value = None

        await handler._handle_data({"payload": "plain text"})
        client.pty.write.assert_called_once_with(b"plain text")

    @pytest.mark.asyncio
    async def test_write_failure_logs(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        terminal.write.return_value = False
        client.runtime_manager.get_terminal.return_value = terminal

        # Should not raise
        await handler._handle_data({
            "terminal_id": "t1",
            "payload": base64.b64encode(b"x").decode(),
        })


# ---- _handle_resize ----

class TestHandleResize:
    @pytest.mark.asyncio
    async def test_resize_default_values(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        await handler._handle_resize({"terminal_id": "t1"})
        terminal.resize.assert_called_once_with(24, 80)

    @pytest.mark.asyncio
    async def test_resize_updates_snapshot(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal

        await handler._handle_resize({
            "terminal_id": "t1",
            "rows": 50,
            "cols": 160,
        })
        client.snapshot_manager.update_terminal_pty.assert_called_once_with("t1", 50, 160)

    @pytest.mark.asyncio
    async def test_resize_no_terminal(self):
        handler, client = _make_handler()
        client.runtime_manager.get_terminal.return_value = None

        # Should not raise
        await handler._handle_resize({"terminal_id": "nonexistent", "rows": 10, "cols": 10})


# ---- _handle_create_terminal ----

class TestHandleCreateTerminal:
    @pytest.mark.asyncio
    async def test_missing_terminal_id(self):
        handler, client = _make_handler()
        await handler._handle_create_terminal({"command": "/bin/bash"})
        client.runtime_manager.create_terminal.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure(self):
        handler, client = _make_handler()
        client.runtime_manager.build_terminal_closed_event.return_value = {"type": "terminal_closed"}

        await handler._handle_create_terminal({
            "terminal_id": "t1",
            "command": "",  # empty command → validation failure
        })
        client.runtime_manager.create_terminal.assert_not_called()
        client._send_ws_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_success(self):
        handler, client = _make_handler()
        runtime = MagicMock()
        client.runtime_manager.create_terminal.return_value = runtime
        client.runtime_manager.build_terminal_created_event.return_value = {"type": "terminal_created"}

        await handler._handle_create_terminal({
            "terminal_id": "t1",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "env": {"HOME": "/tmp"},
        })
        client.runtime_manager.create_terminal.assert_called_once()
        client.snapshot_manager.create_terminal.assert_called_once()
        client._send_ws_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_exception(self):
        handler, client = _make_handler()
        client.runtime_manager.create_terminal.side_effect = RuntimeError("boom")
        client.runtime_manager.build_terminal_closed_event.return_value = {"type": "terminal_closed"}

        await handler._handle_create_terminal({
            "terminal_id": "t1",
            "command": "/bin/bash",
        })
        client._send_ws_message.assert_called()


# ---- _handle_close_terminal ----

class TestHandleCloseTerminal:
    @pytest.mark.asyncio
    async def test_close_existing_terminal(self):
        handler, client = _make_handler()
        terminal = MagicMock()
        client.runtime_manager.get_terminal.return_value = terminal
        close_event = {"type": "terminal_closed"}
        client.runtime_manager.close_terminal.return_value = close_event

        await handler._handle_close_terminal({"terminal_id": "t1"})
        client.runtime_manager.close_terminal.assert_called_once()
        client.snapshot_manager.close_terminal.assert_called_once_with("t1")
        client._send_ws_message.assert_called_once_with(close_event)

    @pytest.mark.asyncio
    async def test_close_nonexistent_terminal(self):
        handler, client = _make_handler()
        client.runtime_manager.get_terminal.return_value = None

        await handler._handle_close_terminal({"terminal_id": "nonexistent"})
        client.runtime_manager.close_terminal.assert_not_called()


# ---- _handle_snapshot_request ----

class TestHandleSnapshotRequest:
    @pytest.mark.asyncio
    async def test_missing_fields(self):
        handler, client = _make_handler()
        await handler._handle_snapshot_request({"terminal_id": "t1"})
        client._send_ws_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapshot_success(self):
        handler, client = _make_handler()
        client.snapshot_manager.build_snapshot_data.return_value = {
            "payload": "base64data",
            "pty": {"rows": 24},
            "active_buffer": "main",
        }

        await handler._handle_snapshot_request({
            "terminal_id": "t1",
            "request_id": "r1",
        })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["type"] == MessageType.SNAPSHOT_DATA
        assert msg["request_id"] == "r1"


# ---- _handle_execute_command ----

class TestHandleExecuteCommand:
    @pytest.mark.asyncio
    async def test_rejected_command(self):
        handler, client = _make_handler()
        with patch("app.transport.agent_message_handler.validate_command", return_value=(False, "forbidden")):
            await handler._handle_execute_command({
                "request_id": "r1",
                "command": "rm -rf /",
            })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["exit_code"] == -1
        assert msg["stderr"] == "forbidden"

    @pytest.mark.asyncio
    async def test_invalid_shell_command(self):
        handler, client = _make_handler()
        with patch("app.transport.agent_message_handler.validate_command", return_value=(True, "")):
            await handler._handle_execute_command({
                "request_id": "r1",
                "command": "echo 'unclosed",
            })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["exit_code"] == -1
        assert "无效" in msg["stderr"]

    @pytest.mark.asyncio
    async def test_successful_command(self):
        handler, client = _make_handler()
        with patch("app.transport.agent_message_handler.validate_command", return_value=(True, "")):
            await handler._handle_execute_command({
                "request_id": "r1",
                "command": "echo hello",
                "timeout": 5,
            })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["type"] == MessageType.EXECUTE_COMMAND_RESULT
        assert msg["request_id"] == "r1"
        assert msg["exit_code"] == 0
        assert "hello" in msg["stdout"]


# ---- _handle_lookup_knowledge ----

class TestHandleLookupKnowledge:
    @pytest.mark.asyncio
    async def test_success(self):
        handler, client = _make_handler()
        with patch("app.transport.agent_message_handler.lookup_knowledge", return_value="结果"):
            await handler._handle_lookup_knowledge({
                "request_id": "r1",
                "query": "test",
            })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["type"] == MessageType.LOOKUP_KNOWLEDGE_RESULT
        assert msg["result"] == "结果"

    @pytest.mark.asyncio
    async def test_exception(self):
        handler, client = _make_handler()
        with patch("app.transport.agent_message_handler.lookup_knowledge", side_effect=RuntimeError("fail")):
            await handler._handle_lookup_knowledge({
                "request_id": "r1",
                "query": "test",
            })
        msg = client._send_ws_message.call_args[0][0]
        assert msg.get("error") == "fail"


# ---- _handle_tool_call ----

class TestHandleToolCall:
    @pytest.mark.asyncio
    async def test_builtin_tool_rejected(self):
        handler, client = _make_handler()
        await handler._handle_tool_call({
            "call_id": "c1",
            "tool_name": "execute_command",
            "arguments": {},
        })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["status"] == "error"
        assert "built-in" in msg["error"]

    @pytest.mark.asyncio
    async def test_mcp_tool_success(self):
        handler, client = _make_handler()
        client.mcp_manager.call_tool = AsyncMock(return_value={
            "status": "ok",
            "result": "data",
        })

        await handler._handle_tool_call({
            "call_id": "c1",
            "tool_name": "custom_tool",
            "arguments": {"key": "value"},
        })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["status"] == "ok"
        assert msg["result"] == "data"

    @pytest.mark.asyncio
    async def test_mcp_tool_exception(self):
        handler, client = _make_handler()
        client.mcp_manager.call_tool = AsyncMock(side_effect=RuntimeError("boom"))

        await handler._handle_tool_call({
            "call_id": "c1",
            "tool_name": "custom_tool",
            "arguments": {},
        })
        msg = client._send_ws_message.call_args[0][0]
        assert msg["status"] == "error"
        assert msg["error"] == "boom"
