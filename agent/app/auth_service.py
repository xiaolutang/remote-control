"""
认证服务模块
处理登录、token 刷新等认证相关操作
"""
import logging
import aiohttp
from typing import Optional
from dataclasses import dataclass

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
    """认证服务"""

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

    async def login(self, username: str, password: str) -> LoginResult:
        """
        用户登录

        Args:
            username: 用户名
            password: 密码

        Returns:
            LoginResult 登录结果
        """
        url = f"{self.base_url}/api/login"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"username": username, "password": password},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    data = await response.json()

                    if response.status == 200 and data.get("success"):
                        logger.info("Login success: username=%s", username)
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
                        return LoginResult(
                            success=False,
                            message=data.get("detail", "登录失败"),
                        )

        except aiohttp.ClientError as e:
            logger.warning("Login network error: username=%s error=%s", username, e)
            return LoginResult(
                success=False,
                message=f"网络错误: {e}",
            )
        except Exception as e:
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
        url = f"{self.base_url}/api/refresh"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"refresh_token": refresh_token},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    data = await response.json()

                    if response.status == 200 and data.get("success"):
                        logger.info("Token refresh success")
                        return RefreshResult(
                            success=True,
                            access_token=data.get("access_token"),
                            refresh_token=data.get("refresh_token"),
                            expires_in=data.get("expires_in"),
                            message="Token 刷新成功",
                        )
                    else:
                        return RefreshResult(
                            success=False,
                            message=data.get("detail", "Token 刷新失败"),
                        )

        except aiohttp.ClientError as e:
            return RefreshResult(
                success=False,
                message=f"网络错误: {e}",
            )
        except Exception as e:
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
        # 使用 /api/devices 端点验证 token（需要认证的简单端点）
        url = f"{self.base_url}/api/devices?username=test"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    result = response.status == 200
                    if not result:
                        logger.warning("Token verification failed: status=%d", response.status)
                    return result

        except Exception as e:
            logger.warning("Token verification error: %s", e)
            return False
