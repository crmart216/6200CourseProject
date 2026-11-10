"""Audit helpers. Only publish ciphertext, plaintext and public-key metadata.

Never place private keys or unwrapped AES group keys in this public database.
"""
import base64
import binascii
import hashlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models.audit import AuditEvent


CIPHER_PREFIX = "enc:v1:"


def fingerprint(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def message_versions(content: str, group_key: bytes | None) -> dict:
    """Decode browser AES-GCM format; never make log failures block a message.

    A malformed ciphertext is still captured verbatim, with an explicit error.
    """
    if not content.startswith(CIPHER_PREFIX):
        # Early key-exchange clients used base64(nonce || AES-GCM ciphertext)
        # without an enc:v1 prefix. Detect only when authentication succeeds;
        # otherwise preserve arbitrary/plaintext content verbatim.
        if group_key is not None:
            try:
                combined = base64.b64decode(content, validate=True)
                if len(combined) >= 28:
                    plaintext = AESGCM(group_key).decrypt(combined[:12], combined[12:], None)
                    return {"encrypted": content, "decrypted": plaintext.decode("utf-8"),
                            "format": "AES-256-GCM (legacy base64)"}
            except (ValueError, UnicodeDecodeError, binascii.Error, InvalidTag):
                pass
        return {"encrypted": None, "decrypted": content, "format": "plaintext"}
    data = {"encrypted": content, "decrypted": None, "format": "AES-256-GCM (enc:v1)"}
    if group_key is None:
        data["decryption_error"] = "Group key unavailable"
        return data
    try:
        parts = content[len(CIPHER_PREFIX):].split(":")
        if len(parts) != 2:
            raise ValueError("Invalid encrypted message format")
        iv, ciphertext = (base64.b64decode(p, validate=True) for p in parts)
        if len(iv) != 12 or len(ciphertext) < 16:
            raise ValueError("Invalid AES-GCM nonce or ciphertext length")
        data["decrypted"] = AESGCM(group_key).decrypt(iv, ciphertext, None).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error, InvalidTag) as exc:
        data["decryption_error"] = type(exc).__name__
    return data


def log_event(repo, event_type: str, *, group=None, group_id=None, user_id=None,
              message_id=None, details=None):
    return repo.add(AuditEvent(
        event_type=event_type,
        group_id=group.id if group is not None else group_id,
        group_name=group.name if group is not None else None,
        user_id=user_id,
        message_id=message_id,
        details=details or {},
    ))
