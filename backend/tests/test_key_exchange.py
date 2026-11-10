"""Full RSA group-key exchange and backwards compatibility through the HTTP API."""

import base64
import os

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.services.crypto import _private_key_for_path

BASE = "/api/v1"


def rsa_pair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private, public_pem


def oaep():
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
    )


def user(client, name):
    response = client.post(f"{BASE}/users", json={"username": name, "display_name": name})
    assert response.status_code == 201
    return response.json()["id"]


def wrap_with_server_key(client, group_key):
    response = client.get(f"{BASE}/publickey")
    assert response.status_code == 200
    pem = response.json()["public_key"]
    public = serialization.load_pem_public_key(pem.encode("ascii"))
    return base64.b64encode(public.encrypt(group_key, oaep())).decode("ascii")


@pytest.fixture
def isolated_server_keys(monkeypatch, tmp_path):
    key_path = tmp_path / "server-keys" / "server.pem"
    monkeypatch.setenv("SERVER_PRIVATE_KEY_PATH", str(key_path))
    get_settings.cache_clear()
    _private_key_for_path.cache_clear()
    yield key_path
    _private_key_for_path.cache_clear()
    get_settings.cache_clear()


def test_public_key_persists_and_private_key_is_never_served(client, isolated_server_keys):
    first = client.get(f"{BASE}/publickey").json()
    assert list(first) == ["public_key"]
    assert "BEGIN PUBLIC KEY" in first["public_key"]
    assert "PRIVATE KEY" not in first["public_key"]
    assert isolated_server_keys.is_file()
    if os.name == "posix":
        assert isolated_server_keys.stat().st_mode & 0o077 == 0
    _private_key_for_path.cache_clear()  # Simulates another process/restart.
    assert client.get(f"{BASE}/publickey").json() == first
    assert "/api/v1/publickey" in client.get("/openapi.json").json()["paths"]


def test_alice_and_bob_can_exchange_key_and_read_old_encrypted_messages(
    client, isolated_server_keys
):
    alice = user(client, "alice")
    bob = user(client, "bob")
    symmetric_key = AESGCM.generate_key(bit_length=256)
    encrypted_group_key = wrap_with_server_key(client, symmetric_key)
    response = client.post(
        f"{BASE}/groups",
        json={
            "name": "Secure-ish chat",
            "description": "Insecure key escrow demo",
            "created_by": alice,
            "encrypted_group_key": encrypted_group_key,
        },
    )
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]
    assert "symmetric_key" not in response.json()
    assert "encrypted_group_key" not in response.json()
    assert "symmetric_key" not in client.get(f"{BASE}/groups/{group_id}").json()
    assert "symmetric_key" not in str(client.get(f"{BASE}/groups").json())

    # The API retains its original message CRUD contract: clients can submit ciphertext.
    nonce = os.urandom(12)
    ciphertext = AESGCM(symmetric_key).encrypt(nonce, b"Secret written before Bob joined", None)
    message_content = base64.b64encode(nonce + ciphertext).decode("ascii")
    sent = client.post(
        f"{BASE}/groups/{group_id}/messages",
        json={"sender_id": alice, "content": message_content},
    )
    assert sent.status_code == 201, sent.text

    # No membership or key is granted if a new user does not supply their RSA public key.
    missing = client.post(f"{BASE}/groups/{group_id}/members", json={"user_id": bob})
    assert missing.status_code == 422
    assert len(client.get(f"{BASE}/groups/{group_id}/members").json()) == 1

    bob_private, bob_public = rsa_pair()
    joined = client.post(
        f"{BASE}/groups/{group_id}/members",
        json={"user_id": bob, "public_key": bob_public},
    )
    assert joined.status_code == 201, joined.text
    joined_data = joined.json()
    assert joined_data["group_id"] == group_id
    assert joined_data["user_id"] == bob
    assert "encrypted_group_key" in joined_data
    encrypted_for_bob = base64.b64decode(joined_data["encrypted_group_key"], validate=True)
    assert encrypted_for_bob != base64.b64decode(encrypted_group_key)
    decrypted_key = bob_private.decrypt(encrypted_for_bob, oaep())
    assert decrypted_key == symmetric_key

    prior_message = client.get(f"{BASE}/groups/{group_id}/messages").json()[0]["content"]
    payload = base64.b64decode(prior_message)
    assert AESGCM(decrypted_key).decrypt(payload[:12], payload[12:], None) == (
        b"Secret written before Bob joined"
    )
    # Listing members should not accidentally disclose any key material.
    assert "encrypted_group_key" not in str(
        client.get(f"{BASE}/groups/{group_id}/members").json()
    )


def test_invalid_payloads_are_rejected_without_creating_rows(client, isolated_server_keys):
    alice, bob = user(client, "alice"), user(client, "bob")
    for bad_key in ("not base64 *", base64.b64encode(os.urandom(256)).decode("ascii")):
        response = client.post(
            f"{BASE}/groups",
            json={"name": "Bad", "created_by": alice, "encrypted_group_key": bad_key},
        )
        assert response.status_code == 422, response.text
    # The OAEP plaintext must be a 32-byte AES-256 key.
    short_key = wrap_with_server_key(client, b"short")
    assert (
        client.post(
            f"{BASE}/groups",
            json={"name": "Bad", "created_by": alice, "encrypted_group_key": short_key},
        ).status_code
        == 422
    )
    assert client.get(f"{BASE}/groups").json() == []

    good_key = wrap_with_server_key(client, os.urandom(32))
    group_id = client.post(
        f"{BASE}/groups",
        json={"name": "Encrypted", "created_by": alice, "encrypted_group_key": good_key},
    ).json()["id"]
    for bad_public_key in ("not a key", rsa_pair()[1].replace("PUBLIC KEY", "PRIVATE KEY")):
        response = client.post(
            f"{BASE}/groups/{group_id}/members",
            json={"user_id": bob, "public_key": bad_public_key},
        )
        assert response.status_code == 422, response.text
    assert len(client.get(f"{BASE}/groups/{group_id}/members").json()) == 1


def test_legacy_group_creation_and_join_still_work(client, isolated_server_keys):
    alice, bob = user(client, "alice"), user(client, "bob")
    response = client.post(f"{BASE}/groups", json={"name": "Legacy", "created_by": alice})
    assert response.status_code == 201
    group_id = response.json()["id"]
    join = client.post(f"{BASE}/groups/{group_id}/members", json={"user_id": bob})
    assert join.status_code == 201, join.text
    assert "encrypted_group_key" not in join.json()
    assert (
        client.post(
            f"{BASE}/groups/{group_id}/messages", json={"sender_id": bob, "content": "Hi"}
        ).status_code
        == 201
    )
    assert client.get(f"{BASE}/groups/{group_id}/messages").json()[0]["content"] == "Hi"


def test_wrong_server_key_cannot_unwrap_group_key(client, isolated_server_keys):
    alice = user(client, "alice")
    unrelated_private, _ = rsa_pair()
    ciphertext = unrelated_private.public_key().encrypt(os.urandom(32), oaep())
    response = client.post(
        f"{BASE}/groups",
        json={
            "name": "Wrong key",
            "created_by": alice,
            "encrypted_group_key": base64.b64encode(ciphertext).decode("ascii"),
        },
    )
    assert response.status_code == 422
    assert client.get(f"{BASE}/groups").json() == []
