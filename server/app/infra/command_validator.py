"""
B078: 命令白名单验证器（Server 端）。

白名单定义从 shared/command_whitelist.json 加载，与 Agent 端共享同一份配置源。

三重防护：
1. 白名单：只有 ALLOWED_COMMANDS 中的命令允许执行
2. shell 元字符拦截：禁止 ;|&$`\\>> 等元字符（B122: 增加 | 管道符拦截）
3. 敏感路径过滤：禁止访问 /etc/shadow、.ssh、.env 等
"""
import json
import os
import re
import shlex
from pathlib import Path

# ---------------------------------------------------------------------------
# 从 shared/command_whitelist.json 加载白名单配置
# 优先使用 SHARED_DIR 环境变量，fallback 到相对路径（4 层上级 → 项目根）
# ---------------------------------------------------------------------------
_SHARED_ROOT = os.environ.get("SHARED_DIR", str(Path(__file__).resolve().parent.parent.parent.parent / "shared"))
_WHITELIST_PATH = Path(_SHARED_ROOT) / "command_whitelist.json"


def _load_whitelist() -> dict:
    """加载白名单 JSON 配置文件。加载失败时抛出 RuntimeError，不静默降级。"""
    try:
        with open(_WHITELIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            f"command_whitelist.json 未找到: {_WHITELIST_PATH}。"
            "请确保 shared/command_whitelist.json 存在。"
        )
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"command_whitelist.json 格式错误: {e}。请检查 JSON 语法。"
        )


_CFG = _load_whitelist()

ALLOWED_COMMANDS = frozenset(_CFG["allowed_commands"])
SAFE_GIT_SUBCOMMANDS = frozenset(_CFG["safe_git_subcommands"])

_SENSITIVE_PATHS = re.compile(_CFG["sensitive_paths_pattern"])
# 人类可读的敏感路径摘要（从 _SENSITIVE_PATHS 同步维护，供 SYSTEM_PROMPT 引用）
SENSITIVE_PATH_DISPLAY = "/etc/passwd、/etc/shadow、/etc/ssh、/root/.ssh、/proc/self、.ssh、.env、.pem、.key"
_SHELL_META = re.compile(_CFG["shell_meta_pattern"])
_FIND_DANGEROUS = frozenset(_CFG["find_dangerous_options"])

MAX_STDOUT_LEN = _CFG["max_stdout_len"]
MAX_STDERR_LEN = _CFG["max_stderr_len"]
DEFAULT_COMMAND_TIMEOUT = _CFG["default_command_timeout"]
MAX_COMMAND_RATE_PER_MINUTE = 60  # 每会话每分钟（server 端特有常量）


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
