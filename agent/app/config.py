"""Compatibility alias for app.config."""
import sys

from app.core import config as _impl

sys.modules[__name__] = _impl
