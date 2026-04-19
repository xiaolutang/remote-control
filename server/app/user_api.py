"""
用户认证 REST API
"""
from fastapi import APIRouter, HTTPException, status, Depends, Request as FastAPIRequest
from pydantic import BaseModel
from typing import Optional
import hashlib
from datetime import datetime, timezone, timedelta

from app.session import get_redis, create_session, get_session, verify_session_ownership, get_session_by_name, cleanup_user_sessions
from app.auth import (
    create_token_response,
    generate_refresh_token,
    verify_refresh_token,
    async_verify_token,
    generate_token,
    increment_token_version,
    get_token_version,
    normalize_view_type,
    create_token_with_session,
    TokenVerificationError,
    JWT_EXPIRATION_HOURS,
    REFRESH_TOKEN_EXPIRATION_DAYS,
    get_current_user_id,
)
from app.database import get_user, save_user, get_user_devices, add_user_device, update_password_hash
from app.rate_limit import check_rate_limit

router = APIRouter()


class UserRegister(BaseModel):
    username: str
    password: Optional[str] = None
    password_encrypted: Optional[str] = None
    device_name: Optional[str] = None
    view: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: Optional[str] = None  # 明文密码（兼容旧客户端）
    password_encrypted: Optional[str] = None  # RSA 加密后的密码（base64）
    view: Optional[str] = None


class DeviceInfo(BaseModel):
    device_name: str
    device_type: str = "mobile"  # mobile, tablet, desktop


class LoginResponse(BaseModel):
    success: bool
    message: str
    username: Optional[str] = None
    session_id: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None
    refresh_token: Optional[str] = None
    refresh_expires_at: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    success: bool
    access_token: str
    refresh_token: str
    expires_in: int  # 秒
    refresh_expires_in: int  # 秒
    token_type: str = "Bearer"


class DeviceListResponse(BaseModel):
    devices: list


class SessionStateResponse(BaseModel):
    """Session 状态响应模型 (CONTRACT-001)"""
    session_id: str
    owner: str
    agent_online: bool
    views: dict
    pty: dict
    updated_at: str


