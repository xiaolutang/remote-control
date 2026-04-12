"""
配置管理测试
"""
import os
import tempfile
import pytest

from app.config import Config, load_config


class TestConfigEnvFallback:
    """环境变量回退测试（Docker 容器场景）"""

    @pytest.fixture
    def empty_config_dir(self):
        """空临时目录（无 config.json）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_server_url_from_env(self, empty_config_dir):
        """无配置文件时 SERVER_URL 环境变量生效"""
        config_path = os.path.join(empty_config_dir, "config.json")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("SERVER_URL", "ws://server:8000")
            config = load_config(config_path)
        assert config.server_url == "ws://server:8000"

    def test_agent_token_from_env(self, empty_config_dir):
        """无配置文件时 AGENT_TOKEN 环境变量映射到 access_token"""
        config_path = os.path.join(empty_config_dir, "config.json")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AGENT_TOKEN", "my-secret-token")
            config = load_config(config_path)
        assert config.access_token == "my-secret-token"
        assert config.token == "my-secret-token"  # 向后兼容

    def test_both_env_vars(self, empty_config_dir):
        """同时设置两个环境变量"""
        config_path = os.path.join(empty_config_dir, "config.json")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("SERVER_URL", "ws://server:8000")
            mp.setenv("AGENT_TOKEN", "tok-123")
            config = load_config(config_path)
        assert config.server_url == "ws://server:8000"
        assert config.get_access_token() == "tok-123"

    def test_config_file_overrides_env(self, empty_config_dir):
        """有配置文件时忽略环境变量"""
        import json
        config_path = os.path.join(empty_config_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump({"server_url": "wss://from-file.example.com"}, f)
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("SERVER_URL", "ws://from-env:8000")
            config = load_config(config_path)
        assert config.server_url == "wss://from-file.example.com"

    def test_no_env_no_file_returns_defaults(self, empty_config_dir):
        """无环境变量无配置文件时返回默认值"""
        config_path = os.path.join(empty_config_dir, "config.json")
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("SERVER_URL", raising=False)
            mp.delenv("AGENT_TOKEN", raising=False)
            config = load_config(config_path)
        assert config.server_url == "ws://localhost:8000"
        assert config.access_token is None
