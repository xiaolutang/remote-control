"""Compatibility alias for app.skill_registry."""
import sys

from app.tools import skill_registry as _impl

sys.modules[__name__] = _impl
