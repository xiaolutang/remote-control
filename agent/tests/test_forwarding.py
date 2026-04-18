"""
消息转发测试
"""
import base64
import json

import pytest

from app.websocket_client import (
    AgentSnapshotManager,
    TerminalRuntimeManager,
    TerminalSpec,
    WebSocketClient,
)


class TestForwarding:
    """消息转发测试"""

    def test_base64_encoding(self):
        """Base64 编码正确"""
        test_data = "Hello 世界! \x1b[31mRed\x1b[0m"
        encoded = base64.b64encode(test_data.encode("utf-8")).decode("utf-8")
        decoded = base64.b64decode(encoded).decode("utf-8")
        assert decoded == test_data

    def test_message_format(self):
        """消息格式正确"""
        test_output = b"Test output"
        payload = base64.b64encode(test_output).decode("utf-8")

        message = {
            "type": "data",
            "payload": payload,
            "direction": "output",
        }

        # 验证消息格式
        assert message["type"] == "data"
        assert "payload" in message

        # 验证可以正确解码
        decoded = base64.b64decode(message["payload"]).decode("utf-8")
        assert decoded == "Test output"

    def test_resize_message(self):
        """resize 消息格式"""
        message = {
            "type": "resize",
            "rows": 40,
            "cols": 120,
        }

        assert message["type"] == "resize"
        assert message["rows"] == 40
        assert message["cols"] == 120

    def test_heartbeat_message(self):
        """心跳消息格式"""
        message = {"type": "ping"}

        assert message["type"] == "ping"

    def test_client_initialization(self):
        """客户端初始化"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
        )

        assert client.server_url == "wss://test.example.com"
        assert client.token == "test-token"
        assert client.command == "/bin/bash"
        assert client.auto_reconnect == True
        assert client.max_retries == 60
        assert client.runtime_manager is not None


class FakePTY:
    def __init__(self, command: str, args=None, config=None):
        self.command = command
        self.args = args or []
        self.config = config
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class TestTerminalRuntimeManager:
    def test_create_multiple_terminals_with_distinct_cwd(self):
        manager = TerminalRuntimeManager(pty_factory=FakePTY)

        manager.create_terminal(TerminalSpec(
            terminal_id="term-1",
            command="claude",
            args=["code"],
            cwd="/tmp/one",
            title="Claude / one",
        ))
        manager.create_terminal(TerminalSpec(
            terminal_id="term-2",
            command="/bin/bash",
            cwd="/tmp/two",
            title="Shell / two",
        ))

        terminals = manager.list_terminals()
        assert len(terminals) == 2
        assert terminals[0].cwd != terminals[1].cwd

    def test_close_one_terminal_does_not_remove_others(self):
        manager = TerminalRuntimeManager(pty_factory=FakePTY)

        manager.create_terminal(TerminalSpec(terminal_id="term-1", command="claude", title="one"))
        manager.create_terminal(TerminalSpec(terminal_id="term-2", command="/bin/bash", title="two"))

        closed = manager.close_terminal("term-1", reason="terminal_exit")

        assert closed["terminal_id"] == "term-1"
        assert closed["reason"] == "terminal_exit"
        assert manager.get_terminal("term-1") is None
        assert manager.get_terminal("term-2") is not None

    def test_build_terminal_created_event(self):
        manager = TerminalRuntimeManager(pty_factory=FakePTY)
        manager.create_terminal(TerminalSpec(
            terminal_id="term-1",
            command="claude",
            cwd="./",
            title="Claude / ai_rules",
        ))

        event = manager.build_terminal_created_event("term-1")

        assert event["type"] == "terminal_created"
        assert event["terminal_id"] == "term-1"
        assert event["cwd"] == "./"

class TestAgentSnapshotManager:
    def test_snapshot_payload_tracks_recent_output(self):
        manager = AgentSnapshotManager(snapshot_limit_bytes=8)
        spec = TerminalSpec(
            terminal_id="term-1",
            command="/bin/bash",
            title="shell",
        )
        manager.create_terminal(spec)

        manager.append_output("term-1", b"hello")
        manager.append_output("term-1", b" world")

        payload = manager.get_snapshot_payload("term-1")
        assert payload is not None
        assert base64.b64decode(payload) == b"lo world"

    def test_close_terminal_clears_snapshot_payload(self):
        manager = AgentSnapshotManager()
        spec = TerminalSpec(
            terminal_id="term-1",
            command="/bin/bash",
            title="shell",
        )
        manager.create_terminal(spec)
        manager.append_output("term-1", b"hello")

        manager.close_terminal("term-1")

        assert manager.get_snapshot_payload("term-1") is None

    def test_multiple_terminals_keep_isolated_snapshots(self):
        manager = AgentSnapshotManager()
        manager.create_terminal(TerminalSpec(terminal_id="term-1", command="/bin/bash", title="one"))
        manager.create_terminal(TerminalSpec(terminal_id="term-2", command="/bin/bash", title="two"))

        manager.append_output("term-1", b"alpha")
        manager.append_output("term-2", b"beta")

        assert base64.b64decode(manager.get_snapshot_payload("term-1")) == b"alpha"
        assert base64.b64decode(manager.get_snapshot_payload("term-2")) == b"beta"

    def test_recreate_terminal_does_not_inherit_old_snapshot(self):
        manager = AgentSnapshotManager()
        spec = TerminalSpec(terminal_id="term-1", command="/bin/bash", title="shell")
        manager.create_terminal(spec)
        manager.append_output("term-1", b"old-state")
        manager.close_terminal("term-1")

        manager.create_terminal(spec)

        assert manager.get_snapshot_payload("term-1") is None

    def test_snapshot_metadata_tracks_pty_and_active_buffer(self):
        manager = AgentSnapshotManager()
        spec = TerminalSpec(
            terminal_id="term-1",
            command="/bin/bash",
            title="shell",
            rows=24,
            cols=80,
        )
        manager.create_terminal(spec)

        manager.update_terminal_pty("term-1", 40, 120)
        manager.append_output("term-1", b"\x1b[?1049hhello")
        metadata = manager.get_snapshot_metadata("term-1")

        assert metadata == {
            "pty": {"rows": 40, "cols": 120},
            "active_buffer": "alt",
        }
