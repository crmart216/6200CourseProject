from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import get_settings
from app.services.audit import fingerprint, log_event, message_versions

from app.models.chat import Group, Membership, Message, User
from app.repository.chat import ChatRepository
from app.services.crypto import (
    InvalidKeyPayload,
    decrypt_group_key,
    encrypt_for_public_key,
    public_key_pem,
)


class DomainError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class ChatService:
    def __init__(self, repo: ChatRepository):
        self.repo = repo

    def require(self, model, key):
        entity = self.repo.get(model, key)
        if entity is None:
            raise DomainError(404, f"{model.__name__} not found")
        return entity

    def create_user(self, data):
        return self.repo.add(User(**data.model_dump()))

    def get_user(self, user_id):
        return self.require(User, user_id)

    def list_users(self, limit, offset):
        return self.repo.users(limit, offset)

    def get_server_public_key(self):
        # Key generation happens lazily on the first request. The key file itself
        # is never written into the publicly visible audit log.
        existed = Path(get_settings().server_private_key_path).expanduser().exists()
        pem = public_key_pem()
        info = {"algorithm": "RSA-2048/OAEP-SHA256", "public_key_sha256": fingerprint(pem.encode("ascii"))}
        if not existed:
            log_event(self.repo, "server_rsa_key_generated", details=info)
        log_event(self.repo, "server_public_key_distributed", details=info)
        return {"public_key": pem}

    def identity_key_generated(self, data):
        """Browser reports its own RSA key generation; not independently verifiable."""
        self.require(User, data.user_id)
        try:
            public = serialization.load_pem_public_key(data.public_key.encode("ascii"))
        except (ValueError, TypeError, UnicodeError) as exc:
            raise DomainError(422, "Invalid RSA public key") from exc
        if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 2048:
            raise DomainError(422, "Public key must be RSA 2048 bits or larger")
        der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        log_event(self.repo, "client_identity_key_generated", user_id=data.user_id, details={
            "algorithm": f"RSA-{public.key_size}/OAEP-SHA256",
            "public_key_sha256": fingerprint(der),
            "source": "client reported; backend cannot verify local key creation",
        })
        return {"recorded": True}

    def create_group(self, data):
        self.require(User, data.created_by)
        symmetric_key = None
        if data.encrypted_group_key is not None:
            try:
                symmetric_key = decrypt_group_key(data.encrypted_group_key)
            except InvalidKeyPayload as exc:
                raise DomainError(422, str(exc)) from exc
        group = self.repo.add(
            Group(
                name=data.name,
                description=data.description,
                created_by=data.created_by,
                symmetric_key=symmetric_key,
            )
        )
        self.repo.add(Membership(group_id=group.id, user_id=data.created_by))
        log_event(self.repo, "group_created", group=group, user_id=data.created_by,
                  details={"name": group.name, "encrypted_group": symmetric_key is not None})
        if symmetric_key is not None:
            log_event(self.repo, "group_key_generated_and_received", group=group, user_id=data.created_by,
                      details={"algorithm": "AES-256-GCM", "generated_by": "client (inferred from group creation)",
                               "encrypted_group_key_for_server": data.encrypted_group_key,
                               "group_key_sha256": fingerprint(symmetric_key),
                               "action": "Backend unwrapped and escrowed the client-generated key"})
        return group

    def get_group(self, group_id):
        return self.require(Group, group_id)

    def list_groups(self, limit, offset, user_id):
        if user_id is not None:
            self.require(User, user_id)
        return self.repo.groups(limit, offset, user_id)

    def update_group(self, group_id, data):
        group = self.require(Group, group_id)
        old_name = group.name
        group.name, group.description = data.name, data.description
        log_event(self.repo, "group_updated", group=group,
                  details={"previous_name": old_name, "name": group.name, "description": group.description})
        return group

    def delete_group(self, group_id):
        group = self.require(Group, group_id)
        log_event(self.repo, "group_deleted", group=group, details={"name": group.name})
        self.repo.delete(group)

    def add_member(self, group_id, data):
        group = self.require(Group, group_id)
        self.require(User, data.user_id)
        encrypted_group_key = None
        if group.symmetric_key is not None:
            if data.public_key is None:
                raise DomainError(422, "public_key is required to join an encrypted group")
            try:
                encrypted_group_key = encrypt_for_public_key(group.symmetric_key, data.public_key)
            except InvalidKeyPayload as exc:
                raise DomainError(422, str(exc)) from exc
        member = self.repo.add(Membership(group_id=group_id, user_id=data.user_id))
        log_event(self.repo, "member_joined", group=group, user_id=data.user_id)
        if encrypted_group_key is not None:
            log_event(self.repo, "group_key_distributed", group=group, user_id=data.user_id,
                      details={"algorithm": "RSA-OAEP-SHA256", "encrypted_group_key_for_member": encrypted_group_key,
                               "recipient_public_key_sha256": fingerprint(data.public_key.encode("utf-8")),
                               "action": "Server wrapped the existing AES key for this member"})
        return {
            "group_id": member.group_id,
            "user_id": member.user_id,
            "joined_at": member.joined_at,
            "encrypted_group_key": encrypted_group_key,
        }

    def list_members(self, group_id, limit, offset):
        self.require(Group, group_id)
        return self.repo.members(group_id, limit, offset)

    def remove_member(self, group_id, user_id):
        self.require(Group, group_id)
        member = self.repo.lock_member(group_id, user_id)
        if member is None:
            raise DomainError(404, "Membership not found")
        group = self.require(Group, group_id)
        log_event(self.repo, "member_left", group=group, user_id=user_id)
        self.repo.delete(member)

    def _message_details(self, message, group):
        return {"sender_id": str(message.sender_id),
                **message_versions(message.content, group.symmetric_key)}

    def create_message(self, group_id, data):
        group = self.require(Group, group_id)
        self.require(User, data.sender_id)
        if self.repo.lock_member(group_id, data.sender_id) is None:
            raise DomainError(409, "Sender must be a group member")
        message = self.repo.add(Message(group_id=group_id, **data.model_dump()))
        log_event(self.repo, "message_received", group=group, user_id=data.sender_id,
                  message_id=message.id, details=self._message_details(message, group))
        return message

    def list_messages(self, group_id, limit, offset):
        group = self.require(Group, group_id)
        messages = self.repo.messages(group_id, limit, offset)
        if messages:
            log_event(self.repo, "messages_sent", group=group,
                      details={"endpoint": "GET /messages", "count": len(messages),
                               "messages": [{"message_id": str(m.id), **self._message_details(m, group)}
                                            for m in messages]})
        return messages

    def _find_message(self, group_id, message_id):
        message = self.require(Message, message_id)
        if message.group_id != group_id:
            raise DomainError(404, "Message not found in this group")
        return message

    def get_message(self, group_id, message_id):
        group = self.require(Group, group_id)
        message = self._find_message(group_id, message_id)
        log_event(self.repo, "message_sent", group=group, user_id=message.sender_id,
                  message_id=message.id, details=self._message_details(message, group))
        return message

    def update_message(self, group_id, message_id, data):
        group = self.require(Group, group_id)
        message = self._find_message(group_id, message_id)
        before = self._message_details(message, group)
        message.content = data.content
        message.updated_at = datetime.now(UTC)
        log_event(self.repo, "message_updated", group=group, user_id=message.sender_id,
                  message_id=message.id,
                  details={"before": before, "after": self._message_details(message, group)})
        return message

    def delete_message(self, group_id, message_id):
        group = self.require(Group, group_id)
        message = self._find_message(group_id, message_id)
        log_event(self.repo, "message_deleted", group=group, user_id=message.sender_id,
                  message_id=message.id, details=self._message_details(message, group))
        self.repo.delete(message)

    def list_audit_events(self, group_id, after, limit):
        return self.repo.audit_events(group_id, after, limit)

    def list_audit_groups(self):
        return self.repo.audit_groups()
