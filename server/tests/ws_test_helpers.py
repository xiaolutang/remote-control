import os
from types import SimpleNamespace


def trusted_proxy_scope():
    return {"scheme": "ws", "client": ("172.18.0.2", 443)}


def trusted_proxy_headers():
    return {"x-rc-forwarded-tls": os.environ["TRUSTED_PROXY_TLS_TOKEN"]}


def websocket_stub(*, headers=None, scope=None, client=None):
    return SimpleNamespace(
        headers=headers or {},
        scope=scope or {},
        client=client,
    )
