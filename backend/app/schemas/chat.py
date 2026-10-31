from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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


class MemberRead(Output):
    group_id: UUID
    user_id: UUID
    joined_at: datetime


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
