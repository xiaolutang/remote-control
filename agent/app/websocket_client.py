"""Compatibility alias for app.websocket_client."""
import sys

from app.transport import websocket_client as _impl

sys.modules[__name__] = _impl
