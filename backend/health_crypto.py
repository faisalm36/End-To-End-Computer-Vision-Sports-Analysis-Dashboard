"""AES-256-GCM encryption for health data at rest (heart rate, risk scores, risk feature snapshots).

Format of every stored value: base64( nonce(12 random bytes) || ciphertext || tag(16) ), ASCII text.
Key: settings.HEALTH_DATA_KEY = base64 of exactly 32 bytes (from backend/.env; never logged).
Passwords are NOT handled here: they are bcrypt-hashed (security.py), which is one-way by design.
"""
import base64
import binascii
import json
import os
from typing import Any, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import settings

NONCE_BYTES = 12
_AAD = b"soccer-health-v1"


class HealthKeyError(RuntimeError):
    """HEALTH_DATA_KEY is missing or malformed."""


class HealthDecryptError(RuntimeError):
    """A stored value failed authentication (tampered, truncated, or encrypted with another key)."""


def parse_key(raw: Optional[str]) -> bytes:
    if not raw or not raw.strip():
        raise HealthKeyError("HEALTH_DATA_KEY is not set (backend/.env). It must be base64 of 32 random bytes.")
    try:
        key = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise HealthKeyError("HEALTH_DATA_KEY is not valid base64 (expected base64 of 32 random bytes).") from None
    if len(key) != 32:
        raise HealthKeyError(f"HEALTH_DATA_KEY decodes to {len(key)} bytes; AES-256 needs exactly 32.")
    return key


def _aes(key: Optional[bytes] = None) -> AESGCM:
    return AESGCM(key if key is not None else parse_key(settings.HEALTH_DATA_KEY))


def key_status() -> tuple[bool, str]:
    """(ok, message) for the startup log. Never includes the key."""
    try:
        parse_key(settings.HEALTH_DATA_KEY)
        return True, "HEALTH_DATA_KEY ok (AES-256-GCM)"
    except HealthKeyError as e:
        return False, str(e)


def encrypt_bytes(data: bytes, key: Optional[bytes] = None) -> str:
    nonce = os.urandom(NONCE_BYTES)
    return base64.b64encode(nonce + _aes(key).encrypt(nonce, data, _AAD)).decode("ascii")


def decrypt_bytes(token: str, key: Optional[bytes] = None) -> bytes:
    aes = _aes(key)
    try:
        raw = base64.b64decode(token, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise HealthDecryptError("stored health value is not valid base64") from None
    if len(raw) < NONCE_BYTES + 16:
        raise HealthDecryptError("stored health value is truncated")
    try:
        return aes.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], _AAD)
    except InvalidTag:
        raise HealthDecryptError("stored health value failed authentication (tampered or wrong key)") from None


def encrypt_float(v: Optional[float], key: Optional[bytes] = None) -> Optional[str]:
    return None if v is None else encrypt_bytes(repr(float(v)).encode(), key)


def decrypt_float(token: Optional[str], key: Optional[bytes] = None) -> Optional[float]:
    return None if token is None else float(decrypt_bytes(token, key).decode())


def encrypt_json(obj: Any, key: Optional[bytes] = None) -> str:
    return encrypt_bytes(json.dumps(obj, separators=(",", ":")).encode(), key)


def decrypt_json(token: Optional[str], key: Optional[bytes] = None) -> Any:
    return None if token is None else json.loads(decrypt_bytes(token, key).decode())
