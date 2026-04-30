"""部署配置验证测试。

验证 docker-compose 文件、.env.example 和 deploy.sh 满足开源部署契约。
运行: python -m pytest deploy/tests/test_deploy_config.py -v
"""
import os
import re
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(path):
    with open(os.path.join(ROOT, path)) as f:
        return f.read()


class TestDevCompose:
    """docker-compose.dev.yml 验证。"""

    def test_no_external_network(self):
        content = read("deploy/docker-compose.dev.yml")
        assert "external: true" not in content, "dev compose 不应引用 external network"

    def test_server_port_8880(self):
        content = read("deploy/docker-compose.dev.yml")
        assert "8880:8000" in content or "RC_DIRECT_PORT" in content

    def test_redis_password_required(self):
        content = read("deploy/docker-compose.dev.yml")
        # 使用 :? 语法要求 REDIS_PASSWORD
        assert "REDIS_PASSWORD:?" in content or "REDIS_PASSWORD:?请在" in content


class TestProdCompose:
    """docker-compose.yml 验证。"""

    def test_no_hardcoded_internal_domain(self):
        content = read("deploy/docker-compose.yml")
        # 不允许硬编码内部域名（排除 localhost）
        matches = re.findall(r"xiaolutang\.top", content)
        assert len(matches) == 0, f"prod compose 中仍有 {len(matches)} 处硬编码域名"

    def test_redis_password_required(self):
        content = read("deploy/docker-compose.yml")
        assert "REDIS_PASSWORD:?" in content or "REDIS_PASSWORD:?请在" in content

    def test_jwt_secret_required(self):
        content = read("deploy/docker-compose.yml")
        assert "JWT_SECRET:?" in content or "JWT_SECRET:?请在" in content

    def test_router_rule_parameterized(self):
        content = read("deploy/docker-compose.yml")
        # TRAEFIK_ROUTER_RULE 应通过环境变量引用
        assert "TRAEFIK_ROUTER_RULE" in content
        # 默认值不应包含内部域名
        default_match = re.search(r"TRAEFIK_ROUTER_RULE:-([^}]+)", content)
        if default_match:
            default_val = default_match.group(1)
            assert "xiaolutang.top" not in default_val


class TestEnvExample:
    """.env.example 验证。"""

    def test_has_required_variables(self):
        content = read(".env.example")
        required = ["JWT_SECRET", "REDIS_PASSWORD"]
        for var in required:
            assert var in content, f".env.example 缺少 {var}"

    def test_has_optional_variables(self):
        content = read(".env.example")
        optional = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "RC_DIRECT_PORT"]
        for var in optional:
            assert var in content, f".env.example 缺少 {var}"

    def test_no_internal_domain(self):
        content = read(".env.example")
        assert "xiaolutang.top" not in content, ".env.example 不应包含内部域名"

    def test_no_secrets(self):
        content = read(".env.example")
        # 不应包含实际的密钥值（变量为空或有默认值是允许的）
        assert not re.search(r"sk-[a-zA-Z0-9]{10,}", content)
        # 不应出现非注释行中的非空密码值
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            # 非注释行中 password/secret 不应有非空非数字值
            if re.match(r".*(PASSWORD|SECRET)\s*=\s*\S+", stripped, re.IGNORECASE):
                val = stripped.split("=", 1)[1].strip()
                assert val == "", f"非注释行含非空密码: {stripped}"


class TestDeployScript:
    """deploy.sh 验证。"""

    def test_no_source_env(self):
        content = read("deploy/deploy.sh")
        # 不应直接 source .env 文件（用 grep 安全解析）
        # 检查非注释行
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            assert "source " not in stripped or "get_env_var" in stripped, \
                f"deploy.sh 不应 source 文件: {stripped}"

    def test_no_private_deps(self):
        content = read("deploy/deploy.sh")
        assert "deploy-lib.sh" not in content
        assert "ai_rules" not in content

    def test_no_hardcoded_domain(self):
        content = read("deploy/deploy.sh")
        assert "xiaolutang.top" not in content

    def test_has_dev_mode(self):
        content = read("deploy/deploy.sh")
        assert "--dev" in content
        assert "docker-compose.dev.yml" in content

    def test_has_jwt_validation(self):
        content = read("deploy/deploy.sh")
        assert "JWT_SECRET" in content
