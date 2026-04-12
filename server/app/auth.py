"""
JWT 认证服务
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import secrets
import string

# Redis key 前缀
TOKEN_VERSION_KEY_PREFIX = "token_version"


class TokenVerificationError(HTTPException):
    """Token 校验异常，携带 error_code 供客户端分支处理。

    继承 HTTPException，现有 except HTTPException 仍能捕获。
    自定义 exception handler 将 error_code 写入响应体顶层。
    """
    def __init__(self, status_code: int, detail: str, error_code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code

# 配置
# 兼容历史环境变量，避免 docker / 本地脚本配置错位导致 token 不一致。
JWT_SECRET_KEY = (
    os.getenv("JWT_SECRET_KEY")
    or os.getenv("JWT_SECRET")
    or secrets.token_hex(32)
)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(
    os.getenv("JWT_EXPIRATION_HOURS")
    or os.getenv("JWT_EXPIRY_HOURS")
    or "168"  # 7天，避免频繁刷新
)
REFRESH_TOKEN_EXPIRATION_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "30"))

# HTTP Bearer 认证
security = HTTPBearer()


def normalize_view_type(view: Optional[str]) -> str:
    """规范化 view_type，非法/未知值按 mobile 处理"""
    if view in ("mobile", "desktop"):
        return view
    return "mobile"


async def _get_token_version_redis():
    """获取 Redis 连接用于 token_version 操作"""
    from app.session import get_redis
    return await get_redis()


def _token_version_key(session_id: str, view_type: str) -> str:
    """构造 token_version Redis key"""
    return f"{TOKEN_VERSION_KEY_PREFIX}:{session_id}:{view_type}"


async def get_token_version(session_id: str, view_type: str) -> Optional[int]:
    """获取当前 token 版本号，key 不存在返回 None"""
    redis = await _get_token_version_redis()
    key = _token_version_key(session_id, view_type)
    val = await redis.get(key)
    if val is None:
        return None
    return int(val)


async def increment_token_version(session_id: str, view_type: str) -> int:
    """递增 token 版本号并返回新值。失败时抛出异常（由调用方处理 fail-closed）。

    每次 INCR 后都刷新 TTL，防止长时间未重启的 key 因只设一次 TTL 而意外过期。
    """
    redis = await _get_token_version_redis()
    key = _token_version_key(session_id, view_type)
    new_version = await redis.incr(key)
    # 每次递增都刷新 TTL，防止旧 key 过期后导致新 token 被误判
    ttl_seconds = REFRESH_TOKEN_EXPIRATION_DAYS * 24 * 60 * 60
    await redis.expire(key, ttl_seconds)
    return new_version


def generate_session_id(length: int = 16) -> str:
    """生成随机 session_id"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def generate_token(
    session_id: str,
    expires_in_hours: Optional[int] = None,
    token_version: Optional[int] = None,
    view_type: Optional[str] = None,
) -> str:
    """
    生成 JWT Token

    Args:
        session_id: 会话 ID
        expires_in_hours: 过期时间（小时），默认使用配置值
        token_version: 可选，登录层版本号
        view_type: 可选，设备类型 (mobile/desktop)

    Returns:
        JWT Token 字符串
    """
    if not session_id:
        raise ValueError("session_id 不能为空")

    expiration_hours = expires_in_hours or JWT_EXPIRATION_HOURS
    expire = datetime.now(timezone.utc) + timedelta(hours=expiration_hours)

    payload = {
        "sub": session_id,
        "exp": expire.timestamp(),
        "iat": datetime.now(timezone.utc).timestamp(),
    }

    if token_version is not None:
        payload["token_version"] = token_version
    if view_type is not None:
        payload["view_type"] = view_type

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """
    验证 JWT Token（同步，仅做 JWT 解码校验，不含 Redis 版本校验）。

    Args:
        token: JWT Token 字符串

    Returns:
        包含 session_id 和其他信息的字典。
        如果 JWT 含 token_version/view_type，一并返回供 async_verify_token 使用。

    Raises:
        TokenVerificationError: token 过期时含 error_code=TOKEN_EXPIRED，
                                无效时含 error_code=TOKEN_INVALID
        HTTPException: 其他格式错误
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 不能为空",
        )

    # 检查 token 长度
    if len(token) > 10240:  # 10KB
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Token 过长",
        )

    # 检查 null bytes
    if '\x00' in token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token 格式错误",
        )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )

        session_id = payload.get("sub")
        if not session_id:
            raise TokenVerificationError(
                detail="Token 缺少 session_id",
                error_code="TOKEN_INVALID",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        result = {
            "session_id": session_id,
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
        }

        # 透传 token_version/view_type（如有），供 async_verify_token 使用
        if "token_version" in payload:
            result["token_version"] = payload["token_version"]
        if "view_type" in payload:
            result["view_type"] = payload["view_type"]

        return result

    except JWTError as e:
        error_msg = str(e).lower()

        if "expired" in error_msg:
            raise TokenVerificationError(
                detail="Token 已过期",
                error_code="TOKEN_EXPIRED",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        else:
            raise TokenVerificationError(
                detail=f"Token 无效: {e}",
                error_code="TOKEN_INVALID",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )


async def async_verify_token(token: str) -> dict:
    """
    异步验证 JWT Token，包含 Redis token_version 校验。

    用于受保护 API 的依赖注入。流程：
    1. 调用 verify_token 做 JWT 基础校验
    2. 如果 JWT 含 token_version，与 Redis 当前版本比对
    3. 旧 token（无 token_version）直接放行（向后兼容）
    """
    import logging
    _logger = logging.getLogger("auth.verify")

    # 先做基础 JWT 校验
    try:
        payload = verify_token(token)
    except TokenVerificationError as e:
        _logger.warning(
            "JWT decode failed: error_code=%s detail=%s token_prefix=%s",
            e.error_code, e.detail, token[:20] if token else "None",
        )
        raise

    # 如果 JWT 中携带 token_version，与 Redis 比对
    token_version = payload.get("token_version")
    view_type = payload.get("view_type")
    if token_version is not None and view_type is not None:
        try:
            current_version = await get_token_version(payload["session_id"], view_type)
        except Exception as redis_err:
            _logger.error(
                "Redis GET failed for session=%s view=%s: %s",
                payload["session_id"], view_type, redis_err,
            )
            # Redis GET 失败 → fail-closed: 携带 token_version 的 token 返回 503
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Token 验证服务暂不可用",
            )

        if current_version is None or current_version != token_version:
            _logger.warning(
                "Token version mismatch: session=%s view=%s jwt_version=%s redis_version=%s",
                payload["session_id"], view_type, token_version, current_version,
            )
            raise TokenVerificationError(
                detail="Token 已在其他设备登录",
                error_code="TOKEN_REPLACED",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

    return payload


async def get_current_session_async(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    获取当前会话 ID（异步 async_verify_token 版本，用于受保护路由）

    通过 async_verify_token 进行完整校验，包含 Redis token_version 比对。

    Returns:
        session_id 字符串
    """
    token = credentials.credentials
    payload = await async_verify_token(token)
    return payload["session_id"]


