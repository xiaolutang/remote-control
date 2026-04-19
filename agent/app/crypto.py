"""
Agent 端加密服务

职责：
- 从 Server 拉取 RSA 公钥
- RSA-OAEP 加密（密码、AES 密钥）
- AES-256-GCM 加解密（WebSocket 消息）
- TOFU 公钥指纹校验
"""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

import aiohttp
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

PLAINTEXT_MSG_TYPES = frozenset({"auth", "connected", "ping", "pong"})


class AgentCrypto:
    """Agent 端加密管理器"""

    def __init__(self, state_dir: str | None = None):
        self._state_dir = Path(state_dir or os.getenv("AGENT_STATE_DIR", Path.home() / ".rc-agent"))
        self._public_key = None
        self._fingerprint: str | None = None
        self._aes_key: bytes | None = None

    # ---- 公钥管理 ----

    async def fetch_public_key(self, http_base_url: str) -> None:
        """从 Server 拉取 RSA 公钥并校验指纹"""
        url = f"{http_base_url}/api/public-key"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

        pem = data["public_key_pem"]
        self._public_key = serialization.load_pem_public_key(pem.encode())
        self._fingerprint = data["fingerprint"]
        self._verify_fingerprint(self._fingerprint)
        logger.info("Public key loaded, fingerprint=%s", self._fingerprint)

    @property
    def has_public_key(self) -> bool:
        return self._public_key is not None

    # ---- RSA 加密 ----

    def rsa_encrypt(self, plaintext: bytes) -> bytes:
        """RSA-OAEP 加密"""
        return self._public_key.encrypt(
            plaintext,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

    def rsa_encrypt_b64(self, plaintext: bytes) -> str:
        """RSA 加密并返回 base64"""
        return base64.b64encode(self.rsa_encrypt(plaintext)).decode()

    # ---- AES 会话密钥 ----

    def generate_aes_key(self) -> bytes:
        """生成 AES-256 密钥"""
        self._aes_key = os.urandom(32)
        return self._aes_key

    def get_encrypted_aes_key_b64(self) -> str:
        """获取 RSA 加密后的 AES 密钥（base64）"""
        return self.rsa_encrypt_b64(self._aes_key)

    def clear_aes_key(self) -> None:
        self._aes_key = None

    # ---- AES 消息加解密 ----

    def encrypt_message(self, message: dict) -> dict:
        """加密消息为 {encrypted, iv, data}"""
        plaintext = json.dumps(message, ensure_ascii=False).encode("utf-8")
        iv = os.urandom(12)
        aesgcm = AESGCM(self._aes_key)
        ciphertext = aesgcm.encrypt(iv, plaintext, None)
        return {
            "encrypted": True,
            "iv": base64.b64encode(iv).decode(),
            "data": base64.b64encode(ciphertext).decode(),
        }

    def decrypt_message(self, raw: dict) -> dict:
        """解密 {encrypted, iv, data} 消息"""
        iv = base64.b64decode(raw["iv"])
        ciphertext = base64.b64decode(raw["data"])
        aesgcm = AESGCM(self._aes_key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(plaintext)

    @staticmethod
    def should_encrypt(msg_type: str) -> bool:
        return msg_type not in PLAINTEXT_MSG_TYPES

    # ---- TOFU 指纹 ----

    def _verify_fingerprint(self, fingerprint: str) -> None:
        """TOFU: 首次存储，后续比对"""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        fp_file = self._state_dir / "server_fingerprint.txt"

        if not fp_file.exists():
            fp_file.write_text(fingerprint)
            return

        stored = fp_file.read_text().strip()
        if stored != fingerprint:
            raise RuntimeError(
                f"服务器密钥指纹已变更！可能存在中间人攻击。\n"
                f"已存储: {stored}\n当前: {fingerprint}"
            )


# 全局单例
agent_crypto = AgentCrypto()
