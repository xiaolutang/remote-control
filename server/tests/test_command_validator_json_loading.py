"""
S063: command_validator JSON 加载测试（server 端）。

验证：
1. JSON 文件缺失时抛出明确 RuntimeError
2. JSON 文件格式错误时抛出明确 RuntimeError
3. SENSITIVE_PATH_DISPLAY 和 MAX_COMMAND_RATE_PER_MINUTE 保留在 server 端
4. JSON 文件可通过 Docker COPY 到达
"""
import json
import importlib
from pathlib import Path
from unittest import mock

import pytest

from app.infra.command_validator import (
    validate_command,
    ALLOWED_COMMANDS,
    SAFE_GIT_SUBCOMMANDS,
    SENSITIVE_PATH_DISPLAY,
    MAX_COMMAND_RATE_PER_MINUTE,
    MAX_STDOUT_LEN,
    MAX_STDERR_LEN,
    DEFAULT_COMMAND_TIMEOUT,
)


class TestServerJsonLoadErrors:
    """server 端 JSON 加载失败时的错误处理。"""

    def test_missing_json_raises_runtime_error(self):
        """JSON 文件不存在时抛出 RuntimeError，包含文件路径信息。"""
        with mock.patch("builtins.open", side_effect=FileNotFoundError("not found")):
            import app.infra.command_validator as cv_mod
            with pytest.raises(RuntimeError, match="command_whitelist.json 未找到"):
                importlib.reload(cv_mod)

    def test_invalid_json_raises_runtime_error(self):
        """JSON 格式错误时抛出 RuntimeError，包含语法错误信息。"""
        bad_json = "{ invalid json"
        with mock.patch("builtins.open", mock.mock_open(read_data=bad_json)):
            import app.infra.command_validator as cv_mod
            with pytest.raises(RuntimeError, match="command_whitelist.json 格式错误"):
                importlib.reload(cv_mod)

    def test_missing_required_key_raises_key_error(self):
        """JSON 缺少必需字段时加载失败。"""
        incomplete_json = '{"allowed_commands": ["ls"]}'
        with mock.patch("builtins.open", mock.mock_open(read_data=incomplete_json)):
            import app.infra.command_validator as cv_mod
            with pytest.raises(KeyError):
                importlib.reload(cv_mod)


class TestServerSpecificConstants:
    """验证 server 端特有常量保留在 server 端。"""

    def test_sensitive_path_display_exists(self):
        assert isinstance(SENSITIVE_PATH_DISPLAY, str)
        assert "/etc/shadow" in SENSITIVE_PATH_DISPLAY
        assert ".env" in SENSITIVE_PATH_DISPLAY

    def test_max_command_rate_per_minute_exists(self):
        assert MAX_COMMAND_RATE_PER_MINUTE == 60

    def test_max_command_rate_not_in_json(self):
        """MAX_COMMAND_RATE_PER_MINUTE 不在 JSON 中，是 server 端硬编码常量。"""
        # server 运行时 CWD 是 server/，JSON 在 ../shared/
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert "max_command_rate_per_minute" not in cfg

    def test_sensitive_path_display_not_in_json(self):
        """SENSITIVE_PATH_DISPLAY 不在 JSON 中，是 server 端硬编码常量。"""
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert "sensitive_path_display" not in cfg


class TestWhitelistLoadedFromJson:
    """验证白名单从 JSON 正确加载。"""

    def test_allowed_commands_from_json(self):
        """ALLOWED_COMMANDS 的内容与 JSON 中定义一致。"""
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert ALLOWED_COMMANDS == frozenset(cfg["allowed_commands"])

    def test_git_subcommands_from_json(self):
        """SAFE_GIT_SUBCOMMANDS 的内容与 JSON 中定义一致。"""
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert SAFE_GIT_SUBCOMMANDS == frozenset(cfg["safe_git_subcommands"])

    def test_constants_from_json(self):
        """共享常量从 JSON 正确加载。"""
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert MAX_STDOUT_LEN == cfg["max_stdout_len"] == 8192
        assert MAX_STDERR_LEN == cfg["max_stderr_len"] == 4096
        assert DEFAULT_COMMAND_TIMEOUT == cfg["default_command_timeout"] == 10

    def test_json_file_exists_at_expected_path(self):
        """JSON 文件在预期的 shared/ 路径下存在。"""
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        assert json_path.exists(), f"command_whitelist.json 不在 {json_path}"

    def test_dockerfile_copies_shared(self):
        """验证 Dockerfile 中有 COPY shared 指令。"""
        dockerfile_path = Path(__file__).resolve().parent.parent.parent / "deploy" / "server.Dockerfile"
        with open(dockerfile_path) as f:
            content = f.read()
        assert "COPY shared ./shared" in content