def hash_password(password: str) -> str:
    """密码哈希（bcrypt）"""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码（支持 bcrypt 和旧 SHA-256）"""
    import bcrypt

    # bcrypt 哈希以 $2b$ 开头
    if password_hash.startswith("$2b$"):
        return bcrypt.checkpw(password.encode(), password_hash.encode())

    # 旧 SHA-256 格式（64 hex 字符）
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()
    return legacy_hash == password_hash


def is_legacy_hash(password_hash: str) -> bool:
    """判断是否为旧 SHA-256 哈希"""
    return len(password_hash) == 64 and all(c in "0123456789abcdef" for c in password_hash)


async def _rate_limit_dependency(request: FastAPIRequest):
    """速率限制依赖：检查客户端 IP，超限返回 429。"""
    client_ip = request.client.host if request.client else "unknown"
    retry_after = await check_rate_limit(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )


# Refresh Token Redis 管理函数
async def store_refresh_token(session_id: str, refresh_token: str):
    """存储 refresh token 到 Redis"""
    redis = await get_redis()
    key = f"refresh_token:{session_id}"
    ttl_seconds = REFRESH_TOKEN_EXPIRATION_DAYS * 24 * 60 * 60
    await redis.set(key, refresh_token, ex=ttl_seconds)


async def get_stored_refresh_token(session_id: str) -> Optional[str]:
    """从 Redis 获取 refresh token"""
    redis = await get_redis()
    key = f"refresh_token:{session_id}"
    return await redis.get(key)


async def delete_refresh_token(session_id: str):
    """删除 Redis 中的 refresh token（单次使用后失效）"""
    redis = await get_redis()
    key = f"refresh_token:{session_id}"
    await redis.delete(key)


def _resolve_password(password: Optional[str], password_encrypted: Optional[str]) -> str:
    """从明文或 RSA 加密字段解析出真实密码"""
    if password_encrypted:
        from app.crypto import get_crypto_manager
        return get_crypto_manager().rsa_decrypt(password_encrypted).decode("utf-8")
    if password:
        return password
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="password 或 password_encrypted 必须提供一项",
    )


@router.get("/public-key")
async def get_public_key():
    """获取服务器 RSA 公钥（供客户端加密密码和 AES 密钥交换）"""
    from app.crypto import get_crypto_manager
    return get_crypto_manager().get_public_key_info()


@router.post("/register", response_model=LoginResponse)
async def register(user: UserRegister, _rl=Depends(_rate_limit_dependency)):
    """注册新用户"""
    raw_password = _resolve_password(user.password, user.password_encrypted)

    if len(user.username) < 3 or len(user.username) > 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名长度需要 3-32 个字符",
        )

    if len(raw_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度至少 6 个字符",
        )

    # 检查用户是否已存在
    existing = await get_user(user.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    # 创建用户
    password_hash = hash_password(raw_password)
    await save_user(user.username, password_hash)

    # 自动登录，生成 token
    token_response = create_token_response()

    # 创建 session 记录（WebSocket 连接需要），绑定用户
    await create_session(
        token_response["session_id"],
        name=f"{user.username}_session",
        user_id=user.username
    )

    # 递增 token_version 并重新签发携带版本的 token
    view_type = normalize_view_type(user.view)
    session_id = token_response["session_id"]
    try:
        new_version = await increment_token_version(session_id, view_type)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="注册服务暂不可用，请稍后重试",
        )

    # 用携带 token_version 的 token 替换无版本 token
    versioned_token = generate_token(
        session_id, token_version=new_version, view_type=view_type
    )
    token_response["token"] = versioned_token

    return LoginResponse(
        success=True,
        message="注册成功",
        username=user.username,
        session_id=session_id,
        token=versioned_token,
        expires_at=token_response["expires_at"],
    )


@router.post("/login", response_model=LoginResponse)
async def login(user: UserLogin, _rl=Depends(_rate_limit_dependency)):
    """用户登录"""
    raw_password = _resolve_password(user.password, user.password_encrypted)

    # 验证用户
    stored_user = await get_user(user.username)
    if not stored_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    stored_hash = stored_user["password_hash"]

    if not verify_password(raw_password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    # 旧 SHA-256 哈希自动迁移为 bcrypt
    if is_legacy_hash(stored_hash):
        new_hash = hash_password(raw_password)
        await update_password_hash(user.username, new_hash)

    # 检查是否已有该用户的 session（实现同用户多设备共享 session）
    existing_session = await get_session_by_name(f"{user.username}_session")

    if existing_session:
        # 清理该用户的其他旧 session，只保留当前找到的
        await cleanup_user_sessions(user.username, keep_session_id=existing_session["id"])
        # 使用现有 session，生成新 token
        token_response = create_token_with_session(existing_session["id"])
    else:
        # 清理该用户的旧 session，防止 stale session 残留
        await cleanup_user_sessions(user.username)

        # 生成新 token 和 session
        token_response = create_token_response()
        # 创建 session 记录（WebSocket 连接需要），绑定用户
        await create_session(
            token_response["session_id"],
            name=f"{user.username}_session",
            user_id=user.username
        )

    session_id = token_response["session_id"]

    # 递增 token_version 并签发携带版本的 token
    view_type = normalize_view_type(user.view)
    try:
        new_version = await increment_token_version(session_id, view_type)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="登录服务暂不可用，请稍后重试",
        )

    versioned_token = generate_token(
        session_id, token_version=new_version, view_type=view_type
    )

    # 生成 refresh token（携带 view_type）
    refresh_token = generate_refresh_token(session_id, view_type=view_type)
    await store_refresh_token(session_id, refresh_token)

    # 计算 refresh token 过期时间
    refresh_expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)

    return LoginResponse(
        success=True,
        message="登录成功",
        username=user.username,
        session_id=session_id,
        token=versioned_token,
        expires_at=token_response["expires_at"],
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expire.isoformat(),
    )


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(user_id: str = Depends(get_current_user_id)):
    """列出用户绑定的设备（需要认证）"""
    devices = await get_user_devices(user_id)
    return DeviceListResponse(devices=devices)


@router.post("/bind-device")
async def bind_device(
    device: DeviceInfo,
    user_id: str = Depends(get_current_user_id),
):
    """绑定设备到用户（需要认证）"""
    device_info = {
        "device_name": device.device_name,
        "device_type": device.device_type,
        "bound_at": datetime.now(timezone.utc).isoformat(),
    }
    await add_user_device(user_id, device_info)
    return {"success": True, "message": "设备绑定成功"}


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest):
    """
    刷新 Access Token

    使用 refresh_token 获取新的 access_token 和 refresh_token
    旧的 refresh_token 使用后立即失效（单次使用）
    不递增 token_version，使用 Redis 当前版本写入新 token
    """
    # 验证 refresh token 格式和签名
    payload = verify_refresh_token(request.refresh_token)
    session_id = payload["session_id"]

    # 从 Redis 获取存储的 refresh token
    stored_token = await get_stored_refresh_token(session_id)

    # 检查 token 是否存在（可能已被使用或过期被清理）
    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 无效或已过期",
        )

    # 验证 token 是否匹配（防止重放攻击）
    if stored_token != request.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 无效或已过期",
        )

    # 立即删除旧的 refresh token（单次使用）
    await delete_refresh_token(session_id)

    # 读取当前 token_version（不递增）
    # 旧 refresh token 无 view_type 时按 mobile 处理
    view_type = normalize_view_type(payload.get("view_type"))
    try:
        current_version = await get_token_version(session_id, view_type)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token 刷新服务暂不可用，请稍后重试",
        )

    # 生成新的 access token（携带当前版本）
    if current_version is not None:
        new_access_token = generate_token(
            session_id, token_version=current_version, view_type=view_type
        )
    else:
        # Redis 中无版本记录（旧 session 未登录过），不携带版本
        new_access_token = generate_token(session_id)

    # 生成新的 refresh token（携带 view_type 保持设备范围）
    new_refresh_token = generate_refresh_token(session_id, view_type=view_type)

    # 存储新的 refresh token
    await store_refresh_token(session_id, new_refresh_token)

    # 返回新的 token
    return RefreshResponse(
        success=True,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=JWT_EXPIRATION_HOURS * 3600,  # 转换为秒
        refresh_expires_in=REFRESH_TOKEN_EXPIRATION_DAYS * 24 * 3600,  # 转换为秒
        token_type="Bearer",
    )


@router.get("/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session_state(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    获取 Session 状态 (CONTRACT-001)

    需要 Bearer Token 认证，只能查询自己拥有的 session
    """
    # 验证 session 归属
    try:
        session = await verify_session_ownership(session_id, user_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} 不存在",
            )
        elif e.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问此 Session",
            )
        raise

    # 获取当前视图连接数
    from app.ws_client import get_view_counts
    from app.ws_agent import is_agent_connected

    view_counts = get_view_counts(session_id)
    agent_online = is_agent_connected(session_id)

    return SessionStateResponse(
        session_id=session_id,
        owner=session.get("owner", user_id),
        agent_online=agent_online,
        views=view_counts,
        pty=session.get("pty", {"rows": 24, "cols": 80}),
        updated_at=session.get("updated_at", session.get("created_at", "")),
    )
