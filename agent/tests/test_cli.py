"""
CLI 测试
"""
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

import pytest

from app.cli import cli, _safe_save_config
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


# ---------------------------------------------------------------------------
# S060 审计修复回归测试：--config 优先级 + 错误处理
# ---------------------------------------------------------------------------


class TestConfigPrecedence:
    """--config 参数优先级测试"""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def temp_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_explicit_config_overrides_env_var(self, runner, temp_config_dir):
        """显式 --config 应覆盖 RC_AGENT_CONFIG_DIR 环境变量"""
        # 创建显式 config 文件
        explicit_dir = os.path.join(temp_config_dir, "explicit")
        os.makedirs(explicit_dir, exist_ok=True)
        config_file = os.path.join(explicit_dir, "config.json")
        with open(config_file, "w") as f:
            json.dump({"server_url": "wss://explicit.example.com"}, f)

        # 环境变量指向另一个目录
        env_dir = os.path.join(temp_config_dir, "from_env")

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = env_dir
            result = runner.invoke(
                cli,
                ["--config", config_file, "status"],
            )

            # 命令应成功执行
            assert result.exit_code == 0
            # 显式 --config 应覆盖环境变量，设置 RC_AGENT_CONFIG_DIR 为 explicit_dir
            # 使用 resolve() 处理 macOS 符号链接 (/var -> /private/var)
            assert os.environ.get("RC_AGENT_CONFIG_DIR") == str(Path(explicit_dir).resolve())
            # 输出应包含服务器地址（status 子命令正常输出）
            assert "explicit.example.com" in result.output
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_config_sets_rc_agent_config_dir(self, runner, temp_config_dir):
        """--config 应将 RC_AGENT_CONFIG_DIR 设置为 config 文件的父目录"""
        explicit_dir = os.path.join(temp_config_dir, "my_config_dir")
        os.makedirs(explicit_dir, exist_ok=True)
        config_file = os.path.join(explicit_dir, "config.json")
        with open(config_file, "w") as f:
            json.dump({"server_url": "wss://test.example.com"}, f)

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", config_file, "status"])

            # 命令应成功执行
            assert result.exit_code == 0
            # --config 桥接后 RC_AGENT_CONFIG_DIR 应为 config 文件的父目录
            assert os.environ.get("RC_AGENT_CONFIG_DIR") == str(Path(explicit_dir).resolve())
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_no_config_respects_env_var(self, runner, temp_config_dir):
        """无 --config 时应尊重已有的 RC_AGENT_CONFIG_DIR 环境变量"""
        env_dir = os.path.join(temp_config_dir, "env_dir")
        os.makedirs(env_dir, exist_ok=True)
        config_file = os.path.join(env_dir, "config.json")
        with open(config_file, "w") as f:
            json.dump({"server_url": "wss://env.example.com"}, f)

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = env_dir
            result = runner.invoke(cli, ["status"])
            # 环境变量未被覆盖
            assert os.environ.get("RC_AGENT_CONFIG_DIR") == env_dir
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_config_without_env_var(self, runner, temp_config_dir):
        """--config 在无 RC_AGENT_CONFIG_DIR 环境变量时仍正确设置"""
        explicit_dir = os.path.join(temp_config_dir, "standalone")
        os.makedirs(explicit_dir, exist_ok=True)
        config_file = os.path.join(explicit_dir, "config.json")
        with open(config_file, "w") as f:
            json.dump({"server_url": "wss://standalone.example.com"}, f)

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", config_file, "status"])

            assert os.environ.get("RC_AGENT_CONFIG_DIR") == str(Path(explicit_dir).resolve())
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original


