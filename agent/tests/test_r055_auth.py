"""
R055 补充测试：S302（cli.py PATH 集成）、S304（auth 耗时日志）、S305（auth 超时值+状态机）
"""
import inspect
import json
import os
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.security.auth_service import AuthService
from app.security.crypto import AgentCrypto


# ---------------------------------------------------------------------------
# 辅助：正确 mock aiohttp ClientSession
# ---------------------------------------------------------------------------

def _make_response(json_data, status=200):
    """创建一个可被 async with 使用的 mock response"""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    return resp


def _make_session(get_resp=None, post_resp=None):
    """创建一个 mock aiohttp.ClientSession，支持 async with 嵌套"""

    @asynccontextmanager
    async def _get_cm(*args, **kwargs):
        yield get_resp

    @asynccontextmanager
    async def _post_cm(*args, **kwargs):
        yield post_resp

    session = MagicMock()
    if get_resp is not None:
        session.get = MagicMock(side_effect=_get_cm)
    if post_resp is not None:
        session.post = MagicMock(side_effect=_post_cm)

    @asynccontextmanager
    async def _session_cm(*args, **kwargs):
        yield session

    return _session_cm


# ---------------------------------------------------------------------------
# S302: ensure_shell_path 集成测试
# ---------------------------------------------------------------------------

class TestEnsureShellPathIntegration:
    """验证 run 和 start 命令都调用了 ensure_shell_path()"""

    def test_run_calls_ensure_shell_path(self, tmp_path):
        from click.testing import CliRunner
        from app.cli import cli

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "server_url": "wss://test.example.com",
            "access_token": "valid-token",
        }))

        runner = CliRunner()
        with patch("app.cli.ensure_shell_path") as mock_esp, \
             patch("app.cli.setup_agent_logging"), \
             patch("app.cli.ensure_valid_token", new_callable=AsyncMock, return_value=(True, "token")), \
             patch("app.cli.WebSocketClient") as mock_ws:
            mock_ws.return_value.run = AsyncMock(side_effect=KeyboardInterrupt)
            mock_ws.return_value.stop = AsyncMock()
            runner.invoke(cli, ["--config", str(config_file), "run"])

        mock_esp.assert_called_once()

    def test_start_calls_ensure_shell_path(self, tmp_path):
        from click.testing import CliRunner
        from app.cli import cli

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"server_url": "wss://test.example.com"}))

        runner = CliRunner()
        with patch("app.cli.ensure_shell_path") as mock_esp, \
             patch("app.cli.setup_agent_logging"), \
             patch("app.cli.WebSocketClient") as mock_ws:
            mock_ws.return_value.run = AsyncMock(side_effect=KeyboardInterrupt)
            mock_ws.return_value.stop = AsyncMock()
            runner.invoke(cli, [
                "--config", str(config_file),
                "start", "--server", "wss://test.example.com", "--token", "test"
            ])

        mock_esp.assert_called_once()


# ---------------------------------------------------------------------------
# S304: auth 耗时日志测试
# ---------------------------------------------------------------------------

