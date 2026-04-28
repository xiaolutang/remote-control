"""Compatibility alias for app.auth_service."""
import sys

from app.security import auth_service as _impl

sys.modules[__name__] = _impl
