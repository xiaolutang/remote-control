"""
B092: Skill 注册表 + MCP Client 框架测试。
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.skill_registry import (
    SkillEntry,
    SkillManifest,
    discover_skills,
    load_skill_registry,
    save_skill_registry,
    ensure_skills_dir,
    _parse_skill_json,
)


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

class TestLoadSkillRegistry:

    def test_missing_file_returns_empty(self, tmp_path):
        with patch("app.skill_registry._get_registry_path", return_value=tmp_path / "nonexistent.json"):
            result = load_skill_registry()
            assert result == {}

    def test_valid_registry(self, tmp_path):
        registry_file = tmp_path / "skill-registry.json"
        registry_file.write_text(json.dumps({
            "skills": [
                {"name": "git_helper", "enabled": True},
                {"name": "code_review", "enabled": False},
            ]
        }))
        with patch("app.skill_registry._get_registry_path", return_value=registry_file):
            result = load_skill_registry()
            assert result == {"git_helper": True, "code_review": False}

    def test_malformed_json_returns_empty(self, tmp_path):
        registry_file = tmp_path / "skill-registry.json"
        registry_file.write_text("not json{")
        with patch("app.skill_registry._get_registry_path", return_value=registry_file):
            result = load_skill_registry()
            assert result == {}

    def test_empty_skills_returns_empty(self, tmp_path):
        registry_file = tmp_path / "skill-registry.json"
        registry_file.write_text(json.dumps({"skills": []}))
        with patch("app.skill_registry._get_registry_path", return_value=registry_file):
            result = load_skill_registry()
            assert result == {}


class TestSaveSkillRegistry:

    def test_save_and_load_roundtrip(self, tmp_path):
        registry_file = tmp_path / "skill-registry.json"
        with patch("app.skill_registry._get_registry_path", return_value=registry_file):
            save_skill_registry({"test": True, "other": False})
            result = load_skill_registry()
            assert result == {"test": True, "other": False}


class TestParseSkillJson:

    def test_valid_skill_json(self, tmp_path):
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "my_skill",
            "version": "1.0.0",
            "description": "Test skill",
            "command": "python3",
            "args": ["-m", "my_skill"],
            "transport": "stdio",
            "timeout": 15,
        }))
        manifest = _parse_skill_json(skill_dir)
        assert manifest is not None
        assert manifest.name == "my_skill"
        assert manifest.command == "python3"
        assert manifest.transport == "stdio"
        assert manifest.timeout == 15

    def test_missing_skill_json(self, tmp_path):
        skill_dir = tmp_path / "no_json"
        skill_dir.mkdir()
        manifest = _parse_skill_json(skill_dir)
        assert manifest is None

    def test_malformed_json(self, tmp_path):
        skill_dir = tmp_path / "bad_json"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text("{invalid")
        manifest = _parse_skill_json(skill_dir)
        assert manifest is None

    def test_missing_required_field(self, tmp_path):
        skill_dir = tmp_path / "missing_field"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "test",
            # missing "command" and "transport"
        }))
        manifest = _parse_skill_json(skill_dir)
        assert manifest is None

    def test_unsupported_transport(self, tmp_path):
        skill_dir = tmp_path / "unsupported"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "test",
            "command": "test",
            "transport": "http",  # not supported in R043
        }))
        manifest = _parse_skill_json(skill_dir)
        assert manifest is None


class TestDiscoverSkills:

    def test_discover_enabled_skills(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "test_skill",
            "command": "echo",
            "transport": "stdio",
        }))

        with patch("app.skill_registry._get_skills_dir", return_value=skills_dir), \
             patch("app.skill_registry.load_skill_registry", return_value={}):
            entries = discover_skills()
            assert len(entries) == 1
            assert entries[0].name == "test_skill"
            assert entries[0].enabled is True

    def test_disabled_skill(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "disabled"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text(json.dumps({
            "name": "disabled_skill",
            "command": "echo",
            "transport": "stdio",
        }))

        with patch("app.skill_registry._get_skills_dir", return_value=skills_dir), \
             patch("app.skill_registry.load_skill_registry", return_value={"disabled_skill": False}):
            entries = discover_skills()
            assert len(entries) == 1
            assert entries[0].enabled is False

    def test_empty_skills_dir(self, tmp_path):
        skills_dir = tmp_path / "empty_skills"
        skills_dir.mkdir()
        with patch("app.skill_registry._get_skills_dir", return_value=skills_dir), \
             patch("app.skill_registry.load_skill_registry", return_value={}):
            entries = discover_skills()
            assert entries == []

    def test_nonexistent_skills_dir(self, tmp_path):
        with patch("app.skill_registry._get_skills_dir", return_value=tmp_path / "nope"), \
             patch("app.skill_registry.load_skill_registry", return_value={}):
            entries = discover_skills()
            assert entries == []


class TestEnsureSkillsDir:

    def test_creates_dir(self, tmp_path):
        target = tmp_path / "skills"
        with patch("app.skill_registry._get_skills_dir", return_value=target):
            result = ensure_skills_dir()
            assert result == target
            assert target.is_dir()
