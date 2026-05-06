"""
R055 + R056 测试：S302（cli.py PATH 集成）、S304（auth 耗时日志）、S305（auth 超时值+状态机）
S401（共享 ClientSession + has_public_key 守卫）
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


def _make_mock_session(get_resp=None, post_resp=None):
    """创建一个 mock aiohttp.ClientSession 对象，支持 .get()/.post() 的 async with"""

    @asynccontextmanager
    async def _get_cm(*args, **kwargs):
        yield get_resp

    @asynccontextmanager
    async def _post_cm(*args, **kwargs):
        yield post_resp

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    if get_resp is not None:
        session.get = MagicMock(side_effect=_get_cm)
    if post_resp is not None:
        session.post = MagicMock(side_effect=_post_cm)
    return session


def _make_session_factory(session):
    """创建 async with 兼容的 factory（用于 patch side_effect）"""
    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield session
    return _cm


def _inject_session(auth: AuthService, session: MagicMock) -> None:
    """向 AuthService 注入 mock session（模拟懒加载已触发）"""
    auth._session = session


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
        _inject_session(auth, _make_mock_session(get_resp=resp))

        with patch("app.security.auth_service._log") as mock_log:
            result = await auth.verify_token("test-token")

        assert result is True
        mock_log.assert_called_once()
        assert "verify_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_verify_timing_logged_on_failure(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response([], status=401)
        _inject_session(auth, _make_mock_session(get_resp=resp))

        with patch("app.security.auth_service._log") as mock_log:
            result = await auth.verify_token("bad-token")

        assert result is False
        mock_log.assert_called_once()
        assert "verify_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_refresh_timing_logged(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "access_token": "new", "refresh_token": "new_r"})
        _inject_session(auth, _make_mock_session(post_resp=resp))

        with patch("app.security.auth_service._log") as mock_log:
            result = await auth.refresh_token("refresh-token")

        assert result.success
        mock_log.assert_called_once()
        assert "refresh_token took" in mock_log.call_args[0][0]

    @pytest.mark.asyncio
    async def test_login_timing_logged(self):
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "token": "access", "refresh_token": "refresh"})
        _inject_session(auth, _make_mock_session(post_resp=resp))

        with patch("app.security.auth_service._log") as mock_log, \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
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
        mock_session = _make_mock_session(get_resp=resp)
        session_factory = _make_session_factory(mock_session)

        with patch("app.security.crypto._log") as mock_log, \
             patch("aiohttp.ClientSession", side_effect=session_factory):
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

        # 共享同一 mock session，先 get 返回 401，再 post 返回 refresh ok
        verify_resp = _make_response([], status=401)
        refresh_resp = _make_response({"success": True, "access_token": "new", "refresh_token": "new_r"})
        session = _make_mock_session(get_resp=verify_resp, post_resp=refresh_resp)
        _inject_session(auth, session)

        assert await auth.verify_token("expired") is False
        result = await auth.refresh_token("refresh-token")
        assert result.success

    @pytest.mark.asyncio
    async def test_refresh_fail_then_login_ok(self):
        """refresh 失败 → login 成功"""
        auth = AuthService("https://test.example.com")

        refresh_resp = _make_response({"success": False, "detail": "expired"})
        login_resp = _make_response({"success": True, "token": "new_access", "refresh_token": "new_refresh"})
        session = _make_mock_session(post_resp=MagicMock(
            side_effect=[
                # 第一次 post: refresh → 返回失败
                _make_response({"success": False, "detail": "expired"}),
                # 第二次 post: login → 返回成功
                # 这里需要用 side_effect 但 session.post 是 async context manager
            ]
        ))
        # 用更简洁的方式：分两次注入 session
        session1 = _make_mock_session(post_resp=refresh_resp)
        _inject_session(auth, session1)
        refresh_result = await auth.refresh_token("bad-refresh")
        assert not refresh_result.success

        session2 = _make_mock_session(post_resp=login_resp)
        auth._session = session2
        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            login_result = await auth.login("user", "pass")
            assert login_result.success

    @pytest.mark.asyncio
    async def test_login_failure_returns_error(self):
        """login 失败返回错误，不抛异常"""
        auth = AuthService("https://test.example.com")
        login_resp = _make_response({"success": False, "detail": "密码错误"}, status=401)
        _inject_session(auth, _make_mock_session(post_resp=login_resp))

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            result = await auth.login("user", "wrong-pass")

        assert not result.success
        assert "密码错误" in result.message


# ---------------------------------------------------------------------------
# S401: 共享 ClientSession + has_public_key 守卫测试
# ---------------------------------------------------------------------------

class TestSharedClientSession:
    """验证 AuthService 共享 ClientSession 行为"""

    @pytest.mark.asyncio
    async def test_session_created_lazily(self):
        """__init__ 不创建 session，首次调用才创建"""
        auth = AuthService("https://test.example.com")
        assert auth._session is None

    @pytest.mark.asyncio
    async def test_session_reused_across_calls(self):
        """同一 AuthService 实例 verify→refresh 复用同一 session"""
        auth = AuthService("https://test.example.com")
        verify_resp = _make_response([], status=200)
        session = _make_mock_session(get_resp=verify_resp)
        _inject_session(auth, session)

        await auth.verify_token("token")
        # session 不变
        assert auth._session is session

    @pytest.mark.asyncio
    async def test_close_cleans_up_session(self):
        """close() 后 session 被关闭"""
        auth = AuthService("https://test.example.com")
        mock_session = _make_mock_session(get_resp=_make_response([]))
        _inject_session(auth, mock_session)
        assert auth._session is not None

        await auth.close()
        assert auth._session is None

    @pytest.mark.asyncio
    async def test_close_safe_when_no_session(self):
        """无 session 时 close() 不抛异常"""
        auth = AuthService("https://test.example.com")
        assert auth._session is None
        await auth.close()  # 不抛异常
        assert auth._session is None

    @pytest.mark.asyncio
    async def test_close_safe_after_exception(self):
        """异常后 close() 不抛二次异常"""
        auth = AuthService("https://test.example.com")
        mock_session = _make_mock_session(get_resp=_make_response([]))
        _inject_session(auth, mock_session)
        # 模拟 session.close 抛异常，close() 应安全吞掉
        mock_session.close = AsyncMock(side_effect=RuntimeError("already closed"))
        mock_session.closed = False
        await auth.close()  # 不抛异常
        assert auth._session is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """async with AuthService 自动 close"""
        auth = AuthService("https://test.example.com")
        mock_session = _make_mock_session(get_resp=_make_response([], status=200))
        _inject_session(auth, mock_session)

        assert auth._session is not None
        async with auth:
            await auth.verify_token("token")
        # __aexit__ 调用了 close()
        assert auth._session is None

    @pytest.mark.asyncio
    async def test_get_session_recreates_after_close(self):
        """close() 后再次调用 _get_session() 创建新 session"""
        auth = AuthService("https://test.example.com")
        session1 = MagicMock()
        session1.closed = True
        auth._session = session1

        new_session = auth._get_session()
        assert new_session is not session1


class TestPublicKeyGuard:
    """验证 has_public_key 守卫行为"""

    @pytest.mark.asyncio
    async def test_login_skips_pubkey_when_cached(self):
        """has_public_key=True 时不调用 fetch_public_key"""
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "token": "t", "refresh_token": "r"})
        _inject_session(auth, _make_mock_session(post_resp=resp))

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            result = await auth.login("user", "pass")

        assert result.success
        mock_crypto.fetch_public_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_login_fetches_pubkey_when_missing(self):
        """has_public_key=False 时正常拉取公钥"""
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "token": "t", "refresh_token": "r"})
        _inject_session(auth, _make_mock_session(post_resp=resp))

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = False
            mock_crypto.fetch_public_key = AsyncMock()
            # fetch_public_key 成功后 has_public_key 变为 True
            def _set_has_pubkey(*args, **kwargs):
                mock_crypto.has_public_key = True
            mock_crypto.fetch_public_key.side_effect = _set_has_pubkey
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            result = await auth.login("user", "pass")

        assert result.success
        mock_crypto.fetch_public_key.assert_called_once()

    @pytest.mark.asyncio
    async def test_ws_pubkey_fail_closed(self):
        """ws:// (→ http://) 公钥拉取失败时 fail-closed（不回退明文）"""
        auth = AuthService("http://test.example.com")  # ws:// → http://
        _inject_session(auth, _make_mock_session(post_resp=_make_response({"success": True})))

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = False
            mock_crypto.fetch_public_key = AsyncMock(side_effect=RuntimeError("network error"))

            with pytest.raises(RuntimeError, match="network error"):
                await auth.login("user", "pass")

    @pytest.mark.asyncio
    async def test_https_pubkey_fail_fallback(self):
        """https:// 公钥失败时 TLS 下回退明文密码"""
        auth = AuthService("https://test.example.com")
        resp = _make_response({"success": True, "token": "t", "refresh_token": "r"})
        session = _make_mock_session(post_resp=resp)
        _inject_session(auth, session)

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = False
            mock_crypto.fetch_public_key = AsyncMock(side_effect=RuntimeError("network error"))
            result = await auth.login("user", "pass")

        assert result.success
        # 验证使用了明文密码
        call_kwargs = session.post.call_args[1]
        assert call_kwargs["json"]["password"] == "pass"
        assert "password_encrypted" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_fallback_state_machine_intact(self):
        """verify 失败 → refresh → login 状态链不变"""
        auth = AuthService("https://test.example.com")

        # 模拟完整链路：verify 401 → refresh 失败 → login 成功
        verify_resp = _make_response([], status=401)
        refresh_resp = _make_response({"success": False, "detail": "expired"})
        login_resp = _make_response({"success": True, "token": "new_token", "refresh_token": "new_r"})

        # 注入 session 同时支持 get 和 post
        call_count = {"post": 0}

        @asynccontextmanager
        async def _post_cm(*args, **kwargs):
            call_count["post"] += 1
            if call_count["post"] == 1:
                yield refresh_resp
            else:
                yield login_resp

        session = _make_mock_session(get_resp=verify_resp)
        session.post = MagicMock(side_effect=_post_cm)
        _inject_session(auth, session)

        # verify 失败
        assert await auth.verify_token("expired") is False
        # refresh 失败
        refresh_result = await auth.refresh_token("bad-refresh")
        assert not refresh_result.success
        # login 成功
        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            login_result = await auth.login("user", "pass")
        assert login_result.success
        assert login_result.access_token == "new_token"


