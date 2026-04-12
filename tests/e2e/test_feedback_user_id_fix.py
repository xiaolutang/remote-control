"""
S032: 用户信息 + 反馈修复集成测试

端到端验证 B056 user_id 修复 + F054/F055/F056 客户端改动。

后端测试：
- 登录获取 username → 提交反馈 → 反馈记录中 user_id 为真实用户名
- 不同用户提交反馈 → 各自 user_id 正确

前端代码检查：
- 三处菜单不含退出登录和反馈菜单项
- 三处菜单均包含个人信息入口
- UserProfileScreen 包含反馈入口和退出入口
"""
import json
import os
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from app.auth import generate_token


# ---------------------------------------------------------------------------
# InMemoryRedis — 复用自 test_feedback_e2e.py
# ---------------------------------------------------------------------------

class InMemoryRedis:
    def __init__(self):
        self._store: dict = {}
        self._lists: dict = {}
        self._kv: dict = {}

    async def set(self, key: str, value: str, ex=None):
        self._kv[key] = value

    async def get(self, key: str):
        return self._kv.get(key)

    async def delete(self, key: str):
        self._kv.pop(key, None)

    async def hset(self, key: str, *, mapping: dict = None, **kwargs):
        if key not in self._store:
            self._store[key] = {}
        if mapping:
            self._store[key].update(mapping)

    async def hgetall(self, key: str) -> dict:
        return dict(self._store.get(key, {}))

    async def lpush(self, key: str, value: str):
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: InMemoryRedis):
        self._redis = redis
        self._ops = []

    def hset(self, key: str, *, mapping: dict = None):
        self._ops.append(("hset", key, mapping))
        return self

    def lpush(self, key: str, value: str):
        self._ops.append(("lpush", key, value))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "hset":
                await self._redis.hset(op[1], mapping=op[2])
                results.append(True)
            elif op[0] == "lpush":
                await self._redis.lpush(op[1], op[2])
                results.append(1)
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_redis():
    return InMemoryRedis()


@pytest.fixture
def client(memory_redis):
    from app import app
    from fastapi.testclient import TestClient

    redis_conn_mock = MagicMock()
    redis_conn_mock.get_redis = AsyncMock(return_value=memory_redis)

    with patch("app.feedback_service.redis_conn", redis_conn_mock):
        yield TestClient(app)


@pytest.fixture
def user_alice():
    """Alice 的 token + session"""
    token = generate_token("alice-session")
    session = {"id": "alice-session", "user_id": "alice", "owner": "alice", "created_at": "2026-04-12T10:00:00Z"}
    return token, session


@pytest.fixture
def user_bob():
    """Bob 的 token + session"""
    token = generate_token("bob-session")
    session = {"id": "bob-session", "user_id": "bob", "owner": "bob", "created_at": "2026-04-12T10:00:00Z"}
    return token, session


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 后端集成测试：user_id 修复验证
# ---------------------------------------------------------------------------

class TestFeedbackUserIdFix:
    """B056 修复验证：反馈 user_id 为真实用户名"""

    def test_submit_feedback_user_id_is_real_username(self, client, user_alice):
        """登录 → 提交反馈 → 查询反馈 → user_id 为真实用户名"""
        alice_token, alice_session = user_alice

        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=alice_session), \
             patch("app.feedback_service.get_logs", new_callable=AsyncMock, return_value={"logs": [], "total": 0}), \
             patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
            resp = client.post(
                "/api/feedback",
                json={"session_id": "alice-session", "category": "connection", "description": "连接断开"},
                headers=_auth_headers(alice_token),
            )

        assert resp.status_code == 200
        feedback_id = resp.json()["feedback_id"]

        # 查询反馈验证 user_id
        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=alice_session):
            resp2 = client.get(f"/api/feedback/{feedback_id}", headers=_auth_headers(alice_token))

        assert resp2.status_code == 200
        detail = resp2.json()
        assert detail["user_id"] == "alice", f"Expected user_id='alice', got '{detail['user_id']}'"

    def test_different_users_different_user_ids(self, client, user_alice, user_bob):
        """不同用户提交反馈 → 各自 user_id 正确"""
        alice_token, alice_session = user_alice
        bob_token, bob_session = user_bob

        # Alice 提交反馈
        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=alice_session), \
             patch("app.feedback_service.get_logs", new_callable=AsyncMock, return_value={"logs": [], "total": 0}), \
             patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
            resp_a = client.post(
                "/api/feedback",
                json={"session_id": "alice-session", "category": "terminal", "description": "Alice 的反馈"},
                headers=_auth_headers(alice_token),
            )
        assert resp_a.status_code == 200
        fb_a = resp_a.json()["feedback_id"]

        # Bob 提交反馈
        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=bob_session), \
             patch("app.feedback_service.get_logs", new_callable=AsyncMock, return_value={"logs": [], "total": 0}), \
             patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
            resp_b = client.post(
                "/api/feedback",
                json={"session_id": "bob-session", "category": "other", "description": "Bob 的反馈"},
                headers=_auth_headers(bob_token),
            )
        assert resp_b.status_code == 200
        fb_b = resp_b.json()["feedback_id"]

        # 验证 Alice 的反馈 user_id
        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=alice_session):
            detail_a = client.get(f"/api/feedback/{fb_a}", headers=_auth_headers(alice_token)).json()
        assert detail_a["user_id"] == "alice"

        # 验证 Bob 的反馈 user_id
        with patch("app.feedback_api.get_session", new_callable=AsyncMock, return_value=bob_session):
            detail_b = client.get(f"/api/feedback/{fb_b}", headers=_auth_headers(bob_token)).json()
        assert detail_b["user_id"] == "bob"


