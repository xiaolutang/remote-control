"""
B091: lookup_knowledge 工具测试。

覆盖：知识检索逻辑、内置知识文件完整性、配置降级、裁剪规则。
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.knowledge_tool import (
    KnowledgeConfig,
    load_knowledge_config,
    lookup_knowledge,
    get_knowledge_catalog_entry,
    _compute_relevance,
    _extract_relevant_section,
    _scan_knowledge_files,
    ensure_user_knowledge_dir,
    MAX_MATCHES,
    MAX_CHARS_PER_FILE,
)


# ---------------------------------------------------------------------------
# KnowledgeConfig
# ---------------------------------------------------------------------------

class TestKnowledgeConfig:

    def test_default_all_enabled(self):
        config = KnowledgeConfig()
        assert config.is_enabled("any_file.md") is True

    def test_disabled_file(self):
        config = KnowledgeConfig(disabled_files={"disabled.md"})
        assert config.is_enabled("disabled.md") is False
        assert config.is_enabled("other.md") is True


# ---------------------------------------------------------------------------
# load_knowledge_config
# ---------------------------------------------------------------------------

class TestLoadKnowledgeConfig:

    def test_missing_file_returns_default(self, tmp_path):
        with patch("app.knowledge_tool._get_knowledge_config_path", return_value=tmp_path / "nonexistent.json"):
            config = load_knowledge_config()
            assert config.disabled_files == set()

    def test_valid_config(self, tmp_path):
        config_file = tmp_path / "knowledge_config.json"
        config_file.write_text(json.dumps({"disabled_files": ["test.md"]}))
        with patch("app.knowledge_tool._get_knowledge_config_path", return_value=config_file):
            config = load_knowledge_config()
            assert config.is_enabled("test.md") is False
            assert config.is_enabled("other.md") is True

    def test_malformed_json_defaults_all_enabled(self, tmp_path):
        config_file = tmp_path / "knowledge_config.json"
        config_file.write_text("not json{")
        with patch("app.knowledge_tool._get_knowledge_config_path", return_value=config_file):
            config = load_knowledge_config()
            assert config.disabled_files == set()

    def test_empty_disabled_files(self, tmp_path):
        config_file = tmp_path / "knowledge_config.json"
        config_file.write_text(json.dumps({"disabled_files": []}))
        with patch("app.knowledge_tool._get_knowledge_config_path", return_value=config_file):
            config = load_knowledge_config()
            assert config.disabled_files == set()


# ---------------------------------------------------------------------------
# 知识检索逻辑
# ---------------------------------------------------------------------------

class TestLookupKnowledge:

    def _setup_knowledge_dir(self, tmp_path, files: dict[str, str]):
        """创建临时知识目录并填充文件。"""
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        for name, content in files.items():
            (knowledge_dir / name).write_text(content, encoding="utf-8")
        return knowledge_dir

    def test_query_claude_code_returns_content(self, tmp_path):
        knowledge_dir = self._setup_knowledge_dir(tmp_path, {
            "claude_code.md": "# Claude Code 使用技巧\n启动命令: claude\n交互式编程",
            "other.md": "# 其他\n无关内容",
        })
        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("Claude Code")
            assert "Claude Code" in result
            assert "claude" in result

    def test_query_refactor_returns_scenario(self, tmp_path):
        knowledge_dir = self._setup_knowledge_dir(tmp_path, {
            "scenario_tips.md": "# 场景化编程建议\n## 代码重构\n请帮我重构模块",
        })
        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("重构")
            assert "重构" in result

    def test_query_not_found(self, tmp_path):
        knowledge_dir = self._setup_knowledge_dir(tmp_path, {
            "test.md": "# 测试\n一些测试内容",
        })
        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("完全不存在的主题 xyz123")
            assert result == "未找到相关知识"

    def test_empty_query_returns_not_found(self):
        result = lookup_knowledge("")
        assert result == "未找到相关知识"

    def test_user_custom_files_searched(self, tmp_path):
        builtin_dir = self._setup_knowledge_dir(tmp_path, {
            "builtin.md": "# 内置\n内置内容",
        })
        user_dir = tmp_path / "user_knowledge"
        user_dir.mkdir()
        (user_dir / "custom.md").write_text("# 自定义\n我的自定义知识", encoding="utf-8")

        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=builtin_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=user_dir), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("自定义")
            assert "自定义" in result

    def test_max_3_matches(self, tmp_path):
        files = {f"file{i}.md": f"# 文件{i}\n关键词匹配测试内容" for i in range(5)}
        knowledge_dir = self._setup_knowledge_dir(tmp_path, files)

        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("关键词匹配")
            # 应该只有 3 个文件的分隔符（2 个 ---）
            assert result.count("---") == 2  # 3 个文件 = 2 个分隔符

    def test_truncation_over_2000_chars(self, tmp_path):
        long_content = "A" * 3000
        knowledge_dir = self._setup_knowledge_dir(tmp_path, {
            "long.md": f"# 长文件\n{long_content}",
        })

        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=KnowledgeConfig()):
            result = lookup_knowledge("长文件")
            assert "[已截断]" in result or len(result) <= MAX_CHARS_PER_FILE + 100

    def test_disabled_file_excluded(self, tmp_path):
        knowledge_dir = self._setup_knowledge_dir(tmp_path, {
            "enabled.md": "# 启用的\n重要内容关键词",
            "disabled.md": "# 禁用的\n禁用关键词内容",
        })
        config = KnowledgeConfig(disabled_files={"disabled.md"})

        with patch("app.knowledge_tool._get_builtin_knowledge_dir", return_value=knowledge_dir), \
             patch("app.knowledge_tool._get_user_knowledge_dir", return_value=tmp_path / "empty_user"), \
             patch("app.knowledge_tool.load_knowledge_config", return_value=config):
            result = lookup_knowledge("关键词")
            assert "禁用" not in result
            assert "重要" in result


# ---------------------------------------------------------------------------
# 内置知识文件完整性
# ---------------------------------------------------------------------------

class TestBuiltinKnowledgeFiles:

    def _get_knowledge_dir(self):
        return Path(__file__).parent.parent / "app" / "knowledge"

    def test_knowledge_dir_has_at_least_4_files(self):
        knowledge_dir = self._get_knowledge_dir()
        md_files = list(knowledge_dir.glob("*.md"))
        assert len(md_files) >= 4, f"Expected >= 4 md files, found {len(md_files)}: {[f.name for f in md_files]}"

    def test_each_file_non_empty(self):
        knowledge_dir = self._get_knowledge_dir()
        for md_file in knowledge_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            assert content.strip(), f"{md_file.name} is empty"

    def test_expected_files_exist(self):
        knowledge_dir = self._get_knowledge_dir()
        expected = {"claude_code.md", "vibe_coding.md", "scenario_tips.md", "ai_tools_guide.md"}
        actual = {f.name for f in knowledge_dir.glob("*.md")}
        assert expected.issubset(actual), f"Missing files: {expected - actual}"


# ---------------------------------------------------------------------------
# Catalog Entry
# ---------------------------------------------------------------------------

class TestCatalogEntry:

    def test_catalog_entry_structure(self):
        entry = get_knowledge_catalog_entry()
        assert entry["name"] == "lookup_knowledge"
        assert entry["kind"] == "builtin"
        assert "query" in entry["parameters"]["properties"]
        assert entry["parameters"]["required"] == ["query"]

    def test_catalog_entry_description_present(self):
        entry = get_knowledge_catalog_entry()
        assert len(entry["description"]) > 0


# ---------------------------------------------------------------------------
# Relevance & Extraction
# ---------------------------------------------------------------------------

class TestRelevanceComputation:

    def test_name_match_higher_score(self):
        s1 = _compute_relevance("claude", "claude_code.md", "内容")
        s2 = _compute_relevance("claude", "other.md", "内容")
        assert s1 > s2

    def test_multiple_keyword_hits(self):
        score = _compute_relevance("claude code 使用", "test.md", "claude code 使用技巧")
        assert score > 0

    def test_no_match_zero_score(self):
        score = _compute_relevance("xyz123", "test.md", "完全无关的内容")
        assert score == 0


class TestExtractRelevantSection:

    def test_short_content_not_truncated(self):
        result = _extract_relevant_section("短内容", "内容", 1000)
        assert result == "短内容"

    def test_long_content_truncated(self):
        content = "A" * 3000
        result = _extract_relevant_section(content, "keyword", 2000)
        assert len(result) <= 2000 + len("\n[已截断]")
        assert "[已截断]" in result

    def test_keyword_centered(self):
        content = "B" * 500 + "KEYWORD" + "C" * 500
        result = _extract_relevant_section(content, "KEYWORD", 200)
        assert "KEYWORD" in result


# ---------------------------------------------------------------------------
# ensure_user_knowledge_dir
# ---------------------------------------------------------------------------

class TestEnsureUserKnowledgeDir:

    def test_creates_dir(self, tmp_path):
        target = tmp_path / "user_knowledge"
        with patch("app.knowledge_tool._get_user_knowledge_dir", return_value=target):
            result = ensure_user_knowledge_dir()
            assert result == target
            assert target.is_dir()
