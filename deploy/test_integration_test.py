import importlib.util
import ssl
import sys
import types
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("integration_test.py")
SPEC = importlib.util.spec_from_file_location("deploy_integration_test", MODULE_PATH)
integration_test = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(integration_test)


def test_ssl_context_for_localhost_wss_returns_unverified_context():
    context = integration_test.ssl_context_for("wss://localhost/rc")
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


@pytest.mark.asyncio
async def test_connect_agent_passes_ssl_context_for_localhost_wss(monkeypatch):
    captured = {"sent": []}

    class FakeWebSocket:
        def __init__(self):
            self._messages = iter([
                '{"type":"connected","session_id":"session-1","owner":"user1"}',
                '{"type":"pong"}',
            ])

        async def recv(self):
            return next(self._messages)

        async def send(self, message):
            captured["sent"].append(message)

    async def fake_connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeWebSocket()

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=fake_connect))
    monkeypatch.setattr(integration_test, "WS_URL", "wss://localhost/rc")

    ws, session_id = await integration_test.connect_agent("token-1")

    assert ws is not None
    assert session_id == "session-1"
    assert captured["url"] == "wss://localhost/rc/ws/agent"
    assert isinstance(captured["kwargs"]["ssl"], ssl.SSLContext)
    assert captured["sent"][0] == '{"type": "auth", "token": "token-1"}'
