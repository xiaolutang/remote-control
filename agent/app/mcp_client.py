"""Compatibility alias for app.mcp_client."""
import sys

from app.tools import mcp_client as _impl

sys.modules[__name__] = _impl
