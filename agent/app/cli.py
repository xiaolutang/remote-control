"""
命令行入口
"""
import asyncio
import atexit
import click
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from app.config import Config, load_config, save_config, get_config_path, normalize_config_path
from app.websocket_client import WebSocketClient
from app.auth_service import AuthService
from app.log_adapter import init_logging as _init_logging, close_logging as _close_logging


logger = logging.getLogger(__name__)


def setup_agent_logging() -> None:
    """初始化 Agent 远程日志（通过适配层）。"""
    _init_logging(component="agent")


atexit.register(_close_logging)


class Context:
    """CLI 上下文"""
    def __init__(self):
        self.config: Optional[Config] = None
        self.config_path: Optional[Path] = None
        self.client: Optional[WebSocketClient] = None


def _log_agent(message: str) -> None:
    """Agent 日志输出到终端"""
    if os.environ.get("FLUTTER_TEST"):
        return
    print(f"[Agent] {message}", file=sys.stderr, flush=True)


@click.group(invoke_without_command=True)
@click.option("--server", help="服务器 URL (例如: wss://example.com)")
@click.option("--token", help="认证 Token (向后兼容)")
@click.option("--command", default="/bin/bash", help="要执行的命令")
@click.option("--shell", is_flag=True, default=False, help="启动交互式 shell")
@click.option("--local-display/--no-local-display", default=False, help="是否在本地终端镜像显示 PTY，并允许本地键盘直接操作")
@click.option("--reconnect/--no-reconnect", default=True, help="自动重连")
@click.option("--max-retries", default=5, help="最大重试次数")
@click.option("--config", "config_path", type=click.Path(), help="配置文件路径")
@click.version_option(version="1.0.0", prog_name="rc-agent")
@click.pass_context
def cli(ctx, **kwargs):
    """Remote Control Agent - 远程终端控制代理

    使用方法:
        rc-agent              # 直接启动（需要先登录）
        rc-agent login        # 登录
        rc-agent status       # 查看状态
        rc-agent logout       # 退出登录
    """
    # 初始化上下文
    if ctx.obj is None:
        ctx.obj = Context()

    # 确定配置路径
    config_path = normalize_config_path(kwargs.pop("config_path", None))
    ctx.obj.config_path = config_path

    # 加载配置
    ctx.obj.config = load_config(config_path)

    # 更新配置
    for key, value in kwargs.items():
        if value is not None and hasattr(ctx.obj.config, key):
            setattr(ctx.obj.config, key, value)


async def ensure_valid_token(config: Config, config_path) -> tuple:
    """
    确保有效的 access token

    Returns:
        (success, access_token_or_error_message)
    """
    access_token = config.get_access_token()
    refresh_token = config.refresh_token

    if not access_token:
        return False, "未配置 Token，请先使用 'rc-agent login' 登录"

    # 验证当前 token
    auth = AuthService(config.server_url)
    if await auth.verify_token(access_token):
        return True, access_token

    # Token 无效，尝试刷新
    if not refresh_token:
        return False, "Token 已过期且无 Refresh Token，请重新登录"

    click.echo("Token 已过期，正在刷新...")

    refresh_result = await auth.refresh_token(refresh_token)
    if refresh_result.success:
        # 保存新 token
        config.access_token = refresh_result.access_token
        config.refresh_token = refresh_result.refresh_token
        config.token = refresh_result.access_token  # 向后兼容
        save_config(config, config_path)

        click.echo(click.style("✓ Token 刷新成功", fg="green"))
        return True, refresh_result.access_token
    else:
        return False, f"Token 刷新失败: {refresh_result.message}，请重新登录"