class TestAuthTimingLogs:
    """验证 auth 各步骤输出耗时日志"""

    @pytest.mark.asyncio
    async def test_verify_timing_logged_on_success(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response([], status=200)
        session_cm = _make_session(get_resp=resp)

        with patch("app.security.auth_service._log") as mock_log, \
             patch("aiohttp.ClientSession", side_effect=session_cm):
            result = await auth.verify_token("test-token")

        assert result is True
        mock_log.assert_called_once()
        assert "verify_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_verify_timing_logged_on_failure(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response([], status=401)
        session_cm = _make_session(get_resp=resp)

        with patch("app.security.auth_service._log") as mock_log, \
             patch("aiohttp.ClientSession", side_effect=session_cm):
            result = await auth.verify_token("bad-token")

        assert result is False
        mock_log.assert_called_once()
        assert "verify_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_refresh_timing_logged(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "access_token": "new", "refresh_token": "new_r"})
        session_cm = _make_session(post_resp=resp)

        with patch("app.security.auth_service._log") as mock_log, \
             patch("aiohttp.ClientSession", side_effect=session_cm):
            result = await auth.refresh_token("refresh-token")

        assert result.success
        mock_log.assert_called_once()
        assert "refresh_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_login_timing_logged(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "token": "access", "refresh_token": "refresh"})
        session_cm = _make_session(post_resp=resp)

        with patch("app.security.auth_service._log") as mock_log, \
             patch("app.security.auth_service.agent_crypto") as mock_crypto, \
             patch("aiohttp.ClientSession", side_effect=session_cm):
            mock_crypto.fetch_public_key = AsyncMock()
            mock_crypto.rsa_encrypt_b64.return_value = "encrypted"
            result = await auth.login("user", "pass")

        assert result.success
        log_calls = [c[0][0] for c in mock_log.call_args_list]
        assert any("login took" in msg for msg in log_calls)

    @pytest.mark.asyncio
    async def test_pubkey_timing_logged(self, tmp_path):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        # 生成真实 RSA 公钥 PEM
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        crypto = AgentCrypto(state_dir=str(tmp_path))
        resp = _make_response({
            "public_key_pem": public_pem,
            "fingerprint": "sha256:abc123"
        })
        session_cm = _make_session(get_resp=resp)

        with patch("app.security.crypto._log") as mock_log, \
             patch("aiohttp.ClientSession", side_effect=session_cm):
            await crypto.fetch_public_key("https://test.example.com")

        mock_log.assert_called_once()
        assert "fetch_public_key took" in mock_log.call_args[0][0]


# ---------------------------------------------------------------------------
# S305: auth 超时值 + 状态机测试
# ---------------------------------------------------------------------------

class TestAuthTimeoutValues:
    """验证 auth 超时值已降低"""

    def test_all_auth_timeouts_reduced(self):
        import app.security.auth_service as auth_mod
        import app.security.crypto as crypto_mod

        login_src = inspect.getsource(auth_mod.AuthService.login)
        assert "total=8" in login_src, "login timeout 应为 8s"

        refresh_src = inspect.getsource(auth_mod.AuthService.refresh_token)
        assert "total=8" in refresh_src, "refresh_token timeout 应为 8s"

        verify_src = inspect.getsource(auth_mod.AuthService.verify_token)
        assert "total=5" in verify_src, "verify_token timeout 应为 5s"

        pubkey_src = inspect.getsource(crypto_mod.AgentCrypto.fetch_public_key)
        assert "total=5" in pubkey_src, "fetch_public_key timeout 应为 5s"


class TestAuthFallbackStateMachine:
    """验证超时降低后 fallback 状态机不变"""

    @pytest.mark.asyncio
    async def test_verify_fail_then_refresh_ok(self):
        """verify 失败 → refresh 成功"""
        auth = AuthService("https://test.example.com")

        verify_resp = _make_response([], status=401)
        refresh_resp = _make_response({"success": True, "access_token": "new", "refresh_token": "new_r"})

        # verify
        with patch("aiohttp.ClientSession", side_effect=_make_session(get_resp=verify_resp)):
            assert await auth.verify_token("expired") is False

        # refresh
        with patch("aiohttp.ClientSession", side_effect=_make_session(post_resp=refresh_resp)):
            result = await auth.refresh_token("refresh-token")

        assert result.success

    @pytest.mark.asyncio
    async def test_refresh_fail_then_login_ok(self):
        """refresh 失败 → login 成功"""
        auth = AuthService("https://test.example.com")

        refresh_resp = _make_response({"success": False, "detail": "expired"})
        login_resp = _make_response({"success": True, "token": "new_access", "refresh_token": "new_refresh"})

        with patch("aiohttp.ClientSession", side_effect=_make_session(post_resp=refresh_resp)):
            refresh_result = await auth.refresh_token("bad-refresh")
            assert not refresh_result.success

        with patch("aiohttp.ClientSession", side_effect=_make_session(post_resp=login_resp)), \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.fetch_public_key = AsyncMock()
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            login_result = await auth.login("user", "pass")
            assert login_result.success

    @pytest.mark.asyncio
    async def test_login_failure_returns_error(self):
        """login 失败返回错误，不抛异常"""
        auth = AuthService("https://test.example.com")
        login_resp = _make_response({"success": False, "detail": "密码错误"}, status=401)

        with patch("aiohttp.ClientSession", side_effect=_make_session(post_resp=login_resp)), \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.fetch_public_key = AsyncMock()
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            result = await auth.login("user", "wrong-pass")

        assert not result.success
        assert "密码错误" in result.message
