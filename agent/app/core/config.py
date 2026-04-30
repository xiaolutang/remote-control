"""
配置管理模块
"""
import json
import os
import ssl
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, ConfigDict


def is_ssl_insecure() -> bool:
    """是否跳过 SSL 证书验证（仅开发环境，由 Client 通过 RC_SSL_INSECURE=1 传入）"""
    return os.environ.get('RC_SSL_INSECURE') == '1'


def ssl_context_for_aiohttp():
    """aiohttp 的 SSL 参数： insecure 时返回 False，否则返回 None 走默认验证"""
    return False if is_ssl_insecure() else None


def ssl_context_for_websockets():
    """websockets 的 SSL 参数：insecure 时返回不验证的 SSLContext，否则返回 None"""
    if not is_ssl_insecure():
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Config(BaseModel):
    """Agent 配置"""
    model_config = ConfigDict(extra="ignore")

    server_url: str = "ws://localhost:8000"
    # 新的 token 字段（推荐）
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None  # 仅内存中使用，不持久化
    # 旧字段（向后兼容）
    token: Optional[str] = None
    # PTY 配置
    command: str = "/bin/bash"
    shell_mode: bool = False
    # 连接配置
    auto_reconnect: bool = True
    max_retries: int = 60
    reconnect_max_attempts: int = 10
    reconnect_base_delay: float = 1.0
    heartbeat_interval: float = 30.0
    # 服务端 URL（用于 HTTP API，可能与 WebSocket URL 不同）
    api_url: Optional[str] = None

    def get_access_token(self) -> Optional[str]:
        """获取 access token（优先新字段，向后兼容旧字段）"""
        return self.access_token or self.token

    def has_valid_credentials(self) -> bool:
        """检查是否有有效的登录凭据"""
        return bool(self.get_access_token() and self.refresh_token)

    def can_auto_login(self) -> bool:
        """检查是否有自动登录所需的凭据"""
        return bool(self.username and self.password)


def get_config_path() -> Path:
    """获取配置文件路径"""
    config_dir = os.environ.get("RC_AGENT_CONFIG_DIR", "~/.rc-agent")
    return Path(config_dir).expanduser() / "config.json"


def normalize_config_path(config_path: Optional[Path | str] = None) -> Path:
    """将 str/Path/None 统一转换为 Path。"""
    if config_path is None:
        return get_config_path()
    if isinstance(config_path, Path):
        return config_path.expanduser()
    return Path(config_path).expanduser()


def load_config(config_path: Optional[Path | str] = None, *, strict: bool = False) -> Config:
    """加载配置

    优先级：配置文件 > 环境变量 > 默认值。
    环境变量用于 Docker 容器场景（无持久化配置文件时）。

    Args:
        config_path: 配置文件路径。None 时从 RC_AGENT_CONFIG_DIR 派生。
        strict: 为 True 时（显式 --config 场景），文件存在但无法读取或
                JSON 格式错误将直接抛出异常，而非静默回退。
    """
    config_path = normalize_config_path(config_path)

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return Config(**data)
        except json.JSONDecodeError as exc:
            if strict:
                raise
            # 配置文件格式错误，回退到环境变量
        except (OSError, PermissionError):
            if strict:
                raise
    else:
        # File does not exist — in strict mode this is not an error
        # (the CLI already emitted a warning before calling load_config)
        pass

    # 无配置文件时，从环境变量回退
    server_url = os.environ.get("SERVER_URL")
    agent_token = os.environ.get("AGENT_TOKEN")
    agent_username = os.environ.get("AGENT_USERNAME")
    agent_password = os.environ.get("AGENT_PASSWORD")
    overrides = {}
    if server_url:
        overrides["server_url"] = server_url
    if agent_token:
        overrides["access_token"] = agent_token
        overrides["token"] = agent_token
    if agent_username:
        overrides["username"] = agent_username
    if agent_password:
        overrides["password"] = agent_password

    return Config(**overrides)


def save_config(config: Config, config_path: Optional[Path | str] = None) -> None:
    """保存配置（password 不会持久化到文件）

    Raises:
        OSError: 目标目录无法创建或文件无法写入。
    """
    config_path = normalize_config_path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(exclude_none=True, exclude={"password"})
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)

    # 设置文件权限为 600 (仅所有者可读写)
    os.chmod(config_path, 0o600)