@cli.command()
@click.option("--server", required=True, help="服务器 URL (例如: https://example.com)")
@click.option("--username", prompt=True, help="用户名")
@click.option("--password", prompt=True, hide_input=True, help="密码")
@click.pass_context
def login(ctx, server, username, password):
    """登录并保存 Token"""
    config = ctx.obj.config
    config_path = ctx.obj.config_path

    click.echo(f"正在登录 {server}...")

    # 创建认证服务
    auth = AuthService(server)

    # 执行登录
    async def do_login():
        return await auth.login(username, password)

    result = asyncio.run(do_login())

    if result.success:
        # 保存配置
        config.server_url = server
        config.access_token = result.access_token
        config.refresh_token = result.refresh_token
        config.username = username
        # 向后兼容
        config.token = result.access_token

        save_config(config, config_path)

        click.echo(click.style("✓ 登录成功!", fg="green"))
        click.echo(f"Session ID: {result.session_id}")
        click.echo(f"配置已保存到: {config_path}")
    else:
        click.echo(click.style(f"✗ 登录失败: {result.message}", fg="red"))
        sys.exit(1)


@cli.command()
@click.option("--command", default=None, help="要执行的命令")
@click.option("--shell", is_flag=True, default=None, help="启动交互式 shell")
@click.option("--reconnect/--no-reconnect", default=None, help="自动重连")
@click.option("--max-retries", default=None, help="最大重试次数")
@click.pass_context
def run(ctx, command, shell, reconnect, max_retries):
    """使用保存的配置启动 Agent（支持自动登录）"""
    setup_agent_logging()
    config = ctx.obj.config
    config_path = ctx.obj.config_path

    # 检查服务器配置
    if not config.server_url:
        click.echo(click.style("✗ 未配置服务器 URL，请先使用 'rc-agent login' 登录", fg="red"))
        sys.exit(1)

    # 确保有效的 token
    success, token_or_error = asyncio.run(ensure_valid_token(config, config_path))

    if not success:
        click.echo(click.style(f"✗ {token_or_error}", fg="red"))
        click.echo("请使用 'rc-agent login' 重新登录")
        sys.exit(1)

    # 更新可选参数
    if command:
        config.command = command
    if shell is not None:
        config.shell_mode = shell
    if reconnect is not None:
        config.auto_reconnect = reconnect
    if max_retries is not None:
        config.max_retries = max_retries

    click.echo(f"正在连接服务器: {config.server_url}")
    click.echo(f"命令: {config.command}")

    # 创建 WebSocket 客户端
    client = WebSocketClient(
        server_url=config.server_url,
        token=token_or_error,
        command=config.command,
        shell_mode=config.shell_mode,
        auto_reconnect=config.auto_reconnect,
        max_retries=config.max_retries,
        local_display=False,
    )
    ctx.obj.client = client

    def _handle_sigterm(signum, frame):
        text = f"received signal {signum}, converting to KeyboardInterrupt"
        click.echo(text)
        _log_agent(text)
        raise KeyboardInterrupt()

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    # 启动连接
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        _log_agent("KeyboardInterrupt path entered, stopping client")
        click.echo("\n正在断开连接...")
        asyncio.run(client.stop())
        click.echo("已断开")
    except Exception as e:
        _log_agent(f"run command exception: {e}")
        click.echo(f"连接错误: {e}", err=True)
        sys.exit(1)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


@cli.command()
@click.option("--server", required=True, help="服务器 URL (例如: wss://example.com)")
@click.option("--token", required=True, help="认证 Token")
@click.option("--command", default="/bin/bash", help="要执行的命令")
@click.option("--shell", is_flag=True, default=False, help="启动交互式 shell")
@click.option("--local-display/--no-local-display", default=False, help="是否在本地终端镜像显示 PTY，并允许本地键盘直接操作")
@click.option("--reconnect/--no-reconnect", default=True, help="自动重连")
@click.option("--max-retries", default=5, help="最大重试次数")
@click.pass_context
def start(ctx, server, token, command, shell, local_display, reconnect, max_retries):
    """手动指定参数启动 Agent（不保存配置）"""
    setup_agent_logging()
    config = ctx.obj.config

    click.echo(f"正在连接服务器: {server}")
    click.echo(f"命令: {command}")

    # 创建 WebSocket 客户端
    client = WebSocketClient(
        server_url=server,
        token=token,
        command=command,
        shell_mode=shell,
        local_display=local_display,
        auto_reconnect=reconnect,
        max_retries=max_retries,
    )
    ctx.obj.client = client

    def _handle_sigterm(signum, frame):
        text = f"received signal {signum}, converting to KeyboardInterrupt"
        click.echo(text)
        _log_agent(text)
        raise KeyboardInterrupt()

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    # 启动连接
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        _log_agent("KeyboardInterrupt path entered, stopping client")
        click.echo("\n正在断开连接...")
        asyncio.run(client.stop())
        click.echo("已断开")
    except Exception as e:
        _log_agent(f"start command exception: {e}")
        click.echo(f"连接错误: {e}", err=True)
        sys.exit(1)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)


