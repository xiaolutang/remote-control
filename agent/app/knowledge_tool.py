"""
B091: lookup_knowledge 内置工具实现。

提供关键词匹配检索逻辑，搜索内置 knowledge/ 和用户自定义 user_knowledge/ 目录下的 md 文件。
支持 knowledge_config.json 启用/禁用配置。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 检索结果限制
MAX_MATCHES = 3
MAX_CHARS_PER_FILE = 2000
TRUNCATION_MARKER = "\n[已截断]"


def _get_agent_data_dir() -> Path:
    """获取 Agent 数据目录（存放 user_knowledge/、knowledge_config.json 等）。"""
    config_dir = os.environ.get("RC_AGENT_CONFIG_DIR", "~/.rc-agent")
    return Path(config_dir).expanduser()


def _get_builtin_knowledge_dir() -> Path:
    """获取内置知识文件目录（随 Agent 分发包）。"""
    return Path(__file__).parent / "knowledge"


def _get_user_knowledge_dir() -> Path:
    """获取用户自定义知识文件目录。"""
    return _get_agent_data_dir() / "user_knowledge"


def _get_knowledge_config_path() -> Path:
    """获取知识文件配置路径。"""
    return _get_agent_data_dir() / "knowledge_config.json"


@dataclass
class KnowledgeConfig:
    """知识文件启用/禁用配置。"""
    # key=文件名(不含路径), value=True=启用, False=禁用
    disabled_files: set[str] = field(default_factory=set)

    def is_enabled(self, filename: str) -> bool:
        return filename not in self.disabled_files


def load_knowledge_config() -> KnowledgeConfig:
    """加载知识文件配置。缺失或格式损坏时默认全启用。"""
    config_path = _get_knowledge_config_path()
    if not config_path.exists():
        return KnowledgeConfig()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        disabled = set(data.get("disabled_files", []))
        return KnowledgeConfig(disabled_files=disabled)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("knowledge_config.json 格式损坏，默认全启用: %s", e)
        return KnowledgeConfig()
    except Exception as e:
        logger.warning("读取 knowledge_config.json 失败，默认全启用: %s", e)
        return KnowledgeConfig()


def ensure_user_knowledge_dir() -> Path:
    """确保 user_knowledge/ 目录存在，返回路径。"""
    user_dir = _get_user_knowledge_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _scan_knowledge_files(config: KnowledgeConfig) -> list[tuple[str, Path]]:
    """扫描所有知识文件，返回 [(文件名, 路径)] 列表，跳过禁用文件。"""
    files = []
    seen_names: set[str] = set()

    # 内置知识优先
    builtin_dir = _get_builtin_knowledge_dir()
    if builtin_dir.is_dir():
        for p in sorted(builtin_dir.glob("*.md")):
            name = p.name
            if name not in seen_names and config.is_enabled(name):
                files.append((name, p))
                seen_names.add(name)

    # 用户自定义知识
    user_dir = _get_user_knowledge_dir()
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.md")):
            name = p.name
            if name not in seen_names and config.is_enabled(name):
                files.append((name, p))
                seen_names.add(name)

    return files


def _scan_all_knowledge_files() -> list[tuple[str, Path]]:
    """扫描所有知识文件，返回 [(文件名, 路径)] 列表，不跳过禁用文件。

    B095: 用于 /knowledge API，需要列出所有文件及其启用状态。
    """
    files = []
    seen_names: set[str] = set()

    # 内置知识优先
    builtin_dir = _get_builtin_knowledge_dir()
    if builtin_dir.is_dir():
        for p in sorted(builtin_dir.glob("*.md")):
            name = p.name
            if name not in seen_names:
                files.append((name, p))
                seen_names.add(name)

    # 用户自定义知识
    user_dir = _get_user_knowledge_dir()
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.md")):
            name = p.name
            if name not in seen_names:
                files.append((name, p))
                seen_names.add(name)

    return files


def save_knowledge_config(config: KnowledgeConfig) -> None:
    """保存知识文件配置到 knowledge_config.json。

    B095: 用于 /knowledge/toggle API。
    """
    config_path = _get_knowledge_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"disabled_files": sorted(config.disabled_files)}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _compute_relevance(query: str, name: str, content: str) -> int:
    """计算匹配度分数。基于关键词命中次数。"""
    query_lower = query.lower()
    # 分词：支持空格和中文字符
    keywords = query_lower.replace("，", " ").replace("、", " ").split()
    keywords = [k for k in keywords if k]

    score = 0
    name_lower = name.lower()
    content_lower = content.lower()

    for kw in keywords:
        # 文件名匹配权重更高
        if kw in name_lower:
            score += 10
        # 内容匹配
        count = content_lower.count(kw)
        score += min(count, 5)  # 每个关键词在内容中最多计 5 次

    return score


def _extract_relevant_section(content: str, query: str, max_chars: int) -> str:
    """提取内容中与 query 最相关的段落。"""
    if len(content) <= max_chars:
        return content

    query_lower = query.lower()
    keywords = query_lower.replace("，", " ").replace("、", " ").split()
    keywords = [k for k in keywords if k]

    if not keywords:
        return content[:max_chars] + TRUNCATION_MARKER

    # 找到第一个包含关键词的位置
    content_lower = content.lower()
    best_pos = -1
    for kw in keywords:
        pos = content_lower.find(kw)
        if pos != -1:
            if best_pos == -1 or pos < best_pos:
                best_pos = pos

    if best_pos == -1:
        return content[:max_chars] + TRUNCATION_MARKER

    # 从关键词前 100 字符开始截取
    start = max(0, best_pos - 100)
    end = start + max_chars
    result = content[start:end]
    if end < len(content):
        result += TRUNCATION_MARKER
    return result


def lookup_knowledge(query: str) -> str:
    """检索知识文件，返回匹配内容。

    Args:
        query: 检索关键词

    Returns:
        拼接后的知识内容，未匹配时返回 '未找到相关知识'
    """
    if not query or not query.strip():
        return "未找到相关知识"

    config = load_knowledge_config()
    files = _scan_knowledge_files(config)

    if not files:
        return "未找到相关知识"

    # 读取内容并计算匹配度
    scored: list[tuple[int, str, str]] = []  # (score, name, content)
    for name, path in files:
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                continue
            score = _compute_relevance(query, name, content)
            if score > 0:
                scored.append((score, name, content))
        except Exception as e:
            logger.warning("读取知识文件失败 %s: %s", path, e)

    if not scored:
        return "未找到相关知识"

    # 按匹配度降序排序，取 top 3
    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored[:MAX_MATCHES]

    # 拼接结果
    parts = []
    for score, name, content in top_matches:
        excerpt = _extract_relevant_section(content, query, MAX_CHARS_PER_FILE)
        parts.append(f"## {name}\n{excerpt}")

    return "\n\n---\n\n".join(parts)


def get_knowledge_catalog_entry() -> dict:
    """返回 lookup_knowledge 的 built-in catalog entry，用于 tool_catalog_snapshot 上报。"""
    return {
        "name": "lookup_knowledge",
        "kind": "builtin",
        "description": "检索本地知识文件，返回与查询关键词匹配的知识内容",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词",
                },
            },
            "required": ["query"],
        },
    }
