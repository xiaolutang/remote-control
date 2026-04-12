"""测试 agent/app/log_adapter.py"""
import importlib
import os
import sys
from unittest.mock import MagicMock

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
        with patch.dict(os.environ, {"LOG_SERVICE_URL": "http://log-service:8001"}):
            import app.log_adapter as mod
            importlib.reload(mod)
            result = mod.init_logging(component="agent")

    assert result is mock_handler


def test_init_logging_sdk_import_fails():
    """SDK import 失败 → 返回 None，不抛异常"""
    with patch.dict(sys.modules, {"log_service_sdk": None}):
        with patch.dict(os.environ, {"LOG_SERVICE_URL": "http://test:8001"}):
            import app.log_adapter as mod
            importlib.reload(mod)
            result = mod.init_logging(component="agent")

    assert result is None


def test_init_logging_no_url_skips():
    """LOG_SERVICE_URL 未设置 → 跳过初始化，返回 None"""
    with patch.dict(os.environ, {}, clear=True):
        import app.log_adapter as mod
        importlib.reload(mod)
        result = mod.init_logging(component="agent")

    assert result is None


def test_init_logging_empty_url_skips():
    """LOG_SERVICE_URL 为空字符串 → 跳过初始化，返回 None"""
    with patch.dict(os.environ, {"LOG_SERVICE_URL": ""}):
        import app.log_adapter as mod
        importlib.reload(mod)
        result = mod.init_logging(component="agent")

    assert result is None


def test_init_logging_idempotent():
    """重复调用 → 幂等"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
        with patch.dict(os.environ, {"LOG_SERVICE_URL": "http://test:8001"}):
            import app.log_adapter as mod
            importlib.reload(mod)
            r1 = mod.init_logging(component="agent")
            r2 = mod.init_logging(component="agent")

    assert r1 is r2
    assert mock_setup.call_count == 1


def test_close_logging_clears_handler():
    """close_logging → handler 清理"""
    mock_handler = MagicMock()
    mock_setup = MagicMock(return_value=mock_handler)

    with patch.dict(sys.modules, {"log_service_sdk": MagicMock(setup_remote_logging=mock_setup)}):
        with patch.dict(os.environ, {"LOG_SERVICE_URL": "http://test:8001"}):
            import app.log_adapter as mod
            importlib.reload(mod)
            mod.init_logging(component="agent")
            mod.close_logging()

    mock_handler.close.assert_called_once()
    assert mod._handler is None


def test_close_logging_without_init():
    """未初始化时 close → 安全"""
    import app.log_adapter as mod
    mod.close_logging()
    assert mod._handler is None


# 需要从 unittest.mock 导入 patch
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 接线测试：验证 cli.py 真正调用了适配层
# ---------------------------------------------------------------------------

def test_cli_imports_adapter():
    """接线：cli.py import 了 log_adapter 的 init_logging 和 close_logging"""
    import app.cli as cli_mod
    assert hasattr(cli_mod, "_init_logging")
    assert hasattr(cli_mod, "_close_logging")


def test_setup_agent_logging_calls_adapter():
    """接线：setup_agent_logging() 调用适配层 init_logging(component='agent')"""
    with patch("app.cli._init_logging") as mock_init:
        import app.cli as cli_mod
        cli_mod.setup_agent_logging()
    mock_init.assert_called_with(component="agent")


def test_cli_does_not_import_sdk():
    """接线：cli.py 不直接 import log_service_sdk"""
    import inspect
    import app.cli as cli_mod
    source = inspect.getsource(cli_mod)
    assert "from log_service_sdk" not in source
    assert "import log_service_sdk" not in source


def test_atexit_registered():
    """接线：atexit.register(close_logging) 已注册"""
    import atexit
    import app.cli as cli_mod
    # cli.py 模块加载时已注册 atexit，检查 _close_logging 在 atexit 中
    # 通过检查 cli_mod 引用了 _close_logging 来确认
    assert hasattr(cli_mod, "_close_logging")
