"""测试 server/app/log_adapter.py"""
import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_adapter():
    """每个测试前重置适配层全局状态"""
    import app.log_adapter as mod
    mod._handler = None
    yield
    mod._handler = None


def test_init_logging_success():
    """SDK 正常初始化 → handler 非空"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
        import app.log_adapter as mod
        importlib.reload(mod)
        result = mod.init_logging(component="server")

    assert result is mock_handler
    mock_setup.assert_called_once()
    call_kwargs = mock_setup.call_args
    assert call_kwargs.kwargs["component"] == "server"
    assert call_kwargs.kwargs["service_name"] == "remote-control"


def test_init_logging_sdk_import_fails():
    """SDK import 失败 → 返回 None，不抛异常"""
    with patch.dict(sys.modules, {"log_service_sdk": None}):
        import app.log_adapter as mod
        importlib.reload(mod)
        result = mod.init_logging(component="server")

    assert result is None


def test_init_logging_idempotent():
    """重复调用 init_logging → 幂等，不重复创建 handler"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
        import app.log_adapter as mod
        importlib.reload(mod)
        r1 = mod.init_logging(component="server")
        r2 = mod.init_logging(component="server")

    assert r1 is r2
    assert mock_setup.call_count == 1


def test_close_logging_clears_handler():
    """close_logging → handler 清理并调用 close()"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
        import app.log_adapter as mod
        importlib.reload(mod)
        mod.init_logging(component="server")
        mod.close_logging()

    mock_handler.close.assert_called_once()
    assert mod._handler is None


def test_close_logging_without_init():
    """未初始化时调用 close_logging → 安全，不抛异常"""
    import app.log_adapter as mod
    mod.close_logging()  # 不应抛异常
    assert mod._handler is None


def test_env_vars_passed_to_sdk():
    """LOG_SERVICE_URL / LOG_LEVEL 正确传递给 SDK"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(os.environ, {"LOG_SERVICE_URL": "http://test:1234", "LOG_LEVEL": "DEBUG"}):
        with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
            import app.log_adapter as mod
            importlib.reload(mod)
            mod.init_logging(component="server")

    call_kwargs = mock_setup.call_args.kwargs
    assert call_kwargs["endpoint"] == "http://test:1234"
    assert call_kwargs["level"] == "DEBUG"


# ---------------------------------------------------------------------------
# 接线测试：验证 __init__.py 真正调用了适配层
# ---------------------------------------------------------------------------

def test_init_imports_adapter():
    """接线：__init__.py import 了 log_adapter 的 init_logging 和 close_logging"""
    import app.__init__ as init_mod
    assert hasattr(init_mod, "init_logging")
    assert hasattr(init_mod, "close_logging")


def test_lifespan_calls_adapter():
    """接线：lifespan 中调用 init_logging(component='server') 和 close_logging()"""
    from unittest.mock import call
    with patch("app.__init__.init_logging") as mock_init, \
         patch("app.__init__.close_logging") as mock_close, \
         patch("app.__init__._stale_agent_ttl_checker"), \
         patch("app.http_client.close_shared_http_client", new_callable=lambda: AsyncMock()):
        from app.__init__ import lifespan, app
        from fastapi.testclient import TestClient
        # 用 TestClient 触发 lifespan
        with TestClient(app):
            pass
        mock_init.assert_called_with(component="server")
        mock_close.assert_called_once()


def test_init_does_not_import_sdk():
    """接线：__init__.py 不直接 import log_service_sdk"""
    import inspect
    import app.__init__ as init_mod
    source = inspect.getsource(init_mod)
    assert "from log_service_sdk" not in source
    assert "import log_service_sdk" not in source


# 需要 AsyncMock
from unittest.mock import AsyncMock
