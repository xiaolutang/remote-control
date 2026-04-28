"""Compatibility alias for app.pty_wrapper."""
import sys

from app.core import pty_wrapper as _impl

sys.modules[__name__] = _impl
