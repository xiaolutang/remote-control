"""
B078: 命令白名单验证器。

Server 端和 Agent 端双重验证共用。Agent 端在 agent/app/command_validator.py
维护一份独立副本（Agent 不依赖 server 包）。

三重防护：
1. 白名单：只有 ALLOWED_COMMANDS 中的命令允许执行
2. shell 元字符拦截：禁止 ;|&$`\\>> 等元字符
3. 敏感路径过滤：禁止访问 /etc/shadow、.ssh、.env 等
"""
import re
import shlex

ALLOWED_COMMANDS = frozenset({
    'ls', 'dir', 'tree',
    'cat', 'head', 'tail', 'less', 'more',
    'find', 'grep', 'rg', 'ag', 'fd',
    'file', 'stat', 'wc', 'du', 'df',
    'pwd', 'whoami', 'hostname', 'uname', 'id',
    'which', 'command', 'type', 'whereis',
    'echo', 'date',
})

SAFE_GIT_SUBCOMMANDS = frozenset({
    'log', 'status', 'branch', 'diff', 'show',
    'remote', 'tag', 'describe', 'rev-parse',
    'ls-files', 'ls-tree',
})

_SENSITIVE_PATHS = re.compile(
    r'(/etc/passwd\b|/etc/shadow\b|/etc/ssh\b|/root/\.ssh\b|/proc/self\b|'
    r'\.ssh/id_|\.ssh/known_hosts\b|\.ssh/authorized_keys\b|'
    r'\.env\b|\.pem\b|\.key\b)',
    re.IGNORECASE,
)
_SHELL_META = re.compile(r'[;|&$`\\]|>>|>')
_FIND_DANGEROUS = {'-exec', '-delete', '-fls', '-ok', '-fprint'}

MAX_STDOUT_LEN = 4096
MAX_STDERR_LEN = 4096
DEFAULT_COMMAND_TIMEOUT = 10  # 秒
MAX_COMMAND_RATE_PER_MINUTE = 10  # 每会话每分钟


def validate_command(command: str) -> tuple[bool, str]:
    """验证命令是否允许执行。

    Returns:
        (True, "OK") 如果命令安全
        (False, reason) 如果命令被拒绝
    """
    cmd = command.strip()
    if not cmd:
        return False, "命令不能为空"
    if _SENSITIVE_PATHS.search(cmd):
        return False, "命令包含敏感路径，禁止访问"
    if _SHELL_META.search(cmd):
        return False, "命令包含禁止的 shell 元字符"
    if '$(' in cmd or '`' in cmd:
        return False, "禁止命令替换"
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return False, "命令格式无效"
    if not parts:
        return False, "命令不能为空"
    base = parts[0]
    if base == 'git':
        if len(parts) < 2:
            return False, "git 需要子命令"
        if parts[1] not in SAFE_GIT_SUBCOMMANDS:
            return False, f"git {parts[1]} 不在安全子命令列表内"
        return True, "OK"
    if base == 'find':
        if set(parts) & _FIND_DANGEROUS:
            return False, "find 不允许修改性操作"
    if base not in ALLOWED_COMMANDS:
        return False, f"命令 '{base}' 不在白名单内"
    return True, "OK"
