"""Compatibility alias for app.crypto."""
import sys

from app.security import crypto as _impl

sys.modules[__name__] = _impl