def create_token_response(session_id: Optional[str] = None) -> dict:
    """
    创建 token 响应

    Args:
        session_id: 可选的 session_id，不提供则自动生成

    Returns:
        包含 session_id, token, expires_at 的字典
    """
    if not session_id:
        session_id = generate_session_id()

    token = generate_token(session_id)
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)

    return {
        "session_id": session_id,
        "token": token,
        "expires_at": expire.isoformat(),
    }


def create_token_with_session(session_id: str) -> dict:
    """
    为已存在的 session 创建新 token

    Args:
        session_id: 已存在的 session_id

    Returns:
        包含 session_id, token, expires_at 的字典
    """
    return create_token_response(session_id)


def generate_refresh_token(session_id: str, view_type: Optional[str] = None) -> str:
    """
    生成 Refresh Token

    Args:
        session_id: 会话 ID
        view_type: 可选，设备类型 (mobile/desktop)

    Returns:
        Refresh Token 字符串
    """
    if not session_id:
        raise ValueError("session_id 不能为空")

    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)

    payload = {
        "sub": session_id,
        "type": "refresh",  # 标记为 refresh token
        "exp": expire.timestamp(),
        "iat": datetime.now(timezone.utc).timestamp(),
    }

    if view_type is not None:
        payload["view_type"] = view_type

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_refresh_token(token: str) -> dict:
    """
    验证 Refresh Token

    Args:
        token: Refresh Token 字符串

    Returns:
        包含 session_id 的字典

    Raises:
        HTTPException: token 无效、过期或类型错误时抛出 401
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 不能为空",
        )

    # 检查 token 长度
    if len(token) > 10240:  # 10KB
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Refresh Token 过长",
        )

    # 检查 null bytes
    if '\x00' in token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh Token 格式错误",
        )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )

        # 检查 token 类型
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 类型错误",
            )

        session_id = payload.get("sub")
        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 缺少 session_id",
            )

        return {
            "session_id": session_id,
            "type": payload.get("type"),
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
            "view_type": payload.get("view_type"),
        }

    except JWTError as e:
        error_msg = str(e).lower()

        if "expired" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh Token 已过期",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Refresh Token 无效: {e}",
            )