# ---------------------------------------------------------------------------
# S401 集成测试：ensure_valid_token 单实例 + login 命令 + session 真复用
# ---------------------------------------------------------------------------

class TestEnsureValidTokenIntegration:
    """验证 ensure_valid_token 使用单个 AuthService 实例 + async with"""

    @pytest.mark.asyncio
    async def test_single_auth_service_instance_verify_ok(self):
        """verify 成功路径：只创建 1 个 AuthService，且 async with 后 close 被调用"""
        from app.core.config import Config
        from app.cli import ensure_valid_token

        config = Config(server_url="https://test.example.com")
        config.access_token = "valid-token"
        config_path = MagicMock()

        verify_resp = _make_response([], status=200)
        mock_session = _make_mock_session(get_resp=verify_resp)

        created_instances = []
        original_init = AuthService.__init__

        def _tracking_init(self_auth, server_url: str):
            original_init(self_auth, server_url)
            _inject_session(self_auth, mock_session)
            created_instances.append(self_auth)

        with patch.object(AuthService, "__init__", _tracking_init):
            success, token = await ensure_valid_token(config, config_path)

        assert success is True
        assert token == "valid-token"
        # 只创建了 1 个 AuthService 实例
        assert len(created_instances) == 1
        # async with 退出后 session 被清理
        assert created_instances[0]._session is None

    @pytest.mark.asyncio
    async def test_single_auth_service_instance_full_fallback(self):
        """verify 失败 → refresh 失败 → login 成功：全程使用 1 个 AuthService"""
        from app.core.config import Config
        from app.cli import ensure_valid_token

        config = Config(server_url="https://test.example.com")
        config.access_token = "expired-token"
        config.refresh_token = "expired-refresh"
        config.username = "user"
        config.password = "pass"
        config_path = MagicMock()

        verify_resp = _make_response([], status=401)
        refresh_resp = _make_response({"success": False, "detail": "expired"})
        login_resp = _make_response({"success": True, "token": "new_token", "refresh_token": "new_r"})

        call_count = {"post": 0}

        @asynccontextmanager
        async def _post_cm(*args, **kwargs):
            call_count["post"] += 1
            if call_count["post"] == 1:
                yield refresh_resp
            else:
                yield login_resp

        mock_session = _make_mock_session(get_resp=verify_resp)
        mock_session.post = MagicMock(side_effect=_post_cm)

        created_instances = []
        original_init = AuthService.__init__

        def _tracking_init(self_auth, server_url: str):
            original_init(self_auth, server_url)
            _inject_session(self_auth, mock_session)
            created_instances.append(self_auth)

        with patch.object(AuthService, "__init__", _tracking_init), \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            success, token = await ensure_valid_token(config, config_path)

        assert success is True
        assert token == "new_token"
        # 只创建了 1 个 AuthService 实例（不是旧的 2 个）
        assert len(created_instances) == 1

    @pytest.mark.asyncio
    async def test_session_reused_across_verify_refresh_login(self):
        """verify→refresh→login 全链路复用同一个 mock session 对象"""
        auth = AuthService("https://test.example.com")

        verify_resp = _make_response([], status=401)
        refresh_resp = _make_response({"success": False, "detail": "expired"})
        login_resp = _make_response({"success": True, "token": "new_token", "refresh_token": "new_r"})

        call_count = {"post": 0}

        @asynccontextmanager
        async def _post_cm(*args, **kwargs):
            call_count["post"] += 1
            if call_count["post"] == 1:
                yield refresh_resp
            else:
                yield login_resp

        mock_session = _make_mock_session(get_resp=verify_resp)
        mock_session.post = MagicMock(side_effect=_post_cm)
        _inject_session(auth, mock_session)

        # 三步都走同一 session
        await auth.verify_token("expired")
        session_after_verify = auth._session

        await auth.refresh_token("bad-refresh")
        session_after_refresh = auth._session

        with patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            await auth.login("user", "pass")

        # 全程 session 对象不变
        assert auth._session is session_after_verify
        assert auth._session is session_after_refresh
        # 调用了 get 1 次 + post 2 次 = 共 3 次 HTTP，全走同一 session
        assert mock_session.get.call_count == 1
        assert mock_session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_token_auto_login_uses_single_instance(self):
        """无 token + 有 username/password → auto-login，仍然只有 1 个 AuthService"""
        from app.core.config import Config
        from app.cli import ensure_valid_token

        config = Config(server_url="https://test.example.com")
        config.access_token = None
        config.username = "user"
        config.password = "pass"
        config_path = MagicMock()

        login_resp = _make_response({"success": True, "token": "auto_token", "refresh_token": "auto_r"})
        mock_session = _make_mock_session(post_resp=login_resp)

        created_instances = []
        original_init = AuthService.__init__

        def _tracking_init(self_auth, server_url: str):
            original_init(self_auth, server_url)
            _inject_session(self_auth, mock_session)
            created_instances.append(self_auth)

        with patch.object(AuthService, "__init__", _tracking_init), \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            success, token = await ensure_valid_token(config, config_path)

        assert success is True
        assert token == "auto_token"
        assert len(created_instances) == 1


