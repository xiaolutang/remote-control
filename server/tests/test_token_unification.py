"""
B041/B042: Token 统一校验 + 直接踢出机制单元测试

覆盖：
- DF-20260409-04 场景：被踢设备旧 token 通过 WS 重连时的行为验证
- B042: 移除冲突弹窗，简化为新设备直接踢出旧设备
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.auth import TokenVerificationError
from app.ws_client import client_websocket_handler, ClientConnection, active_clients
from app.ws_agent import agent_websocket_handler


# ---------- WS Client Token 校验行为 ----------


class TestWSClientTokenReplaced:
    """WS Client: token_version 不匹配 → 4001 TOKEN_REPLACED"""

    @pytest.mark.asyncio
    async def test_replaced_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
            )
            await client_websocket_handler(
                mock_ws, "session-1", "old-token", view="mobile"
            )

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_REPLACED"


class TestWSClientTokenExpired:
    """WS Client: token 过期 → 4001 TOKEN_EXPIRED"""

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已过期",
                error_code="TOKEN_EXPIRED",
            )
            await client_websocket_handler(
                mock_ws, "session-1", "expired-token", view="mobile"
            )

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_EXPIRED"


class TestWSClientTokenInvalid:
    """WS Client: token 无效 → 4001 TOKEN_INVALID"""

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 无效: signature mismatch",
                error_code="TOKEN_INVALID",
            )
            await client_websocket_handler(
                mock_ws, "session-1", "bad-token", view="mobile"
            )

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_INVALID"


class TestWSClientRedisUnavailable:
    """WS Client: Redis 不可用时的行为"""

    @pytest.mark.asyncio
    async def test_redis_down_with_token_version(self):
        """携带 token_version + Redis GET 失败 → 4504"""
        from fastapi import HTTPException

        mock_ws = AsyncMock()

        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = HTTPException(
                status_code=503,
                detail="Token 验证服务暂不可用",
            )
            await client_websocket_handler(
                mock_ws, "session-1", "token-with-version", view="mobile"
            )

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4504 or call[1].get("code") == 4504

    @pytest.mark.asyncio
    async def test_redis_down_without_token_version(self):
        """无 token_version → 正常放行（Redis 不参与）"""

        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_client.async_verify_token', return_value={
            "session_id": "session-1", "sub": "user1"
        }):
            with patch('app.ws_client.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                await client_websocket_handler(
                                    mock_ws, "session-1", "old-token-no-version",
                                    view="mobile"
                                )
                            except asyncio.CancelledError:
                                pass

        # 不应被 close
        mock_ws.close.assert_not_called()
        first_msg = mock_ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"


class TestWSClientCurrentTokenAccepted:
    """WS Client: 当前有效 token → 正常连接"""

    @pytest.mark.asyncio
    async def test_valid_token_connects(self):

        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_client.async_verify_token', return_value={
            "session_id": "session-1",
            "sub": "user1",
            "token_version": 2,
            "view_type": "mobile",
        }):
            with patch('app.ws_client.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                await client_websocket_handler(
                                    mock_ws, "session-1", "valid-token",
                                    view="mobile"
                                )
                            except asyncio.CancelledError:
                                pass

        mock_ws.close.assert_not_called()
        first_msg = mock_ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"
        assert first_msg["session_id"] == "session-1"


# ---------- WS Agent Token 校验行为 ----------


class TestWSAgentTokenReplaced:
    """WS Agent: token_version 不匹配 → 4001 TOKEN_REPLACED"""

    @pytest.mark.asyncio
    async def test_replaced_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_agent.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
            )
            await agent_websocket_handler(mock_ws, "old-token")

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_REPLACED"


class TestWSAgentTokenExpired:
    """WS Agent: token 过期 → 4001 TOKEN_EXPIRED"""

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_agent.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已过期",
                error_code="TOKEN_EXPIRED",
            )
            await agent_websocket_handler(mock_ws, "expired-token")

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_EXPIRED"


class TestWSAgentTokenInvalid:
    """WS Agent: token 无效 → 4001"""

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        mock_ws = AsyncMock()

        with patch('app.ws_agent.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 无效: bad signature",
                error_code="TOKEN_INVALID",
            )
            await agent_websocket_handler(mock_ws, "bad-token")

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001


class TestWSAgentRedisUnavailable:
    """WS Agent: Redis 不可用时的行为"""

    @pytest.mark.asyncio
    async def test_redis_down_with_token_version(self):
        """携带 token_version + Redis GET 失败 → 4503"""
        from fastapi import HTTPException

        mock_ws = AsyncMock()

        with patch('app.ws_agent.async_verify_token') as mock_verify:
            mock_verify.side_effect = HTTPException(
                status_code=503,
                detail="Token 验证服务暂不可用",
            )
            await agent_websocket_handler(mock_ws, "token-with-version")

        mock_ws.close.assert_called_once()
        call = mock_ws.close.call_args
        assert call.kwargs.get("code") == 4503 or call[1].get("code") == 4503


class TestWSAgentOldTokenAccepted:
    """WS Agent: 无 token_version 的旧 token → 正常放行"""

    @pytest.mark.asyncio
    async def test_old_token_accepted(self):

        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_agent.async_verify_token', return_value={
            "session_id": "session-1", "sub": "user1"
        }):
            with patch('app.ws_agent.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_agent.set_session_online', new_callable=AsyncMock):
                    with patch('app.ws_agent.update_session_device_heartbeat', new_callable=AsyncMock):
                        with patch('app.ws_agent._restore_recoverable_terminals', new_callable=AsyncMock):
                            with patch('app.ws_client.get_view_counts', return_value={"mobile": 0, "desktop": 0}):
                                try:
                                    await agent_websocket_handler(mock_ws, "old-token")
                                except asyncio.CancelledError:
                                    pass

        # 不应被 close（正常连接）
        assert not mock_ws.close.called
        first_msg = mock_ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"
        assert first_msg["session_id"] == "session-1"


# ---------- history_api get_current_session_async ----------


class TestHistoryApiAsyncVerify:
    """history_api 使用 get_current_session_async（内部调用 async_verify_token）"""

    def test_imports_async_version(self):
        import app.history_api as mod
        import inspect
        source = inspect.getsource(mod.get_history_endpoint)
        assert "get_current_session_async" in source
        assert "get_current_session," not in source

    def test_auth_provides_async_version(self):
        """auth.py 导出 get_current_session_async"""
        from app.auth import get_current_session_async
        assert callable(get_current_session_async)


# ---------- DF-20260409-04 回归集成测试 ----------


class TestDF20260409Regression:
    """DF-20260409-04 回归：设备 A 登录 → 设备 B 登录(同端) → A WS 用旧 token 重连 → 被拒绝"""

    @pytest.mark.asyncio
    async def test_kicked_device_reconnect_rejected(self):
        """
        场景：iOS(A) 被 Android(B) 踢下线后，A 的 WS 自动重连用旧 token。
        旧 token 的 token_version 不匹配 → async_verify_token 抛出 TOKEN_REPLACED
        → WS 返回 4001 → A 无法重连 → B 不受影响（不再互踢乒乓）。
        """
        mock_ws_a = AsyncMock()

        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
            )
            await client_websocket_handler(
                mock_ws_a, "session-1", "ios-old-token", view="mobile"
            )

        # A 被拒绝，close code 4001 + reason TOKEN_REPLACED
        mock_ws_a.close.assert_called_once()
        call = mock_ws_a.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001
        reason = call.kwargs.get("reason") or call[1].get("reason")
        assert reason == "TOKEN_REPLACED"

    @pytest.mark.asyncio
    async def test_new_device_unaffected_by_old_rejected(self):
        """B 的 WS 不受 A 旧 token 重连被拒的影响（不再互踢乒乓）"""
        # 手动注册 B 到 active_clients（模拟 B 已在线）
        mock_ws_b = AsyncMock()
        client_b = ClientConnection("session-1", mock_ws_b, view_type="mobile")
        active_clients["session-1"] = [client_b]

        # A 用旧 token 重连 → 在 async_verify_token 阶段被拒
        mock_ws_a = AsyncMock()
        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
            )
            await client_websocket_handler(
                mock_ws_a, "session-1", "ios-old-token", view="mobile"
            )

        # A 被拒绝
        mock_ws_a.close.assert_called_once()

        # B 完全不受影响（没有被 close）
        mock_ws_b.close.assert_not_called()

        # B 仍在 active_clients 中
        assert client_b in active_clients.get("session-1", [])

        # 清理
        active_clients.clear()


# ---------- S026: 集成测试 ----------


class TestCrossViewNoKick:
    """S026: 跨端不互踢 — mobile 被踢不影响 desktop WS"""

    @pytest.mark.asyncio
    async def test_mobile_kicked_desktop_unaffected(self):
        """mobile token_version 不匹配 → 只有 mobile 被拒，desktop 不受影响"""
        active_clients.clear()

        # desktop 已在线
        mock_ws_desktop = AsyncMock()
        desktop_client = ClientConnection("session-1", mock_ws_desktop, view_type="desktop")
        active_clients["session-1"] = [desktop_client]

        # mobile 旧 token 重连 → 被拒
        mock_ws_mobile = AsyncMock()
        with patch('app.ws_client.async_verify_token') as mock_verify:
            mock_verify.side_effect = TokenVerificationError(
                status_code=401,
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
            )
            await client_websocket_handler(
                mock_ws_mobile, "session-1", "mobile-old-token", view="mobile"
            )

        # mobile 被拒
        mock_ws_mobile.close.assert_called_once()
        call = mock_ws_mobile.close.call_args
        assert call.kwargs.get("code") == 4001 or call[1].get("code") == 4001

        # desktop 完全不受影响
        mock_ws_desktop.close.assert_not_called()
        assert desktop_client in active_clients.get("session-1", [])

        active_clients.clear()


# ---------- B042: 直接踢出机制 ----------


class TestDirectKick:
    """B042: 新设备连接时直接踢出同端旧设备"""

    @pytest.mark.asyncio
    async def test_new_device_kicks_old_device(self):
        """新设备连接 → 旧设备收到 device_kicked + close(4011)"""
        active_clients.clear()

        # 旧设备 A 已在线
        mock_ws_a = AsyncMock()
        client_a = ClientConnection("session-1", mock_ws_a, view_type="mobile")
        active_clients["session-1"] = [client_a]

        # 新设备 B 连接（需要完整的 mock 链路）
        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws_b = AsyncMock()
        mock_ws_b.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_client.async_verify_token', return_value={
            "session_id": "session-1", "sub": "user1",
            "token_version": 2, "view_type": "mobile",
        }):
            with patch('app.ws_client.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                await client_websocket_handler(
                                    mock_ws_b, "session-1", "new-device-token",
                                    view="mobile"
                                )
                            except asyncio.CancelledError:
                                pass

        # 旧设备 A 收到 device_kicked 消息
        mock_ws_a.send_json.assert_called()
        kicked_msg = mock_ws_a.send_json.call_args[0][0]
        assert kicked_msg["type"] == "device_kicked"
        assert kicked_msg["reason"] == "replaced_by_new_device"

        # 旧设备 A 被 close(4011)
        mock_ws_a.close.assert_called_once()
        call = mock_ws_a.close.call_args
        assert call.kwargs.get("code") == 4011 or call[1].get("code") == 4011

        # 新设备 B 正常连接（收到 connected）
        first_msg = mock_ws_b.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"

        active_clients.clear()

    @pytest.mark.asyncio
    async def test_cross_view_no_kick(self):
        """跨端不互踢：mobile + desktop 同时在线"""
        active_clients.clear()

        # desktop 已在线
        mock_ws_desktop = AsyncMock()
        desktop_client = ClientConnection("session-1", mock_ws_desktop, view_type="desktop")
        active_clients["session-1"] = [desktop_client]

        # mobile 新设备连接
        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws_mobile = AsyncMock()
        mock_ws_mobile.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_client.async_verify_token', return_value={
            "session_id": "session-1", "sub": "user1",
        }):
            with patch('app.ws_client.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                await client_websocket_handler(
                                    mock_ws_mobile, "session-1", "mobile-token",
                                    view="mobile"
                                )
                            except asyncio.CancelledError:
                                pass

        # desktop 不受影响
        mock_ws_desktop.close.assert_not_called()
        assert desktop_client in active_clients.get("session-1", [])

        # mobile 正常连接
        first_msg = mock_ws_mobile.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"

        active_clients.clear()

    def test_no_conflict_futures_or_timeout(self):
        """确认 conflict_futures 和 CONFLICT_TIMEOUT 已被移除"""
        import app.ws_client as ws_module
        assert not hasattr(ws_module, 'conflict_futures')
        assert not hasattr(ws_module, 'CONFLICT_TIMEOUT')
        assert not hasattr(ws_module, '_resolve_conflict')
        assert not hasattr(ws_module, '_cleanup_conflict_future')

    @pytest.mark.asyncio
    async def test_old_client_already_disconnected(self):
        """旧设备已断开时，新设备仍正常连接（send/close 异常被吞掉）"""
        active_clients.clear()

        # 旧设备 A 的 websocket send 会抛异常
        mock_ws_a = AsyncMock()
        mock_ws_a.send_json.side_effect = Exception("Connection closed")
        mock_ws_a.close.side_effect = Exception("Already closed")
        client_a = ClientConnection("session-1", mock_ws_a, view_type="mobile")
        active_clients["session-1"] = [client_a]

        # 新设备 B 连接
        async def cancelled_iter_json():
            if False:
                yield {}
            raise asyncio.CancelledError

        mock_ws_b = AsyncMock()
        mock_ws_b.iter_json = MagicMock(return_value=cancelled_iter_json())

        with patch('app.ws_client.async_verify_token', return_value={
            "session_id": "session-1", "sub": "user1",
        }):
            with patch('app.ws_client.get_session', return_value={
                "session_id": "session-1", "owner": "user1"
            }):
                with patch('app.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                await client_websocket_handler(
                                    mock_ws_b, "session-1", "new-device-token",
                                    view="mobile"
                                )
                            except asyncio.CancelledError:
                                pass

        # 新设备 B 正常连接（不受旧设备异常影响）
        first_msg = mock_ws_b.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"

        active_clients.clear()


class TestConcurrentReconnect:
    """S026: 并发重连 — 旧设备重连被拒，新设备不受影响"""

    @pytest.mark.asyncio
    async def test_concurrent_old_new_reconnect(self):
        """旧设备 A 和新设备 B 同时重连时，A 被拒，B 正常"""
        active_clients.clear()

        # B 已在线
        mock_ws_b = AsyncMock()
        client_b = ClientConnection("session-1", mock_ws_b, view_type="mobile")
        active_clients["session-1"] = [client_b]

        # A 用旧 token 重连 → 被拒
        async def old_device_connect():
            mock_ws_a = AsyncMock()
            with patch('app.ws_client.async_verify_token') as mock_verify:
                mock_verify.side_effect = TokenVerificationError(
                    status_code=401,
                    detail="Token 已在其他设备登录",
                    error_code="TOKEN_REPLACED",
                )
                await client_websocket_handler(
                    mock_ws_a, "session-1", "ios-old-token", view="mobile"
                )
            return mock_ws_a

        # 模拟并发
        results = await asyncio.gather(old_device_connect())

        # A 被拒
        mock_ws_a = results[0]
        mock_ws_a.close.assert_called_once()

        # B 不受影响
        mock_ws_b.close.assert_not_called()
        assert client_b in active_clients.get("session-1", [])

        active_clients.clear()
