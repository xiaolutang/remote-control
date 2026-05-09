"""
S521: Server auth 辅助函数边界测试。

覆盖 S505 提取的 _validate_token_format() 和 _decode_and_classify_jwt() 边界场景。
"""
import pytest

from app.infra.auth import (
    _validate_token_format,
    _decode_and_classify_jwt,
    generate_token,
    TokenVerificationError,
)
from fastapi import HTTPException, status


# ─── _validate_token_format 边界测试 ───


class TestValidateTokenFormatEmpty:
    """空值 / 空字符串 / 纯空白"""

    def test_none_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format(None)
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "不能为空" in exc_info.value.detail

    def test_empty_string_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("")
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_whitespace_only_passes(self):
        """纯空白字符串不被 _validate_token_format 拦截（格式校验不负责语义）。"""
        _validate_token_format("   ")  # 不应抛异常


class TestValidateTokenFormatTooLong:
    """超长 token"""

    def test_exactly_10240_passes(self):
        _validate_token_format("x" * 10240)

    def test_10241_raises_413(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("x" * 10241)
        assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "过长" in exc_info.value.detail


class TestValidateTokenFormatNullBytes:
    """null bytes 检测"""

    def test_null_byte_at_start_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("\x00abc")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_null_byte_at_end_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("abc\x00")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_null_byte_in_middle_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("ab\x00cd")
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_null_bytes_passes(self):
        _validate_token_format("valid-token-string")


class TestValidateTokenFormatCustomLabel:
    """自定义 token_label 透传到错误信息"""

    def test_custom_label_in_empty_error(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("", token_label="Refresh Token")
        assert "Refresh Token" in exc_info.value.detail

    def test_custom_label_in_too_long_error(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("x" * 10241, token_label="Refresh Token")
        assert "Refresh Token" in exc_info.value.detail

    def test_custom_label_in_null_byte_error(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_token_format("\x00x", token_label="API Key")
        assert "API Key" in exc_info.value.detail


class TestValidateTokenFormatNormalToken:
    """正常 token 字符串不抛异常"""

    def test_real_jwt_passes(self):
        token = generate_token("session-ok")
        _validate_token_format(token)  # 不抛异常


# ─── _decode_and_classify_jwt 边界测试 ───


class TestDecodeAndClassifyJwtValid:
    """合法 JWT 解码"""

    def test_valid_token_returns_payload(self):
        token = generate_token("session-decode")
        payload = _decode_and_classify_jwt(token)
        assert payload["sub"] == "session-decode"
        assert "exp" in payload
        assert "iat" in payload

    def test_valid_token_with_version(self):
        token = generate_token("session-v", token_version=3, view_type="desktop")
        payload = _decode_and_classify_jwt(token)
        assert payload["token_version"] == 3
        assert payload["view_type"] == "desktop"


class TestDecodeAndClassifyJwtExpired:
    """过期 JWT 分类为 TOKEN_EXPIRED"""

    def test_expired_token_classified_correctly(self):
        token = generate_token("session-expired", expires_in_hours=-1)
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt(token)
        assert exc_info.value.error_code == "TOKEN_EXPIRED"
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_token_custom_label(self):
        token = generate_token("session-expired", expires_in_hours=-1)
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt(token, "Refresh Token")
        assert "Refresh Token" in exc_info.value.detail


class TestDecodeAndClassifyJwtInvalid:
    """无效 JWT 分类为 TOKEN_INVALID"""

    def test_tampered_signature_classified_invalid(self):
        token = generate_token("session-tamper")
        # 篡改 token 的最后一个字符
        tampered = token[:-2] + ("ZZ" if token[-2:] != "ZZ" else "AA")
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt(tampered)
        assert exc_info.value.error_code == "TOKEN_INVALID"

    def test_random_string_classified_invalid(self):
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt("not-a-jwt-at-all")
        assert exc_info.value.error_code == "TOKEN_INVALID"

    def test_partial_jwt_classified_invalid(self):
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt("eyJhbGciOiJIUzI1NiJ9.broken")
        assert exc_info.value.error_code == "TOKEN_INVALID"

    def test_invalid_token_custom_label(self):
        with pytest.raises(TokenVerificationError) as exc_info:
            _decode_and_classify_jwt("garbage", "Refresh Token")
        assert "Refresh Token" in exc_info.value.detail
        assert exc_info.value.error_code == "TOKEN_INVALID"
