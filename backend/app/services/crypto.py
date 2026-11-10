"""RSA key wrapping for the intentionally server-escrowed group-key demo.

RSA-2048 describes the asymmetric key size; SHA-256 is the OAEP digest.
RSA-256-bit modulus keys are not safe or large enough to wrap AES-256 keys.
"""

import base64
import binascii
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.core.config import get_settings

GROUP_KEY_BYTES = 32  # AES-256; messages are encrypted by clients, not this backend.


class InvalidKeyPayload(ValueError):
    """The supplied ciphertext or public key is not usable for key exchange."""


@lru_cache(maxsize=8)
def _private_key_for_path(path_str: str) -> rsa.RSAPrivateKey:
    """Create a durable private key once, including across concurrent API workers."""
    path = Path(path_str).expanduser()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # Write the complete PEM to a private temp file, then link into place
        # atomically. Another worker's key wins without being overwritten.
        fd, temporary = tempfile.mkstemp(prefix=".server-key-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(pem)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("Configured server key must be an RSA key of at least 2048 bits")
    return key


def _private_key() -> rsa.RSAPrivateKey:
    return _private_key_for_path(get_settings().server_private_key_path)


def _oaep_padding() -> padding.OAEP:
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    )


def public_key_pem() -> str:
    return _private_key().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def decrypt_group_key(encoded_ciphertext: str) -> bytes:
    """Unwrap a base64-encoded RSA-OAEP-SHA256 AES-256 group key."""
    try:
        ciphertext = base64.b64decode(encoded_ciphertext, validate=True)
        key = _private_key()
        if len(ciphertext) != key.key_size // 8:
            raise InvalidKeyPayload("Invalid encrypted_group_key")
        group_key = key.decrypt(ciphertext, _oaep_padding())
    except (ValueError, binascii.Error) as exc:
        raise InvalidKeyPayload("Invalid encrypted_group_key") from exc
    if len(group_key) != GROUP_KEY_BYTES:
        raise InvalidKeyPayload("Group key must contain exactly 32 bytes (AES-256)")
    return group_key


def encrypt_for_public_key(group_key: bytes, pem: str) -> str:
    """Wrap an existing group key for a new member's PEM RSA public key."""
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            raise InvalidKeyPayload("public_key must be an RSA key of at least 2048 bits")
        ciphertext = key.encrypt(group_key, _oaep_padding())
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InvalidKeyPayload("Invalid public_key; expected PEM RSA key (2048+ bits)") from exc
    return base64.b64encode(ciphertext).decode("ascii")
