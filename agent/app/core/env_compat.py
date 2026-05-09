"""
macOS .app PATH 兼容层

解决 macOS .app 从 Finder/Launchpad 启动时继承 launchd 最小 PATH
(`/usr/bin:/bin:/usr/sbin:/sbin`)，不含 homebrew 等用户空间路径的问题。

调用 ensure_shell_path() 后，os.environ["PATH"] 被补全，下游 PTY 进程、
execute_command、MCP 子进程自动继承完整 PATH。
"""
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# 需要确保存在在 PATH 中的关键用户空间路径
_CRITICAL_PATHS = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
)

# $SHELL 获取失败时的 fallback 路径
_FALLBACK_PATHS = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    os.path.expanduser("~/.local/bin"),
)


def _is_missing_user_paths(current_path: str) -> bool:
    """检查 PATH 是否缺失所有关键用户空间路径。只要有一个即认为 PATH 足够。"""
    existing = set(current_path.split(os.pathsep))
    return not any(p in existing for p in _CRITICAL_PATHS)


def _get_shell_path() -> str | None:
    """通过 $SHELL -l -c 'echo $PATH' 获取用户完整 shell PATH。"""
    shell = os.environ.get("SHELL")
    if not shell:
        return None
    try:
        result = subprocess.run(
            [shell, "-l", "-c", "echo $PATH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        path = result.stdout.strip()
        # 基本校验：不能为空，不能只包含系统路径
        if path and ("/opt/homebrew" in path or "/usr/local" in path):
            return path
        return None
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("shell PATH acquisition failed: %s", exc)
        return None


def _build_fallback_path(current_path: str) -> str:
    """将 fallback 路径追加到当前 PATH。"""
    existing = set(current_path.split(os.pathsep))
    additions = [p for p in _FALLBACK_PATHS if p not in existing]
    if not additions:
        return current_path
    return current_path + os.pathsep + os.pathsep.join(additions)


def ensure_shell_path() -> None:
    """
    确保 os.environ["PATH"] 包含关键用户空间路径。

    幂等设计：PATH 已包含 homebrew 路径时不修改。
    缺失时优先通过 $SHELL 获取完整 PATH，失败时 fallback 拼接常见路径。
    """
    current = os.environ.get("PATH", "")

    if not _is_missing_user_paths(current):
        return

    shell_path = _get_shell_path()
    if shell_path:
        new_path = shell_path
        logger.info("PATH expanded via shell (%d → %d entries)",
                     len(current.split(os.pathsep)), len(new_path.split(os.pathsep)))
    else:
        new_path = _build_fallback_path(current)
        logger.info("PATH expanded via fallback (%d → %d entries)",
                     len(current.split(os.pathsep)), len(new_path.split(os.pathsep)))

    os.environ["PATH"] = new_path
