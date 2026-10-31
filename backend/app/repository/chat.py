from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import Group, Membership, Message, User


class ChatRepository:
    """Only this layer issues queries. It never commits a transaction."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, model, key):
        return self.db.get(model, key)

    def add(self, entity):
        self.db.add(entity)
        self.db.flush()
        return entity

    def delete(self, entity):
        self.db.delete(entity)
        self.db.flush()

    def users(self, limit, offset):
        return list(
            self.db.scalars(
                select(User).order_by(User.created_at, User.id).limit(limit).offset(offset)
            )
        )

    def groups(self, limit, offset, user_id=None):
        query = select(Group)
        if user_id is not None:
            query = query.join(Membership).where(Membership.user_id == user_id)
        return list(
            self.db.scalars(query.order_by(Group.created_at, Group.id).limit(limit).offset(offset))
        )

    def members(self, group_id, limit, offset):
        return list(
            self.db.scalars(
                select(Membership)
                .where(Membership.group_id == group_id)
                .order_by(Membership.joined_at, Membership.user_id)
                .limit(limit)
                .offset(offset)
            )
        )

    def lock_member(self, group_id, user_id):
        # Serialize message creation against removal of this membership.
        return self.db.scalar(
            select(Membership)
            .where(Membership.group_id == group_id, Membership.user_id == user_id)
            .with_for_update()
        )

    def messages(self, group_id, limit, offset):
        return list(
            self.db.scalars(
                select(Message)
                .where(Message.group_id == group_id)
                .order_by(Message.created_at, Message.id)
                .limit(limit)
                .offset(offset)
            )
        )