class TestLoginCommandIntegration:
    """验证 CLI login 命令使用 async with AuthService"""

    def test_login_command_uses_async_with(self, tmp_path):
        """login 命令应通过 async with 创建 AuthService，退出后 session 清理"""
        from click.testing import CliRunner
        from app.cli import cli

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"server_url": "https://test.example.com"}))

        login_resp = _make_response({
            "success": True,
            "token": "test-access",
            "refresh_token": "test-refresh",
            "session_id": "sid-123",
        })
        mock_session = _make_mock_session(post_resp=login_resp)

        closed = {"called": False}
        original_close = AuthService.close

        async def _tracking_close(self_auth):
            closed["called"] = True
            await original_close(self_auth)

        runner = CliRunner()
        with patch.object(AuthService, "close", _tracking_close), \
             patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("app.security.auth_service.agent_crypto") as mock_crypto:
            mock_crypto.has_public_key = True
            mock_crypto.rsa_encrypt_b64.return_value = "enc"
            result = runner.invoke(cli, [
                "--config", str(config_file),
                "login", "--server", "https://test.example.com",
                "--username", "testuser", "--password", "testpass",
            ])

        assert result.exit_code == 0
        assert "登录成功" in result.output
        # async with 退出后 close 被调用
        assert closed["called"], "login 命令应通过 async with 自动关闭 session"
