# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for rc-agent (macOS arm64).

Usage:
    cd agent
    pyinstaller rc-agent.spec
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
agent_root = SPECPATH  # directory containing this .spec file

# ---------------------------------------------------------------------------
# Pre-collect data files from tricky packages
# ---------------------------------------------------------------------------
# cryptography: native .so + data files
crypto_datas = collect_data_files('cryptography')
# pydantic: compiled rust backend
pydantic_datas = collect_data_files('pydantic')
# log-service-sdk: editable install, won't be auto-detected
try:
    sdk_datas = collect_data_files('log_service_sdk')
except Exception:
    sdk_datas = []

# ---------------------------------------------------------------------------
# Analysis — collect sources + hidden deps
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(agent_root, 'app', 'main.py')],
    pathex=[agent_root],
    binaries=[],
    datas=[
        # Built-in knowledge files (shipped with agent)
        (os.path.join(agent_root, 'app', 'tools', 'knowledge'), 'app/tools/knowledge'),
        # Shared command whitelist (used by command_validator)
        (os.path.join(agent_root, '..', 'shared', 'command_whitelist.json'), '.'),
    ] + crypto_datas + pydantic_datas + sdk_datas,
    hiddenimports=[
        # --- agent packages ---
        'app',
        'app.cli',
        'app.core',
        'app.core.config',
        'app.core.log_adapter',
        'app.core.pty_wrapper',
        'app.core.pty_types',
        'app.core.pty_process',
        'app.core.message_types',
        'app.core.env_compat',
        'app.security',
        'app.security.auth_service',
        'app.security.crypto',
        'app.security.command_validator',
        'app.transport',
        'app.transport.websocket_client',
        'app.transport.agent_message_handler',
        'app.transport.agent_protocol',
        'app.transport.pty_types',
        'app.tools',
        'app.tools.skill_registry',
        'app.tools.knowledge_tool',
        'app.tools.mcp_client',
        'app.tools.mcp_rpc',
        'app.tools.mcp_types',
        # --- local_server (top-level, dynamically imported by websocket_client) ---
        'local_server',
        # --- third-party (may be lazily imported) ---
        'websockets',
        'websockets.client',
        'websockets.exceptions',
        'click',
        'pydantic',
        'aiohttp',
        'aiohttp.client',
        # --- log-service-sdk (editable install, may not be auto-detected) ---
        'log_service_sdk',
        'log_service_sdk.handler',
        'log_service_sdk.constants',
        'log_service_sdk.issue',
        'log_service_sdk.setup',
        # --- cryptography submodules (native .so) ---
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.ciphers.algorithms',
        'cryptography.hazmat.primitives.ciphers.modes',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.kdf',
        'cryptography.hazmat.primitives.padding',
        'cryptography.hazmat.backends',
        'cryptography.hazmat.backends.openssl',
        'cryptography.fernet',
        'cryptography.utils',
    ] + collect_submodules('cryptography') + collect_submodules('log_service_sdk'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # trim unnecessary large packages
        'tkinter',
        'unittest',
        'test',
        'tests',
        'setuptools',
        'pip',
        'wheel',
    ],
    noarchive=False,
    cipher=block_cipher,
)

# ---------------------------------------------------------------------------
# PYZ (compressed python modules)
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure, cipher=block_cipher)

# ---------------------------------------------------------------------------
# EXE — onedir 模式可执行文件（不含嵌入资源）
# onedir 比 single-file 快 30 倍（0.2s vs 6s），且退出干净无挂起。
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='rc-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,  # UPX can cause issues on macOS arm64
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
)

# ---------------------------------------------------------------------------
# COLLECT — onedir 输出目录（dist/rc-agent/）
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip_binaries=True,
    upx_binaries=False,
    upx_dir=None,
    name='rc-agent',
)
