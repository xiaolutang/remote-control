"""Compatibility alias for app.log_adapter."""
import sys

from app.core import log_adapter as _impl

sys.modules[__name__] = _impl
