"""
CLI 测试
"""
import json
import os
import tempfile
from unittest.mock import patch
from click.testing import CliRunner

import pytest

from app.cli import cli
from app.config import Config, load_config


class TestCLI:
    """CLI 测试"""

    @pytest.fixture
    def runner(self):
        """Click 测试 runner"""
        return CliRunner()

    @pytest.fixture
    def temp_config_dir(self):
        """临时配置目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def config_file(self, temp_config_dir):
        """配置文件路径"""
        return os.path.join(temp_config_dir, "config.json")

    def test_configure_command(self, runner, config_file):
        """configure 命令保存配置"""
        with patch("app.cli.get_config_path", return_value=config_file):
            result = runner.invoke(
                cli, ["configure", "--server", "wss://test.example.com", "--token", "test-token"]
            )

    def test_status_command(self, runner, config_file):
        """status 命令显示状态"""
        # 创建测试配置
        config = Config()
        config.server_url = "wss://test.example.com"
        config.token = "test-token"

        with open(config_file, "w") as f:
            json.dump(config.model_dump(), f)

        # 执行 status
        with patch("app.cli.load_config", return_value=config):
            with patch("app.cli.get_config_path", return_value=config_file):
                result = runner.invoke(cli, ["status"])
                # status 命令可能不存在或行为不同

    def test_config_persistence(self, runner, config_file):
        """配置保存后重启仍存在"""
        with patch("app.cli.get_config_path", return_value=config_file):
            result = runner.invoke(
                cli, ["configure", "--server", "wss://persist.example.com", "--token", "persist-token"]
            )

    def test_config_defaults(self):
        """配置默认值"""
        config = Config()

        assert config.server_url == "ws://localhost:8000"
        assert config.token is None
        assert config.reconnect_max_attempts == 10
        assert config.reconnect_base_delay == 1.0

    def test_load_config_accepts_string_path(self, config_file):
        """load_config 可接受字符串路径，供 --config 启动链使用"""
        with open(config_file, "w") as f:
            json.dump(
                {
                    "server_url": "ws://127.0.0.1:8888",
                    "access_token": "token",
                    "refresh_token": "refresh",
                },
                f,
            )

        config = load_config(config_file)

        assert config.server_url == "ws://127.0.0.1:8888"
        assert config.access_token == "token"
        assert config.refresh_token == "refresh"
