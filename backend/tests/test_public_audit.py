"""The public log is an intentional (insecure) teaching/demo feature."""
import base64
import os
from datetime import datetime
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.services.crypto import _private_key_for_path

PREFIX = "/api/v1"


def make_user(client, username):
    response = client.post(f"{PREFIX}/users", json={"username": username, "display_name": username})
    assert response.status_code == 201
    return response.json()["id"]


def make_group(client, owner, name="Log room", key=None):
    data = {"name": name, "created_by": owner}
    if key is not None:
        pem = client.get(f"{PREFIX}/publickey").json()["public_key"]
        public = serialization.load_pem_public_key(pem.encode())
        wrapped = public.encrypt(key, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ))
        data["encrypted_group_key"] = base64.b64encode(wrapped).decode()
    response = client.post(f"{PREFIX}/groups", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def events(client, group_id=None, after=0):
    params = {"after": after}
    if group_id is not None:
        params["group_id"] = group_id
    response = client.get(f"{PREFIX}/logs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_encrypted_message_both_versions_sent_and_received(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_PRIVATE_KEY_PATH", str(tmp_path / "key.pem"))
    get_settings.cache_clear()
    _private_key_for_path.cache_clear()
    try:
        owner = make_user(client, "writer")
        key = AESGCM.generate_key(bit_length=256)
        group_id = make_group(client, owner, key=key)
        # New events start with the new table; existing chat data is not replayed.
        creation = events(client, group_id)
        assert [entry["event_type"] for entry in creation] == [
            "group_created", "group_key_generated_and_received"
        ]
        assert creation[1]["details"]["algorithm"] == "AES-256-GCM"
        assert creation[1]["details"]["encrypted_group_key_for_server"]
        assert "group_key_sha256" in creation[1]["details"]
        nonce = os.urandom(12)
        plaintext = "AES test — visible on public logs"
        encrypted = "enc:v1:" + base64.b64encode(nonce).decode() + ":" + base64.b64encode(
            AESGCM(key).encrypt(nonce, plaintext.encode(), None)
        ).decode()
        sent = client.post(f"{PREFIX}/groups/{group_id}/messages", json={
            "sender_id": owner, "content": encrypted
        })
        assert sent.status_code == 201, sent.text
        message_id = sent.json()["id"]
        received = events(client, group_id)[-1]
        assert received["event_type"] == "message_received"
        assert received["message_id"] == message_id
        assert received["details"]["encrypted"] == encrypted
        assert received["details"]["decrypted"] == plaintext
        assert received["details"]["sender_id"] == owner
        timestamp = datetime.fromisoformat(received["occurred_at"].replace("Z", "+00:00"))
        assert timestamp.year >= 2026
        assert UUID(received["group_id"]) == UUID(group_id)

        outbound = client.get(f"{PREFIX}/groups/{group_id}/messages")
        assert outbound.status_code == 200
        delivered = events(client, group_id)[-1]
        assert delivered["event_type"] == "messages_sent"
        assert delivered["details"]["count"] == 1
        assert delivered["details"]["messages"][0]["encrypted"] == encrypted
        assert delivered["details"]["messages"][0]["decrypted"] == plaintext

        assert client.get(f"{PREFIX}/groups/{group_id}/messages/{message_id}").status_code == 200
        assert events(client, group_id)[-1]["event_type"] == "message_sent"
        assert events(client, group_id, after=received["id"])[0]["id"] > received["id"]

        # Public API must never include server private PEM or raw AES group key.
        visible = str(events(client))
        assert "BEGIN PRIVATE KEY" not in visible
        assert key.hex() not in visible
        assert client.get(f"{PREFIX}/logs", params={"limit": 201}).status_code == 422
    finally:
        _private_key_for_path.cache_clear()
        get_settings.cache_clear()


def test_public_log_records_key_distribution_plaintext_edit_delete_and_deleted_rooms(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_PRIVATE_KEY_PATH", str(tmp_path / "server.pem"))
    get_settings.cache_clear()
    _private_key_for_path.cache_clear()
    try:
        alice = make_user(client, "aliceaudit")
        bob = make_user(client, "bobaudit")
        key = AESGCM.generate_key(bit_length=256)
        group_id = make_group(client, alice, "Project team", key)
        bob_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_pem = bob_private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        reported = client.post(f"{PREFIX}/key-events/identity-generated", json={
            "user_id": bob, "public_key": public_pem
        })
        assert reported.status_code == 201
        join = client.post(f"{PREFIX}/groups/{group_id}/members", json={
            "user_id": bob, "public_key": public_pem
        })
        assert join.status_code == 201
        assert "encrypted_group_key" in join.json()
        assert bob_private.decrypt(base64.b64decode(join.json()["encrypted_group_key"]), padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        )) == key
        recorded = events(client, group_id)
        distribution = next(e for e in recorded if e["event_type"] == "group_key_distributed")
        assert distribution["details"]["encrypted_group_key_for_member"] == join.json()["encrypted_group_key"]
        global_events = events(client)
        assert any(e["event_type"] == "client_identity_key_generated" for e in global_events)
        assert any(e["event_type"] == "server_public_key_distributed" for e in global_events)
        assert any(e["event_type"] == "server_rsa_key_generated" for e in global_events)

        message = client.post(f"{PREFIX}/groups/{group_id}/messages", json={
            "sender_id": alice, "content": "Plain message"
        }).json()
        assert events(client, group_id)[-1]["details"] == {
            "sender_id": alice, "encrypted": None, "decrypted": "Plain message", "format": "plaintext"
        }
        client.put(f"{PREFIX}/groups/{group_id}/messages/{message['id']}", json={"content": "Edited"})
        updated = events(client, group_id)[-1]
        assert updated["event_type"] == "message_updated"
        assert updated["details"]["before"]["decrypted"] == "Plain message"
        assert updated["details"]["after"]["decrypted"] == "Edited"
        client.delete(f"{PREFIX}/groups/{group_id}/messages/{message['id']}")
        assert events(client, group_id)[-1]["event_type"] == "message_deleted"
        assert client.delete(f"{PREFIX}/groups/{group_id}").status_code == 204
        assert events(client, group_id)[-1]["event_type"] == "group_deleted"
        groups = client.get(f"{PREFIX}/logs/groups")
        assert groups.status_code == 200
        assert {"id": group_id, "name": "Project team"} in groups.json()
    finally:
        _private_key_for_path.cache_clear()
        get_settings.cache_clear()


def test_corrupt_encrypted_payload_is_recorded_without_blocking_chat(client):
    owner = make_user(client, "malformed")
    group_id = make_group(client, owner)
    payload = "enc:v1:invalid-format"
    response = client.post(f"{PREFIX}/groups/{group_id}/messages", json={
        "sender_id": owner, "content": payload
    })
    assert response.status_code == 201
    event = events(client, group_id)[-1]
    assert event["details"]["encrypted"] == payload
    assert event["details"]["decrypted"] is None
    assert event["details"]["decryption_error"] == "Group key unavailable"


def test_legacy_base64_ciphertext_is_detected_when_authenticated(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_PRIVATE_KEY_PATH", str(tmp_path / "key.pem"))
    get_settings.cache_clear()
    _private_key_for_path.cache_clear()
    try:
        owner = make_user(client, "legacycipher")
        key = AESGCM.generate_key(bit_length=256)
        group_id = make_group(client, owner, key=key)
        nonce = os.urandom(12)
        encrypted = base64.b64encode(nonce + AESGCM(key).encrypt(nonce, b"old format", None)).decode()
        response = client.post(f"{PREFIX}/groups/{group_id}/messages", json={
            "sender_id": owner, "content": encrypted
        })
        assert response.status_code == 201
        entry = events(client, group_id)[-1]["details"]
        assert entry["encrypted"] == encrypted
        assert entry["decrypted"] == "old format"
        assert entry["format"] == "AES-256-GCM (legacy base64)"
    finally:
        _private_key_for_path.cache_clear()
        get_settings.cache_clear()
