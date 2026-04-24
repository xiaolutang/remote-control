"""
B092: Skill 注册表管理。

读取 skills/ 目录下的 skill.json 和全局 skill-registry.json，
管理 Skill 的发现、启用/禁用状态。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Skill manifest 必填字段
_REQUIRED_FIELDS = {"name", "command", "transport"}

# R043 仅支持 stdio
_SUPPORTED_TRANSPORTS = {"stdio"}


def _get_agent_data_dir() -> Path:
    """获取 Agent 数据目录。"""
    config_dir = os.environ.get("RC_AGENT_CONFIG_DIR", "~/.rc-agent")
    return Path(config_dir).expanduser()


def _get_skills_dir() -> Path:
    """获取 skills/ 目录路径。"""
    return _get_agent_data_dir() / "skills"


def _get_registry_path() -> Path:
    """获取 skill-registry.json 路径。"""
    return _get_agent_data_dir() / "skill-registry.json"


@dataclass
class SkillManifest:
    """单个 Skill 的描述信息。"""
    name: str
    version: str = "0.0.0"
    description: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    transport: str = "stdio"
    timeout: int = 30


@dataclass
class SkillEntry:
    """注册表中的一个 Skill 条目。"""
    name: str
    enabled: bool = True
    manifest: Optional[SkillManifest] = None
    skill_dir: Optional[Path] = None


def ensure_skills_dir() -> Path:
    """确保 skills/ 目录存在，返回路径。"""
    skills_dir = _get_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    return skills_dir


def load_skill_registry() -> dict[str, bool]:
    """加载 skill-registry.json，返回 {name: enabled} 映射。

    缺失或格式损坏时返回空 dict（视为全启用）。
    """
    registry_path = _get_registry_path()
    if not registry_path.exists():
        return {}

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            logger.warning("skill-registry.json skills 字段不是数组，视为空列表")
            return {}
        return {
            entry["name"]: entry.get("enabled", True)
            for entry in skills
            if isinstance(entry, dict) and "name" in entry
        }
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("skill-registry.json 格式损坏，视为空列表: %s", e)
        return {}
    except Exception as e:
        logger.warning("读取 skill-registry.json 失败: %s", e)
        return {}


def save_skill_registry(entries: dict[str, bool]) -> None:
    """保存 skill-registry.json。"""
    registry_path = _get_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "skills": [
            {"name": name, "enabled": enabled}
            for name, enabled in entries.items()
        ]
    }
    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _parse_skill_json(skill_dir: Path) -> Optional[SkillManifest]:
    """解析 skill.json，malformed 时返回 None 并记录 warning。"""
    skill_json = skill_dir / "skill.json"
    if not skill_json.exists():
        logger.warning("Skill 目录缺少 skill.json: %s", skill_dir)
        return None

    try:
        with open(skill_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("skill.json 格式错误 (%s): %s", skill_dir, e)
        return None

    if not isinstance(data, dict):
        logger.warning("skill.json 不是 JSON 对象: %s", skill_dir)
        return None

    # 检查必填字段
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        logger.warning("skill.json 缺少必填字段 %s: %s", missing, skill_dir)
        return None

    # 检查 transport
    transport = data.get("transport", "")
    if transport not in _SUPPORTED_TRANSPORTS:
        logger.warning("skill.json transport=%s 不支持 (R043 仅支持 %s): %s",
                       transport, _SUPPORTED_TRANSPORTS, skill_dir)
        return None

    return SkillManifest(
        name=data["name"],
        version=data.get("version", "0.0.0"),
        description=data.get("description", ""),
        command=data["command"],
        args=data.get("args", []),
        transport=transport,
        timeout=int(data.get("timeout", 30)),
    )


def discover_skills() -> list[SkillEntry]:
    """发现 skills/ 目录下所有已启用的 Skill。

    Returns:
        SkillEntry 列表，包含 manifest 信息。
    """
    skills_dir = _get_skills_dir()
    registry = load_skill_registry()

    entries = []
    if not skills_dir.is_dir():
        return entries

    for skill_path in sorted(skills_dir.iterdir()):
        if not skill_path.is_dir():
            continue
        skill_json = skill_path / "skill.json"
        if not skill_json.exists():
            continue

        manifest = _parse_skill_json(skill_path)
        if manifest is None:
            continue

        # 检查启用状态：registry 中有记录则用记录，否则默认启用
        enabled = registry.get(manifest.name, True)

        entries.append(SkillEntry(
            name=manifest.name,
            enabled=enabled,
            manifest=manifest,
            skill_dir=skill_path,
        ))

    return entries
