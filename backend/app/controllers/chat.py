from sqlalchemy.exc import IntegrityError

from app.repository.chat import ChatRepository
from app.services.chat import ChatService, DomainError


class ChatController:
    def __init__(self, db):
        self.db = db
        self.service = ChatService(ChatRepository(db))

    def _write(self, operation, *args):
        try:
            result = operation(*args)
            self.db.commit()
            return result
        except IntegrityError as exc:
            self.db.rollback()
            raise DomainError(
                409, "Conflict: duplicate username/membership or a referenced record changed"
            ) from exc

    def create_user(self, data):
        return self._write(self.service.create_user, data)

    def get_user(self, user_id):
        return self.service.get_user(user_id)

    def list_users(self, limit, offset):
        return self.service.list_users(limit, offset)

    def create_group(self, data):
        return self._write(self.service.create_group, data)

    def get_group(self, group_id):
        return self.service.get_group(group_id)

    def list_groups(self, limit, offset, user_id):
        return self.service.list_groups(limit, offset, user_id)

    def update_group(self, group_id, data):
        return self._write(self.service.update_group, group_id, data)

    def delete_group(self, group_id):
        return self._write(self.service.delete_group, group_id)

    def add_member(self, group_id, data):
        return self._write(self.service.add_member, group_id, data)

    def list_members(self, group_id, limit, offset):
        return self.service.list_members(group_id, limit, offset)

    def remove_member(self, group_id, user_id):
        return self._write(self.service.remove_member, group_id, user_id)

    def create_message(self, group_id, data):
        return self._write(self.service.create_message, group_id, data)

    def list_messages(self, group_id, limit, offset):
        return self.service.list_messages(group_id, limit, offset)

    def get_message(self, group_id, message_id):
        return self.service.get_message(group_id, message_id)

    def update_message(self, group_id, message_id, data):
        return self._write(self.service.update_message, group_id, message_id, data)

    def delete_message(self, group_id, message_id):
        return self._write(self.service.delete_message, group_id, message_id)
