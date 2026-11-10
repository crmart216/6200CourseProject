from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Content = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(Input):
    username: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$"
        ),
    ]
    display_name: Name


class UserRead(Output):
    id: UUID
    username: str
    display_name: str
    created_at: datetime


class GroupCreate(Input):
    name: Name
    description: str = Field(default="", max_length=2000)
    created_by: UUID
    # Base64 RSA-OAEP-SHA256 ciphertext containing exactly 32 AES-256 key bytes.
    # Optional so pre-existing plaintext clients continue to function.
    encrypted_group_key: (
        Annotated[str, StringConstraints(min_length=1, max_length=8192)] | None
    ) = None


class GroupUpdate(Input):
    name: Name
    description: str = Field(default="", max_length=2000)


class GroupRead(Output):
    id: UUID
    name: str
    description: str
    created_by: UUID
    created_at: datetime


class MemberCreate(Input):
    user_id: UUID
    # Required when joining a group with a symmetric key. PEM-encoded RSA public key.
    public_key: Annotated[str, StringConstraints(min_length=1, max_length=8192)] | None = None


class MemberRead(Output):
    group_id: UUID
    user_id: UUID
    joined_at: datetime


class MemberJoinRead(MemberRead):
    # Included only when joining a group with a symmetric key.
    encrypted_group_key: str | None = None


class ServerPublicKeyRead(Output):
    public_key: str


class MessageCreate(Input):
    sender_id: UUID
    content: Content


class MessageUpdate(Input):
    content: Content


class MessageRead(Output):
    id: UUID
    group_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime | None


class ErrorRead(BaseModel):
    detail: str


class IdentityKeyGenerated(Input):
    user_id: UUID
    public_key: Annotated[str, StringConstraints(min_length=1, max_length=8192)]


class AuditEventRead(Output):
    @field_serializer("occurred_at")
    def serialize_timestamp(self, value: datetime) -> str:
        # SQLite drops tzinfo; persisted events are always UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    id: int
    occurred_at: datetime
    event_type: str
    group_id: UUID | None
    group_name: str | None
    user_id: UUID | None
    message_id: UUID | None
    details: dict


class AuditGroupRead(Output):
    id: UUID
    name: str
