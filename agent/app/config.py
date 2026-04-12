"""
配置管理模块
"""
import json
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """Agent 配置"""
    model_config = ConfigDict(extra="ignore")

    server_url: str = "ws://localhost:8000"
    # 新的 token 字段（推荐）
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    username: Optional[str] = None
    # 旧字段（向后兼容）
    token: Optional[str] = None
    # PTY 配置
    command: str = "/bin/bash"
    shell_mode: bool = False
    # 连接配置
    auto_reconnect: bool = True
    max_retries: int = 5
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


def load_config(config_path: Optional[Path | str] = None) -> Config:
    """加载配置

    优先级：配置文件 > 环境变量 > 默认值。
    环境变量用于 Docker 容器场景（无持久化配置文件时）。
    """
    config_path = normalize_config_path(config_path)

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return Config(**data)
        except json.JSONDecodeError:
            pass  # 配置文件格式错误，回退到环境变量

    # 无配置文件时，从环境变量回退
    server_url = os.environ.get("SERVER_URL")
    agent_token = os.environ.get("AGENT_TOKEN")
    overrides = {}
    if server_url:
        overrides["server_url"] = server_url
    if agent_token:
        overrides["access_token"] = agent_token
        overrides["token"] = agent_token

    return Config(**overrides)


def save_config(config: Config, config_path: Optional[Path | str] = None) -> None:
    """保存配置"""
    config_path = normalize_config_path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config.model_dump(exclude_none=True), f, indent=2)

    # 设置文件权限为 600 (仅所有者可读写)
    os.chmod(config_path, 0o600)
