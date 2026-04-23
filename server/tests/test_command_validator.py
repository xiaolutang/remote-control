"""
B078: Server 端命令白名单验证器单元测试
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


class TestValidateCommandAllowList:
    """白名单内命令应通过验证。"""

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

    def test_find_name(self):
        ok, _ = validate_command("find . -name '*.py'")
        assert ok

    def test_pwd(self):
        ok, _ = validate_command("pwd")
        assert ok

    def test_whoami(self):
        ok, _ = validate_command("whoami")
        assert ok

    def test_uname_a(self):
        ok, _ = validate_command("uname -a")
        assert ok

    def test_echo_text(self):
        ok, _ = validate_command("echo hello world")
        assert ok

    def test_date(self):
        ok, _ = validate_command("date")
        assert ok

    def test_git_status(self):
        ok, _ = validate_command("git status")
        assert ok

    def test_git_log(self):
        ok, _ = validate_command("git log --oneline -10")
        assert ok

    def test_git_branch(self):
        ok, _ = validate_command("git branch -a")
        assert ok

    def test_git_diff(self):
        ok, _ = validate_command("git diff HEAD~1")
        assert ok

    def test_git_show(self):
        ok, _ = validate_command("git show abc123")
        assert ok

    def test_git_remote(self):
        ok, _ = validate_command("git remote -v")
        assert ok

    def test_git_tag(self):
        ok, _ = validate_command("git tag")
        assert ok

    def test_git_describe(self):
        ok, _ = validate_command("git describe --tags")
        assert ok

    def test_git_rev_parse(self):
        ok, _ = validate_command("git rev-parse HEAD")
        assert ok

    def test_git_ls_files(self):
        ok, _ = validate_command("git ls-files")
        assert ok

    def test_git_ls_tree(self):
        ok, _ = validate_command("git ls-tree HEAD")
        assert ok

    def test_du_sh(self):
        ok, _ = validate_command("du -sh .")
        assert ok

    def test_df_h(self):
        ok, _ = validate_command("df -h")
        assert ok

    def test_wc_l(self):
        ok, _ = validate_command("wc -l file.txt")
        assert ok

    def test_stat_file(self):
        ok, _ = validate_command("stat file.txt")
        assert ok

    def test_file_type(self):
        ok, _ = validate_command("file binary")
        assert ok

    def test_which_command(self):
        ok, _ = validate_command("which python3")
        assert ok

    def test_whereis_command(self):
        ok, _ = validate_command("whereis python3")
        assert ok

    def test_head_n(self):
        ok, _ = validate_command("head -20 file.log")
        assert ok

    def test_tail_n(self):
        ok, _ = validate_command("tail -20 file.log")
        assert ok

    def test_tree_L(self):
        ok, _ = validate_command("tree -L 2")
        assert ok

    def test_rg_pattern(self):
        ok, _ = validate_command("rg 'pattern'")
        assert ok

    def test_fd_pattern(self):
        ok, _ = validate_command("fd '.py'")
        assert ok

    def test_id(self):
        ok, _ = validate_command("id")
        assert ok

    def test_hostname(self):
        ok, _ = validate_command("hostname")
        assert ok


class TestValidateCommandDenyList:
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
        assert "白名单" in reason

    def test_python_rejected(self):
        ok, reason = validate_command("python3 -c 'print(1)'")
        assert not ok
        assert "白名单" in reason

    def test_curl_rejected(self):
        ok, reason = validate_command("curl http://example.com")
        assert not ok

    def test_wget_rejected(self):
        ok, reason = validate_command("wget http://example.com")
        assert not ok

    def test_ssh_rejected(self):
        ok, reason = validate_command("ssh user@host")
        assert not ok

    def test_nc_rejected(self):
        ok, reason = validate_command("nc -l 8080")
        assert not ok

    def test_chmod_rejected(self):
        ok, reason = validate_command("chmod 777 file")
        assert not ok

    def test_mkdir_rejected(self):
        ok, reason = validate_command("mkdir newdir")
        assert not ok

    def test_cp_rejected(self):
        ok, reason = validate_command("cp a b")
        assert not ok

    def test_mv_rejected(self):
        ok, reason = validate_command("mv a b")
        assert not ok


class TestValidateCommandShellMeta:
    """包含 shell 元字符的命令应被拒绝。"""

    def test_semicolon(self):
        ok, reason = validate_command("ls; rm -rf /")
        assert not ok
        assert "元字符" in reason

    def test_pipe(self):
        ok, reason = validate_command("ls | grep foo")
        assert not ok
        assert "元字符" in reason

    def test_ampersand(self):
        ok, reason = validate_command("ls &")
        assert not ok
        assert "元字符" in reason

    def test_dollar_sign(self):
        ok, reason = validate_command("echo $HOME")
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

    def test_redirect_write(self):
        ok, reason = validate_command("echo hi > file.txt")
        assert not ok
        assert "元字符" in reason

    def test_redirect_append(self):
        ok, reason = validate_command("echo hi >> file.txt")
        assert not ok
        assert "元字符" in reason

    def test_backslash(self):
        ok, reason = validate_command("ls\\ ")
        assert not ok
        assert "元字符" in reason


class TestValidateCommandSensitivePaths:
    """包含敏感路径的命令应被拒绝。"""

    def test_etc_shadow(self):
        ok, reason = validate_command("cat /etc/shadow")
        assert not ok
        assert "敏感路径" in reason

    def test_etc_ssh(self):
        ok, reason = validate_command("ls /etc/ssh")
        assert not ok
        assert "敏感路径" in reason

    def test_ssh_id_keyfile(self):
        ok, reason = validate_command("cat .ssh/id_")
        assert not ok
        assert "敏感路径" in reason

    def test_ssh_known_hosts(self):
        ok, reason = validate_command("cat .ssh/known_hosts")
        assert not ok
        assert "敏感路径" in reason

    def test_ssh_authorized_keys(self):
        ok, reason = validate_command("cat .ssh/authorized_keys")
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

    def test_key_file(self):
        ok, reason = validate_command("cat server.key")
        assert not ok
        assert "敏感路径" in reason

    def test_proc_self(self):
        ok, reason = validate_command("cat /proc/self/environ")
        assert not ok
        assert "敏感路径" in reason

    def test_root_ssh(self):
        ok, reason = validate_command("ls /root/.ssh")
        assert not ok
        assert "敏感路径" in reason

    def test_case_insensitive_env(self):
        ok, reason = validate_command("cat .ENV")
        assert not ok
        assert "敏感路径" in reason


class TestValidateCommandGitSubcommands:
    """git 子命令验证。"""

    @pytest.mark.parametrize("subcmd", sorted(SAFE_GIT_SUBCOMMANDS))
    def test_safe_git_subcommands_pass(self, subcmd):
        ok, reason = validate_command(f"git {subcmd}")
        assert ok, f"'git {subcmd}' 应该通过验证"

    def test_git_without_subcommand_rejected(self):
        ok, reason = validate_command("git")
        assert not ok
        assert "子命令" in reason

    def test_git_push_rejected(self):
        ok, reason = validate_command("git push")
        assert not ok
        assert "安全子命令" in reason

    def test_git_pull_rejected(self):
        ok, reason = validate_command("git pull")
        assert not ok

    def test_git_checkout_rejected(self):
        ok, reason = validate_command("git checkout main")
        assert not ok

    def test_git_reset_rejected(self):
        ok, reason = validate_command("git reset --hard")
        assert not ok

    def test_git_clean_rejected(self):
        ok, reason = validate_command("git clean -fd")
        assert not ok

    def test_git_commit_rejected(self):
        ok, reason = validate_command("git commit -m 'test'")
        assert not ok


class TestValidateCommandFindDangerous:
    """find 命令危险操作检测。"""

    def test_find_exec_rejected(self):
        ok, reason = validate_command("find . -name foo -exec rm {} +")
        assert not ok
        assert "修改性操作" in reason

    def test_find_delete_rejected(self):
        ok, reason = validate_command("find . -name '*.tmp' -delete")
        assert not ok
        assert "修改性操作" in reason

    def test_find_ok_rejected(self):
        ok, reason = validate_command("find . -name foo -ok rm {} +")
        assert not ok
        assert "修改性操作" in reason

    def test_find_normal_pass(self):
        ok, _ = validate_command("find . -name '*.py' -type f")
        assert ok

    def test_find_mtime_pass(self):
        ok, _ = validate_command("find . -mtime +7")
        assert ok


class TestValidateCommandEdgeCases:
    """边界情况测试。"""

    def test_empty_command(self):
        ok, reason = validate_command("")
        assert not ok
        assert "不能为空" in reason

    def test_whitespace_only(self):
        ok, reason = validate_command("   ")
        assert not ok
        assert "不能为空" in reason

    def test_leading_trailing_whitespace(self):
        ok, _ = validate_command("  ls  ")
        assert ok

    def test_invalid_quoting(self):
        ok, reason = validate_command("echo 'unclosed")
        assert not ok
        assert "格式无效" in reason

    def test_constants(self):
        assert MAX_STDOUT_LEN == 4096
        assert MAX_STDERR_LEN == 4096
        assert DEFAULT_COMMAND_TIMEOUT == 10
