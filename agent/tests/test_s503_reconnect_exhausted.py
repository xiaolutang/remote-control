"""
S521: Agent ReconnectExhausted 异常测试。

覆盖 S503 的异常类初始化、属性、字符串表示等边界场景。
"""
import pytest

from app.transport.websocket_client import ReconnectExhausted


class TestReconnectExhaustedInit:
    """ReconnectExhausted 初始化"""

    def test_default_reason(self):
        exc = ReconnectExhausted(retry_count=5, max_retries=10)
        assert exc.retry_count == 5
        assert exc.max_retries == 10
        assert exc.reason == "reconnect exhausted"

    def test_custom_reason(self):
        exc = ReconnectExhausted(
            retry_count=3,
            max_retries=3,
            reason="server unreachable",
        )
        assert exc.reason == "server unreachable"

    def test_zero_retries(self):
        exc = ReconnectExhausted(retry_count=0, max_retries=0)
        assert exc.retry_count == 0
        assert exc.max_retries == 0


class TestReconnectExhaustedStr:
    """字符串表示包含关键信息"""

    def test_str_contains_retry_info(self):
        exc = ReconnectExhausted(retry_count=7, max_retries=10)
        s = str(exc)
        assert "retries=7/10" in s

    def test_str_contains_custom_reason(self):
        exc = ReconnectExhausted(
            retry_count=5, max_retries=5, reason="auth failed"
        )
        s = str(exc)
        assert "auth failed" in s
        assert "retries=5/5" in s

    def test_str_format(self):
        exc = ReconnectExhausted(retry_count=3, max_retries=60)
        s = str(exc)
        assert s == "reconnect exhausted (retries=3/60)"


class TestReconnectExhaustedException:
    """作为 Exception 子类的行为"""

    def test_is_exception(self):
        exc = ReconnectExhausted(retry_count=1, max_retries=10)
        assert isinstance(exc, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ReconnectExhausted) as exc_info:
            raise ReconnectExhausted(
                retry_count=60, max_retries=60, reason="timeout"
            )
        assert exc_info.value.retry_count == 60
        assert exc_info.value.max_retries == 60

    def test_caught_by_base_exception(self):
        """能被 except Exception 捕获"""
        caught = False
        try:
            raise ReconnectExhausted(retry_count=5, max_retries=5)
        except Exception:
            caught = True
        assert caught

    def test_attributes_accessible_in_except(self):
        """except 块中能访问自定义属性"""
        with pytest.raises(ReconnectExhausted) as exc_info:
            raise ReconnectExhausted(
                retry_count=10, max_retries=10, reason="dns failure"
            )
        e = exc_info.value
        assert e.retry_count == 10
        assert e.max_retries == 10
        assert e.reason == "dns failure"


class TestReconnectExhaustedEdgeCases:
    """边界场景"""

    def test_large_retry_count(self):
        exc = ReconnectExhausted(retry_count=9999, max_retries=10000)
        assert exc.retry_count == 9999
        assert "retries=9999/10000" in str(exc)

    def test_reason_with_special_chars(self):
        exc = ReconnectExhausted(
            retry_count=1, max_retries=5,
            reason="连接被拒绝 (code=1006)",
        )
        assert "code=1006" in str(exc)
