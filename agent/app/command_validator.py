"""Compatibility alias for app.command_validator."""
import sys

from app.security import command_validator as _impl

sys.modules[__name__] = _impl
