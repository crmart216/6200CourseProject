from datetime import UTC, datetime

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
        return {"public_key": public_key_pem()}

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
        return group

    def get_group(self, group_id):
        return self.require(Group, group_id)

    def list_groups(self, limit, offset, user_id):
        if user_id is not None:
            self.require(User, user_id)
        return self.repo.groups(limit, offset, user_id)

    def update_group(self, group_id, data):
        group = self.require(Group, group_id)
        group.name, group.description = data.name, data.description
        return group

    def delete_group(self, group_id):
        self.repo.delete(self.require(Group, group_id))

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
        self.repo.delete(member)

    def create_message(self, group_id, data):
        self.require(Group, group_id)
        self.require(User, data.sender_id)
        if self.repo.lock_member(group_id, data.sender_id) is None:
            raise DomainError(409, "Sender must be a group member")
        return self.repo.add(Message(group_id=group_id, **data.model_dump()))

    def list_messages(self, group_id, limit, offset):
        self.require(Group, group_id)
        return self.repo.messages(group_id, limit, offset)

    def get_message(self, group_id, message_id):
        message = self.require(Message, message_id)
        if message.group_id != group_id:
            raise DomainError(404, "Message not found in this group")
        return message

    def update_message(self, group_id, message_id, data):
        message = self.get_message(group_id, message_id)
        message.content = data.content
        message.updated_at = datetime.now(UTC)
        return message

    def delete_message(self, group_id, message_id):
        self.repo.delete(self.get_message(group_id, message_id))