@cli.command()
@click.pass_context
def status(ctx):
    """显示当前连接状态"""
    config = ctx.obj.config

    click.echo("Remote Control Agent 状态:")
    click.echo("-" * 30)
    click.echo(f"服务器: {config.server_url or '未配置'}")
    click.echo(f"用户名: {config.username or '未配置'}")
    click.echo(f"Access Token: {'已配置' if config.access_token else '未配置'}")
    click.echo(f"Refresh Token: {'已配置' if config.refresh_token else '未配置'}")
    click.echo(f"命令: {config.command or '未配置'}")
    click.echo(f"Shell 模式: {'是' if config.shell_mode else '否'}")
    click.echo(f"自动重连: {'是' if config.auto_reconnect else '否'}")

    client = ctx.obj.client
    if client and client.is_connected:
        click.echo("连接状态: 已连接")
        click.echo(f"Session ID: {client.session_id}")
    else:
        click.echo("连接状态: 未连接")


@cli.command()
@click.option("--server", help="服务器 URL")
@click.option("--username", help="用户名")
@click.option("--access-token", help="Access Token")
@click.option("--refresh-token", help="Refresh Token")
@click.option("--command", help="要执行的命令")
@click.option("--shell", is_flag=True, default=None, help="启动交互式 shell")
@click.option("--reconnect/--no-reconnect", default=None, help="自动重连")
@click.option("--max-retries", type=int, help="最大重试次数")
@click.pass_context
def configure(ctx, server, username, access_token, refresh_token, command, shell, reconnect, max_retries):
    """配置 Agent（不启动连接）"""
    config = ctx.obj.config
    config_path = ctx.obj.config_path

    if server:
        config.server_url = server
        click.echo(f"服务器 URL 已更新: {server}")
    if username:
        config.username = username
        click.echo(f"用户名已更新: {username}")
    if access_token:
        config.access_token = access_token
        config.token = access_token  # 向后兼容
        click.echo("Access Token 已更新")
    if refresh_token:
        config.refresh_token = refresh_token
        click.echo("Refresh Token 已更新")
    if command:
        config.command = command
        click.echo(f"命令已更新: {command}")
    if shell is not None:
        config.shell_mode = shell
        click.echo(f"Shell 模式已更新: {shell}")
    if reconnect is not None:
        config.auto_reconnect = reconnect
        click.echo(f"自动重连已更新: {reconnect}")
    if max_retries:
        config.max_retries = max_retries
        click.echo(f"最大重试次数已更新: {max_retries}")

    # 保存配置
    save_config(config, config_path)
    click.echo(f"\n配置已保存到: {config_path}")


@cli.command()
@click.pass_context
def logout(ctx):
    """清除保存的登录凭据"""
    config = ctx.obj.config
    config_path = ctx.obj.config_path

    config.access_token = None
    config.refresh_token = None
    config.token = None
    config.username = None

    save_config(config, config_path)
    click.echo("已清除登录凭据")


def main():
    """CLI 主入口"""
    # 如果没有指定子命令，默认运行 run 命令
    if len(sys.argv) == 1 or (len(sys.argv) > 1 and not sys.argv[1].startswith('-') and sys.argv[1] not in ['login', 'run', 'start', 'status', 'configure', 'logout', 'help']):
        # 检查是否是全局选项
        if '--help' not in sys.argv and '--version' not in sys.argv:
            sys.argv.insert(1, 'run')
    cli()


if __name__ == "__main__":
    main()
