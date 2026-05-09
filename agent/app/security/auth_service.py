"""
认证服务模块
处理登录、token 刷新等认证相关操作
"""
import logging
import time

import aiohttp
from typing import Optional
from dataclasses import dataclass

from app.core.config import ssl_context_for_aiohttp
from app.core.log_adapter import _log
from app.security.crypto import agent_crypto

logger = logging.getLogger(__name__)


@dataclass
class LoginResult:
    """登录结果"""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    session_id: Optional[str] = None
    expires_in: Optional[int] = None
    message: str = ""


@dataclass
class RefreshResult:
    """刷新 Token 结果"""
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    message: str = ""


class AuthService:
    """认证服务（共享 ClientSession，支持 async with 自动清理）"""

    def __init__(self, server_url: str):
        """
        初始化认证服务

        Args:
            server_url: 服务器 URL (例如: http://localhost:8000 或 ws://localhost:8000)
        """
        # 确保 server_url 是 HTTP URL
        if server_url.startswith("ws://"):
            self.base_url = server_url.replace("ws://", "http://")
        elif server_url.startswith("wss://"):
            self.base_url = server_url.replace("wss://", "https://")
        else:
            self.base_url = server_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    # ---- 会话管理 ----

    def _get_session(self) -> aiohttp.ClientSession:
        """懒加载共享 ClientSession。"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """关闭共享 ClientSession。安全重复调用。"""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception as e:
                logger.debug("session close failed: %s", e)  # Expected: session may already be closed
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def login(self, username: str, password: str) -> LoginResult:
        """
        用户登录
        """
        t0 = time.monotonic()
        url = f"{self.base_url}/api/login"

        # 密码加密：ws:// (→ http://) 必须加密（不变量 #27），wss:// (→ https://) 由 TLS 保护
        body = {"username": username}
        is_tls = self.base_url.startswith("https://")
        if not agent_crypto.has_public_key:
            try:
                await agent_crypto.fetch_public_key(self.base_url)
            except Exception:
                if not is_tls:
                    raise  # ws:// 必须加密，异常直接传播给调用方
                logger.warning("Public key fetch failed, TLS protects transport")
        if agent_crypto.has_public_key:
            body["password_encrypted"] = agent_crypto.rsa_encrypt_b64(password.encode())
        else:
            body["password"] = password

        try:
            session = self._get_session()
            async with session.post(
                url,
                json=body,
                ssl=ssl_context_for_aiohttp(),
                timeout=aiohttp.ClientTimeout(total=8),
            ) as response:
                data = await response.json()

                if response.status == 200 and data.get("success"):
                    logger.info("Login success: username=%s", username)
                    _log(f"auth: login took {time.monotonic() - t0:.3f}s (success)")
                    return LoginResult(
                        success=True,
                        access_token=data.get("token"),
                        refresh_token=data.get("refresh_token"),
                        session_id=data.get("session_id"),
                        expires_in=data.get("expires_in"),
                        message=data.get("message", "登录成功"),
                    )
                else:
                    logger.warning("Login failed: username=%s status=%d", username, response.status)
                    _log(f"auth: login took {time.monotonic() - t0:.3f}s (failed: status={response.status})")
                    return LoginResult(
                        success=False,
                        message=data.get("detail", "登录失败"),
                    )

        except aiohttp.ClientError as e:
            logger.warning("Login network error: username=%s error=%s", username, e)
            _log(f"auth: login took {time.monotonic() - t0:.3f}s (network error)")
            return LoginResult(
                success=False,
                message=f"网络错误: {e}",
            )
        except Exception as e:
            _log(f"auth: login took {time.monotonic() - t0:.3f}s (exception)")
            return LoginResult(
                success=False,
                message=f"登录失败: {e}",
            )

    async def refresh_token(self, refresh_token: str) -> RefreshResult:
        """
        刷新 Access Token

        Args:
            refresh_token: Refresh Token

        Returns:
            RefreshResult 刷新结果
        """
        t0 = time.monotonic()
        url = f"{self.base_url}/api/refresh"

        try:
            session = self._get_session()
            async with session.post(
                url,
                json={"refresh_token": refresh_token},
                ssl=ssl_context_for_aiohttp(),
                timeout=aiohttp.ClientTimeout(total=8),
            ) as response:
                data = await response.json()

                if response.status == 200 and data.get("success"):
                    logger.info("Token refresh success")
                    _log(f"auth: refresh_token took {time.monotonic() - t0:.3f}s (success)")
                    return RefreshResult(
                        success=True,
                        access_token=data.get("access_token"),
                        refresh_token=data.get("refresh_token"),
                        expires_in=data.get("expires_in"),
                        message="Token 刷新成功",
                    )
                else:
                    _log(f"auth: refresh_token took {time.monotonic() - t0:.3f}s (failed)")
                    return RefreshResult(
                        success=False,
                        message=data.get("detail", "Token 刷新失败"),
                    )

        except aiohttp.ClientError as e:
            _log(f"auth: refresh_token took {time.monotonic() - t0:.3f}s (network error)")
            return RefreshResult(
                success=False,
                message=f"网络错误: {e}",
            )
        except Exception as e:
            _log(f"auth: refresh_token took {time.monotonic() - t0:.3f}s (exception)")
            return RefreshResult(
                success=False,
                message=f"刷新失败: {e}",
            )

    async def verify_token(self, access_token: str) -> bool:
        """
        验证 Token 是否有效

        Args:
            access_token: Access Token

        Returns:
            bool Token 是否有效
        """
        t0 = time.monotonic()
        url = f"{self.base_url}/api/devices"

        try:
            session = self._get_session()
            async with session.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                ssl=ssl_context_for_aiohttp(),
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                result = response.status == 200
                _log(f"auth: verify_token took {time.monotonic() - t0:.3f}s (status={response.status})")
                if not result:
                    logger.warning("Token verification failed: status=%d", response.status)
                return result

        except Exception as e:
            _log(f"auth: verify_token took {time.monotonic() - t0:.3f}s (error)")
            logger.warning("Token verification error: %s", e)
            return False