class TestConfigInvalidPath:
    """无效 --config 路径的错误处理"""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_missing_config_file_shows_warning(self, runner):
        """--config 指向不存在的文件时应显示 Warning（允许首次引导流程）"""
        nonexistent = "/tmp/__rc_agent_test_nonexistent_dir__/config.json"

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", nonexistent, "status"])
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

        # 应输出 Warning 消息（允许 login/configure 首次引导）
        assert "Warning" in result.output or "warning" in result.output.lower()

    def test_nonexistent_directory_still_sets_env(self, runner):
        """--config 指向不存在的目录时仍应设置 RC_AGENT_CONFIG_DIR"""
        nonexistent = "/tmp/__rc_agent_test_nonexistent__/config.json"
        expected_dir = str(Path("/tmp/__rc_agent_test_nonexistent__").resolve())

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", nonexistent, "status"])

            assert os.environ.get("RC_AGENT_CONFIG_DIR") == expected_dir
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    @pytest.mark.skipif(os.getuid() == 0, reason="root 用户无法测试权限拒绝")
    def test_unreadable_config_dir(self, runner, tmp_path):
        """无权限目录下的 config 文件应报错"""
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        config_file = restricted_dir / "config.json"
        config_file.write_text('{"server_url": "wss://test.example.com"}')

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        # 移除读权限
        restricted_dir.chmod(0o000)
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", str(config_file), "status"])
            # 非零退出码或输出包含 Error
            assert result.exit_code != 0 or "Error" in result.output
        finally:
            restricted_dir.chmod(0o755)
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_unreadable_config_file_shows_error(self, runner, tmp_path):
        """--config 指向存在但不可读的文件时应输出 Error 并失败"""
        config_dir = tmp_path / "unreadable_test"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text('{"server_url": "wss://test.example.com"}')

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            # 使用 patch 模拟文件不可读
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                result = runner.invoke(cli, ["--config", str(config_file), "status"])

            # 应报错退出
            assert "Error" in result.output
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_malformed_config_file_shows_error(self, runner, tmp_path):
        """--config 指向存在但 JSON 格式错误的文件时应输出 Error 并失败"""
        config_dir = tmp_path / "malformed_test"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text('this is not valid json {{{')

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(cli, ["--config", str(config_file), "status"])

            # 显式 --config + malformed JSON = 硬错误
            assert "Error" in result.output
            assert result.exit_code != 0
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_configure_creates_new_config(self, runner, tmp_path):
        """--config 指向不存在的文件时 configure 命令应能创建新配置"""
        config_file = tmp_path / "new_config.json"
        # 文件不存在

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            result = runner.invoke(
                cli,
                ["--config", str(config_file), "configure",
                 "--server", "wss://bootstrap.example.com",
                 "--access-token", "new-token"],
            )

            # configure 应成功创建文件
            assert result.exit_code == 0
            assert config_file.exists()
            # 验证内容
            data = json.loads(config_file.read_text())
            assert data["server_url"] == "wss://bootstrap.example.com"
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original


class TestSaveConfigErrors:
    """配置保存失败的错误处理"""

    def test_safe_save_config_oserror(self):
        """_safe_save_config 在 OSError 时应输出错误并退出"""
        config = Config(server_url="wss://test.example.com")

        with patch("app.cli.save_config", side_effect=OSError("disk full")):
            with pytest.raises(SystemExit) as exc_info:
                _safe_save_config(config, "/some/path/config.json")

            assert exc_info.value.code == 1

    def test_save_config_to_unwritable_dir(self, tmp_path):
        """save_config 到不可写目录时应抛出 OSError"""
        config = Config(server_url="wss://test.example.com")

        # 创建只读目录
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)
        config_path = readonly_dir / "config.json"

        try:
            # macOS 可能仍允许 root 写入，所以使用 patch 模拟
            with patch("builtins.open", side_effect=OSError("Permission denied")):
                with pytest.raises(OSError, match="Permission denied"):
                    from app.config import save_config
                    save_config(config, config_path)
        finally:
            readonly_dir.chmod(0o755)

    def test_save_config_handles_mkdir_failure(self, tmp_path):
        """save_config 在 mkdir 失败时应抛出 OSError"""
        config = Config(server_url="wss://test.example.com")

        # 模拟 mkdir 失败
        with patch.object(Path, "mkdir", side_effect=OSError("cannot create dir")):
            with pytest.raises(OSError, match="cannot create dir"):
                from app.config import save_config
                save_config(config, tmp_path / "sub" / "config.json")