# ---------------------------------------------------------------------------
# 前端代码检查：菜单去重 + 个人信息入口
# ---------------------------------------------------------------------------

class TestFrontendMenuDedup:
    """F056 前端菜单去重验证"""

    SCREENS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'client', 'lib', 'screens')

    def _read_screen(self, filename: str) -> str:
        path = os.path.join(self.SCREENS_DIR, filename)
        with open(path) as f:
            return f.read()

    def test_workspace_header_bar_no_feedback_logout(self):
        """_WorkspaceHeaderBar 不含反馈/退出菜单项"""
        content = self._read_screen("terminal_workspace_screen.dart")
        # 检查菜单项中不包含反馈和退出
        assert "反馈问题" not in content, "_WorkspaceHeaderBar 不应包含反馈问题菜单项"
        assert "Icons.logout" not in content, "_WorkspaceHeaderBar 不应包含退出登录菜单项"

    def test_runtime_selection_no_feedback_logout(self):
        """RuntimeSelectionScreen 不含反馈/退出菜单项"""
        content = self._read_screen("runtime_selection_screen.dart")
        assert "反馈问题" not in content, "RuntimeSelectionScreen 不应包含反馈问题菜单项"
        assert "_MenuAction.logout" not in content, "RuntimeSelectionScreen 不应包含退出登录菜单项"

    def test_terminal_screen_no_logout(self):
        """terminal_screen.dart 不含退出登录菜单项"""
        content = self._read_screen("terminal_screen.dart")
        assert "'logout'" not in content, "terminal_screen 不应包含退出登录菜单项"

    def test_workspace_header_bar_has_profile(self):
        """_WorkspaceHeaderBar 包含个人信息入口"""
        content = self._read_screen("terminal_workspace_screen.dart")
        assert "个人信息" in content, "_WorkspaceHeaderBar 应包含个人信息菜单项"
        assert "Icons.person_outline" in content, "_WorkspaceHeaderBar 应包含个人信息图标"

    def test_runtime_selection_has_profile(self):
        """RuntimeSelectionScreen 包含个人信息入口"""
        content = self._read_screen("runtime_selection_screen.dart")
        assert "个人信息" in content, "RuntimeSelectionScreen 应包含个人信息菜单项"
        assert "UserProfileScreen" in content, "RuntimeSelectionScreen 应导航到 UserProfileScreen"

    def test_terminal_screen_has_profile(self):
        """terminal_screen 包含个人信息入口"""
        content = self._read_screen("terminal_screen.dart")
        assert "个人信息" in content, "terminal_screen 应包含个人信息菜单项"
        assert "UserProfileScreen" in content, "terminal_screen 应导航到 UserProfileScreen"


class TestUserProfileScreenHasFeedbackAndLogout:
    """UserProfileScreen 包含反馈入口和退出入口"""

    SCREENS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'client', 'lib', 'screens')

    def test_user_profile_has_feedback_entry(self):
        """UserProfileScreen 包含反馈入口"""
        path = os.path.join(self.SCREENS_DIR, "user_profile_screen.dart")
        with open(path) as f:
            content = f.read()
        assert "FeedbackScreen" in content, "UserProfileScreen 应包含 FeedbackScreen 导航"
        assert "反馈问题" in content, "UserProfileScreen 应包含反馈问题文本"

    def test_user_profile_has_logout_entry(self):
        """UserProfileScreen 包含退出入口"""
        path = os.path.join(self.SCREENS_DIR, "user_profile_screen.dart")
        with open(path) as f:
            content = f.read()
        assert "logoutAndNavigate" in content, "UserProfileScreen 应使用 logoutAndNavigate"
        assert "退出登录" in content, "UserProfileScreen 应包含退出登录文本"
