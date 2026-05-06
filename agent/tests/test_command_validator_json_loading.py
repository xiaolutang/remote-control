"""
S063: command_validator JSON 加载测试（agent 端）。

验证：
1. JSON 文件缺失时抛出明确 RuntimeError
2. JSON 文件格式错误时抛出明确 RuntimeError
3. Agent 端不含 SENSITIVE_PATH_DISPLAY 和 MAX_COMMAND_RATE_PER_MINUTE
4. PyInstaller 打包模式下 sys._MEIPASS 路径定位
5. 源码运行模式下路径定位
6. PyInstaller 打包后 JSON 文件可达
"""
import importlib
import json
from pathlib import Path
from unittest import mock

import pytest


class TestAgentJsonLoadErrors:
    """agent 端 JSON 加载失败时的错误处理。

    每个测试在验证异常后会重新加载模块恢复正常状态，
    避免后续测试引用到被污染的模块级变量。
    """

    @pytest.fixture(autouse=True)
    def _restore_module(self):
        """每个测试后重新加载模块恢复正常状态。"""
        yield
        import app.security.command_validator as cv_mod
        importlib.reload(cv_mod)

    def test_missing_json_raises_runtime_error(self):
        """JSON 文件不存在时抛出 RuntimeError，包含文件路径信息。"""
        with mock.patch("builtins.open", side_effect=FileNotFoundError("not found")):
            import app.security.command_validator as cv_mod
            with pytest.raises(RuntimeError, match="command_whitelist.json 未找到"):
                importlib.reload(cv_mod)

    def test_invalid_json_raises_runtime_error(self):
        """JSON 格式错误时抛出 RuntimeError，包含语法错误信息。"""
        bad_json = "{ invalid json"
        with mock.patch("builtins.open", mock.mock_open(read_data=bad_json)):
            import app.security.command_validator as cv_mod
            with pytest.raises(RuntimeError, match="command_whitelist.json 格式错误"):
                importlib.reload(cv_mod)

    def test_missing_required_key_raises_key_error(self):
        """JSON 缺少必需字段时加载失败。"""
        incomplete_json = '{"allowed_commands": ["ls"]}'
        with mock.patch("builtins.open", mock.mock_open(read_data=incomplete_json)):
            import app.security.command_validator as cv_mod
            with pytest.raises(KeyError):
                importlib.reload(cv_mod)


class TestAgentNoServerSpecificConstants:
    """验证 agent 端不包含 server 端特有常量。"""

    def test_no_sensitive_path_display(self):
        """agent 端不应有 SENSITIVE_PATH_DISPLAY。"""
        import app.security.command_validator as cv_mod
        assert not hasattr(cv_mod, "SENSITIVE_PATH_DISPLAY")

    def test_no_max_command_rate(self):
        """agent 端不应有 MAX_COMMAND_RATE_PER_MINUTE。"""
        import app.security.command_validator as cv_mod
        assert not hasattr(cv_mod, "MAX_COMMAND_RATE_PER_MINUTE")


class TestAgentWhitelistLoadedFromJson:
    """验证白名单从 JSON 正确加载。"""

    def test_allowed_commands_from_json(self):
        """ALLOWED_COMMANDS 的内容与 JSON 中定义一致。"""
        from app.security.command_validator import ALLOWED_COMMANDS
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert ALLOWED_COMMANDS == frozenset(cfg["allowed_commands"])

    def test_git_subcommands_from_json(self):
        """SAFE_GIT_SUBCOMMANDS 的内容与 JSON 中定义一致。"""
        from app.security.command_validator import SAFE_GIT_SUBCOMMANDS
        json_path = Path(__file__).resolve().parent.parent.parent / "shared" / "command_whitelist.json"
        with open(json_path) as f:
            cfg = json.load(f)
        assert SAFE_GIT_SUBCOMMANDS == frozenset(cfg["safe_git_subcommands"])

    def test_constants_from_json(self):
        """共享常量从 JSON 正确加载。"""
        from app.security.command_validator import (
            MAX_STDOUT_LEN,
            MAX_STDERR_LEN,
            DEFAULT_COMMAND_TIMEOUT,
        )
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


class TestAgentPyInstallerPathResolution:
    """验证 PyInstaller 打包模式下的路径定位逻辑。"""

    def test_find_whitelist_path_source_mode(self):
        """源码运行模式：路径指向 shared/command_whitelist.json。"""
        from app.security.command_validator import _find_whitelist_path
        # 非打包模式，路径应指向 project_root/shared/command_whitelist.json
        path = _find_whitelist_path()
        assert path.name == "command_whitelist.json"
        assert "shared" in str(path)

    def test_find_whitelist_path_pyinstaller_mode(self):
        """PyInstaller 打包模式：路径指向 sys._MEIPASS/command_whitelist.json。"""
        import sys as _sys
        _orig_frozen = getattr(_sys, 'frozen', None)
        _orig_meipass = getattr(_sys, '_MEIPASS', None)
        try:
            _sys.frozen = True
            _sys._MEIPASS = "/tmp/_MEI12345"
            import app.security.command_validator as cv_mod
            path = cv_mod._find_whitelist_path()
            assert str(path) == "/tmp/_MEI12345/command_whitelist.json"
        finally:
            if _orig_frozen is None:
                delattr(_sys, 'frozen')
            else:
                _sys.frozen = _orig_frozen
            if _orig_meipass is None:
                delattr(_sys, '_MEIPASS')
            else:
                _sys._MEIPASS = _orig_meipass


class TestAgentSpecIncludesWhitelist:
    """验证 rc-agent.spec 包含 command_whitelist.json。"""

    def test_spec_includes_whitelist(self):
        """rc-agent.spec 的 datas 字段应包含 command_whitelist.json。"""
        spec_path = Path(__file__).resolve().parent.parent / "rc-agent.spec"
        with open(spec_path) as f:
            content = f.read()
        assert "command_whitelist.json" in content
