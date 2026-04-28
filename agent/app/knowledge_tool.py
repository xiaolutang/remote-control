"""Compatibility alias for app.knowledge_tool."""
import sys

from app.tools import knowledge_tool as _impl

sys.modules[__name__] = _impl