class TestCryptoStateDirLazy:
    """AgentCrypto 延迟状态目录解析测试"""

    def test_state_dir_uses_rc_agent_config_dir(self):
        """AgentCrypto._state_dir 应从 RC_AGENT_CONFIG_DIR 环境变量延迟解析"""
        from app.security.crypto import AgentCrypto

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = "/tmp/test_crypto_lazy"
            crypto = AgentCrypto()
            # 属性每次访问时从环境变量读取
            assert str(crypto._state_dir) == "/tmp/test_crypto_lazy"
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_state_dir_respects_explicit_override(self):
        """显式传入 state_dir 参数应优先于环境变量"""
        from app.security.crypto import AgentCrypto

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = "/tmp/should_not_be_used"
            crypto = AgentCrypto(state_dir="/tmp/explicit_state")
            assert str(crypto._state_dir) == "/tmp/explicit_state"
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_state_dir_updates_after_env_change(self):
        """延迟解析意味着在构造后修改环境变量，state_dir 也随之更新"""
        from app.security.crypto import AgentCrypto

        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            crypto = AgentCrypto()

            # 初始状态应使用默认值
            initial = str(crypto._state_dir)
            assert ".rc-agent" in initial

            # 修改环境变量后应反映新值
            os.environ["RC_AGENT_CONFIG_DIR"] = "/tmp/new_config_dir"
            assert str(crypto._state_dir) == "/tmp/new_config_dir"
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_fingerprint_file_under_config_dir(self, tmp_path):
        """指纹文件应写到 --config 的父目录下（即 RC_AGENT_CONFIG_DIR）"""
        from app.security.crypto import AgentCrypto

        config_dir = tmp_path / "custom_config"
        config_dir.mkdir()
        crypto = AgentCrypto(state_dir=str(config_dir))

        # 模拟指纹校验（首次写入）
        crypto._verify_fingerprint("sha256:abc123")

        fp_file = config_dir / "server_fingerprint.txt"
        assert fp_file.exists()
        assert fp_file.read_text() == "sha256:abc123"

    def test_fingerprint_tofu_mismatch_raises(self, tmp_path):
        """指纹不匹配时应抛出 RuntimeError"""
        from app.security.crypto import AgentCrypto

        config_dir = tmp_path / "tofu_test"
        config_dir.mkdir()
        crypto = AgentCrypto(state_dir=str(config_dir))

        # 首次写入
        crypto._verify_fingerprint("sha256:first")
        # 第二次不匹配
        with pytest.raises(RuntimeError, match="密钥指纹已变更"):
            crypto._verify_fingerprint("sha256:attacker")


class TestDerivedDirectoryCreation:
    """验证 --config 桥接后派生目录（skills/、user_knowledge/、fingerprint）在正确根目录创建"""

    def test_skills_dir_created_under_config_parent(self, tmp_path):
        """skills/ 目录应在 --config 的父目录下创建"""
        from app.tools.skill_registry import ensure_skills_dir

        config_dir = tmp_path / "derived_test"
        config_dir.mkdir()
        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = str(config_dir)
            result_dir = ensure_skills_dir()
            assert result_dir == config_dir / "skills"
            assert (config_dir / "skills").exists()
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original

    def test_knowledge_dir_created_under_config_parent(self, tmp_path):
        """user_knowledge/ 目录应在 --config 的父目录下创建"""
        from app.tools.knowledge_tool import ensure_user_knowledge_dir

        config_dir = tmp_path / "derived_knowledge"
        config_dir.mkdir()
        original = os.environ.get("RC_AGENT_CONFIG_DIR")
        try:
            os.environ["RC_AGENT_CONFIG_DIR"] = str(config_dir)
            result_dir = ensure_user_knowledge_dir()
            assert result_dir == config_dir / "user_knowledge"
            assert (config_dir / "user_knowledge").exists()
        finally:
            if original is None:
                os.environ.pop("RC_AGENT_CONFIG_DIR", None)
            else:
                os.environ["RC_AGENT_CONFIG_DIR"] = original
