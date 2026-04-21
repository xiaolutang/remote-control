from app.ws_auth import is_secure_websocket_transport
from tests.ws_test_helpers import trusted_proxy_headers, trusted_proxy_scope, websocket_stub


def _websocket(*, headers=None, scope=None, client=None):
    return websocket_stub(headers=headers, scope=scope, client=client)


def test_is_secure_websocket_transport_accepts_secure_scope_scheme():
    websocket = _websocket(scope={"scheme": "wss"})
    assert is_secure_websocket_transport(websocket) is True


def test_is_secure_websocket_transport_accepts_trusted_proxy_tls_marker():
    websocket = _websocket(
        headers=trusted_proxy_headers(),
        scope=trusted_proxy_scope(),
    )
    assert is_secure_websocket_transport(websocket) is True


def test_is_secure_websocket_transport_accepts_mixed_case_proxy_tls_token(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_TLS_TOKEN", "AbC123XyZ")
    websocket = _websocket(
        headers={"x-rc-forwarded-tls": "AbC123XyZ"},
        scope={"scheme": "ws", "client": ("172.18.0.2", 12345)},
    )
    assert is_secure_websocket_transport(websocket) is True


def test_is_secure_websocket_transport_rejects_wrong_case_proxy_tls_token(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_TLS_TOKEN", "AbC123XyZ")
    websocket = _websocket(
        headers={"x-rc-forwarded-tls": "abc123xyz"},
        scope={"scheme": "ws", "client": ("172.18.0.2", 12345)},
    )
    assert is_secure_websocket_transport(websocket) is False


def test_is_secure_websocket_transport_rejects_spoofed_tls_marker_without_secret():
    websocket = _websocket(
        headers={"x-rc-forwarded-tls": "wss"},
        scope={"scheme": "ws", "client": ("8.8.8.8", 12345)},
    )
    assert is_secure_websocket_transport(websocket) is False


def test_is_secure_websocket_transport_rejects_private_network_spoof_without_secret():
    websocket = _websocket(
        headers={"x-rc-forwarded-tls": "wss"},
        scope=trusted_proxy_scope(),
    )
    assert is_secure_websocket_transport(websocket) is False


def test_is_secure_websocket_transport_rejects_generic_forwarded_proto_header():
    websocket = _websocket(
        headers={"x-forwarded-proto": "https"},
        scope=trusted_proxy_scope(),
    )
    assert is_secure_websocket_transport(websocket) is False


def test_is_secure_websocket_transport_rejects_plain_ws_without_tls_signals():
    websocket = _websocket(
        headers={"x-rc-forwarded-tls": "off"},
        scope={"scheme": "ws"},
    )
    assert is_secure_websocket_transport(websocket) is False
