"""
RSA + AES 加密服务

Server 端职责：
- 管理 RSA-2048 密钥对（生成/加载/持久化）
- 解密客户端发来的 RSA-OAEP 加密数据（密码、AES 密钥）
- 提供 AES-GCM 加解密工具方法
- 计算公钥指纹（TOFU）
"""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# 不加密的控制消息类型（协议握手/心跳）
PLAINTEXT_MSG_TYPES = frozenset({"auth", "connected", "ping", "pong"})


class CryptoManager:
    """RSA 密钥对管理器"""

    def __init__(self, key_dir: str | None = None):
        if key_dir is None:
            key_dir = os.getenv("RSA_KEY_DIR", "/data")
        self._key_dir = Path(key_dir)
        self._private_key = None
        self._public_key = None
        self._public_key_info: dict | None = None  # 缓存
        self._fingerprint: str | None = None  # 缓存
        self._load_or_generate_keys()

    # ---- RSA 密钥管理 ----

    def _load_or_generate_keys(self):
        priv_path = self._key_dir / "rsa_private.pem"
        pub_path = self._key_dir / "rsa_public.pem"

        if priv_path.exists():
            try:
                self._private_key = serialization.load_pem_private_key(
                    priv_path.read_bytes(),
                    password=None,
                )
                self._public_key = self._private_key.public_key()
                logger.info("RSA key pair loaded from %s", priv_path)
                pub_path.write_bytes(
                    self._public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )
                return
            except PermissionError:
                logger.warning("Cannot read %s (permission denied), regenerating keys", priv_path)

        # 生成新的密钥对
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        self._public_key = self._private_key.public_key()
        self._key_dir.mkdir(parents=True, exist_ok=True)
        priv_path.write_bytes(
            self._private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        pub_path.write_bytes(
            self._public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        # 限制私钥文件权限
        try:
            os.chmod(priv_path, 0o600)
        except OSError:
            pass
        logger.info("RSA key pair generated and saved to %s", priv_path)

    def get_public_key_pem(self) -> str:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    def get_public_key_info(self) -> dict:
        """返回公钥信息供客户端使用（缓存）"""
        if self._public_key_info is None:
            numbers = self._public_key.public_numbers()
            n_bytes = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, byteorder="big")
            self._public_key_info = {
                "public_key_pem": self.get_public_key_pem(),
                "modulus_b64": base64.b64encode(n_bytes).decode(),
                "exponent": numbers.e,
                "fingerprint": self.get_fingerprint(),
            }
        return self._public_key_info

    def get_fingerprint(self) -> str:
        """计算公钥指纹（SHA256，SSH 风格，缓存）"""
        if self._fingerprint is None:
            der_bytes = self._public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            digest = hashlib.sha256(der_bytes).digest()
            b64 = base64.b64encode(digest).decode().rstrip("=")
            self._fingerprint = f"SHA256:{b64}"
        return self._fingerprint

    def rsa_decrypt(self, encrypted_b64: str) -> bytes:
        """RSA-OAEP 解密"""
        ciphertext = base64.b64decode(encrypted_b64)
        return self._private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

    # ---- AES 工具方法 ----

    @staticmethod
    def generate_aes_key() -> bytes:
        """生成 256-bit AES 密钥"""
        return os.urandom(32)

    @staticmethod
    def aes_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
        """AES-256-GCM 加密，返回 (iv, ciphertext_with_tag)"""
        iv = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext, None)
        return iv, ciphertext

    @staticmethod
    def aes_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
        """AES-256-GCM 解密"""
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(iv, ciphertext, None)


# ---- 消息级加解密 ----

def encrypt_message(aes_key: bytes, message: dict) -> dict:
    """将消息 JSON 加密为 {encrypted: true, iv, data} 格式"""
    plaintext = json.dumps(message, ensure_ascii=False).encode("utf-8")
    iv, ciphertext = CryptoManager.aes_encrypt(aes_key, plaintext)
    return {
        "encrypted": True,
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }


def decrypt_message(aes_key: bytes, raw: dict) -> dict:
    """解密 {encrypted: true, iv, data} 格式的消息"""
    iv = base64.b64decode(raw["iv"])
    ciphertext = base64.b64decode(raw["data"])
    plaintext = CryptoManager.aes_decrypt(aes_key, iv, ciphertext)
    return json.loads(plaintext)


def should_encrypt(msg_type: str) -> bool:
    """判断消息类型是否需要加密"""
    return msg_type not in PLAINTEXT_MSG_TYPES


# 全局单例（延迟初始化，避免 import 时立即访问文件系统）
crypto_manager: CryptoManager | None = None


def get_crypto_manager() -> CryptoManager:
    global crypto_manager
    if crypto_manager is None:
        crypto_manager = CryptoManager()
    return crypto_manager
