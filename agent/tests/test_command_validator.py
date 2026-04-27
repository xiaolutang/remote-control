"""
B078: Agent 端命令白名单验证器单元测试（独立副本）
"""
import pytest

from app.command_validator import (
    validate_command,
    ALLOWED_COMMANDS,
    SAFE_GIT_SUBCOMMANDS,
    MAX_STDOUT_LEN,
    MAX_STDERR_LEN,
    DEFAULT_COMMAND_TIMEOUT,
)


class TestAgentValidateCommandAllowList:
    """Agent 端白名单内命令应通过验证。"""

    @pytest.mark.parametrize("cmd", sorted(ALLOWED_COMMANDS))
    def test_allowed_commands_pass(self, cmd):
        ok, reason = validate_command(cmd)
        assert ok, f"'{cmd}' 应该通过验证，但被拒绝: {reason}"
        assert reason == "OK"

    def test_ls_with_args(self):
        ok, _ = validate_command("ls -la /home")
        assert ok

    def test_cat_file(self):
        ok, _ = validate_command("cat README.md")
        assert ok

    def test_grep_pattern(self):
        ok, _ = validate_command("grep -r 'TODO' .")
        assert ok

    def test_git_status(self):
        ok, _ = validate_command("git status")
        assert ok

    def test_git_log(self):
        ok, _ = validate_command("git log --oneline -10")
        assert ok

    def test_pwd(self):
        ok, _ = validate_command("pwd")
        assert ok

    def test_whoami(self):
        ok, _ = validate_command("whoami")
        assert ok


class TestAgentValidateCommandDenyList:
    """不在白名单内的命令应被拒绝。"""

    def test_rm_rejected(self):
        ok, reason = validate_command("rm -rf /")
        assert not ok
        assert "白名单" in reason

    def test_sudo_rejected(self):
        ok, reason = validate_command("sudo ls")
        assert not ok

    def test_bash_rejected(self):
        ok, reason = validate_command("bash -c 'echo hi'")
        assert not ok

    def test_python_rejected(self):
        ok, reason = validate_command("python3 -c 'print(1)'")
        assert not ok

    def test_curl_rejected(self):
        ok, reason = validate_command("curl http://example.com")
        assert not ok


class TestAgentValidateCommandShellMeta:
    """包含 shell 元字符的命令应被拒绝。"""

    def test_semicolon(self):
        ok, reason = validate_command("ls; rm -rf /")
        assert not ok
        assert "元字符" in reason

    def test_pipe(self):
        ok, reason = validate_command("ls | grep foo")
        assert not ok
        assert "元字符" in reason

    def test_backtick(self):
        ok, reason = validate_command("echo `whoami`")
        assert not ok
        assert "元字符" in reason

    def test_command_substitution(self):
        ok, reason = validate_command("echo $(whoami)")
        assert not ok
        assert "元字符" in reason

    def test_redirect(self):
        ok, reason = validate_command("echo hi > file.txt")
        assert not ok
        assert "元字符" in reason


class TestAgentValidateCommandSensitivePaths:
    """包含敏感路径的命令应被拒绝。"""

    def test_etc_shadow(self):
        ok, reason = validate_command("cat /etc/shadow")
        assert not ok
        assert "敏感路径" in reason

    def test_ssh_id_keyfile(self):
        ok, reason = validate_command("cat .ssh/id_")
        assert not ok
        assert "敏感路径" in reason

    def test_dot_env(self):
        ok, reason = validate_command("cat .env")
        assert not ok
        assert "敏感路径" in reason

    def test_pem_file(self):
        ok, reason = validate_command("cat key.pem")
        assert not ok
        assert "敏感路径" in reason


class TestAgentValidateCommandGitSubcommands:
    """git 子命令验证。"""

    @pytest.mark.parametrize("subcmd", sorted(SAFE_GIT_SUBCOMMANDS))
    def test_safe_git_subcommands_pass(self, subcmd):
        ok, reason = validate_command(f"git {subcmd}")
        assert ok

    def test_git_without_subcommand_rejected(self):
        ok, reason = validate_command("git")
        assert not ok
        assert "子命令" in reason

    def test_git_push_rejected(self):
        ok, reason = validate_command("git push")
        assert not ok
        assert "安全子命令" in reason


class TestAgentValidateCommandFindDangerous:
    """find 命令危险操作检测。"""

    def test_find_exec_rejected(self):
        ok, reason = validate_command("find . -name foo -exec rm {} +")
        assert not ok
        assert "修改性操作" in reason

    def test_find_delete_rejected(self):
        ok, reason = validate_command("find . -name '*.tmp' -delete")
        assert not ok

    def test_find_normal_pass(self):
        ok, _ = validate_command("find . -name '*.py' -type f")
        assert ok


class TestAgentValidateCommandEdgeCases:
    """边界情况测试。"""

    def test_empty_command(self):
        ok, reason = validate_command("")
        assert not ok
        assert "不能为空" in reason

    def test_whitespace_only(self):
        ok, reason = validate_command("   ")
        assert not ok

    def test_invalid_quoting(self):
        ok, reason = validate_command("echo 'unclosed")
        assert not ok

    def test_constants(self):
        assert MAX_STDOUT_LEN == 8192
        assert MAX_STDERR_LEN == 4096
        assert DEFAULT_COMMAND_TIMEOUT == 10
