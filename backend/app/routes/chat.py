from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.routes.dependencies import Controller, security_hook
from app.schemas.chat import (
    ErrorRead,
    GroupCreate,
    GroupRead,
    GroupUpdate,
    MemberCreate,
    MemberJoinRead,
    MemberRead,
    MessageCreate,
    MessageRead,
    MessageUpdate,
    ServerPublicKeyRead,
    UserCreate,
    UserRead,
)

router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(security_hook)],
    responses={404: {"model": ErrorRead}, 409: {"model": ErrorRead}},
)
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/publickey", response_model=ServerPublicKeyRead, tags=["Key exchange"])
def get_server_public_key(controller: Controller):
    """Get the server's persistent PEM RSA public key for RSA-OAEP-SHA256 encryption."""
    return controller.get_server_public_key()


@router.post("/users", response_model=UserRead, status_code=201, tags=["Users"])
def create_user(controller: Controller, data: UserCreate):
    """Create user."""
    return controller.create_user(data)


@router.get("/users", response_model=list[UserRead], status_code=200, tags=["Users"])
def list_users(controller: Controller, limit: Limit = 50, offset: Offset = 0):
    """List users."""
    return controller.list_users(limit, offset)


@router.get("/users/{user_id}", response_model=UserRead, status_code=200, tags=["Users"])
def get_user(controller: Controller, user_id: UUID):
    """Get user."""
    return controller.get_user(user_id)


@router.post("/groups", response_model=GroupRead, status_code=201, tags=["Groups"])
def create_group(controller: Controller, data: GroupCreate):
    """Create group."""
    return controller.create_group(data)


@router.get("/groups", response_model=list[GroupRead], status_code=200, tags=["Groups"])
def list_groups(
    controller: Controller, limit: Limit = 50, offset: Offset = 0, user_id: UUID | None = None
):
    """List groups."""
    return controller.list_groups(limit, offset, user_id)


@router.get("/groups/{group_id}", response_model=GroupRead, status_code=200, tags=["Groups"])
def get_group(controller: Controller, group_id: UUID):
    """Get group."""
    return controller.get_group(group_id)


@router.put("/groups/{group_id}", response_model=GroupRead, status_code=200, tags=["Groups"])
def update_group(controller: Controller, group_id: UUID, data: GroupUpdate):
    """Update group."""
    return controller.update_group(group_id, data)


@router.delete("/groups/{group_id}", response_model=None, status_code=204, tags=["Groups"])
def delete_group(controller: Controller, group_id: UUID):
    """Delete group."""
    return controller.delete_group(group_id)


@router.post(
    "/groups/{group_id}/members",
    response_model=MemberJoinRead,
    response_model_exclude_none=True,
    status_code=201,
    tags=["Members"],
)
def add_member(controller: Controller, group_id: UUID, data: MemberCreate):
    """Add member."""
    return controller.add_member(group_id, data)


@router.get(
    "/groups/{group_id}/members", response_model=list[MemberRead], status_code=200, tags=["Members"]
)
def list_members(controller: Controller, group_id: UUID, limit: Limit = 50, offset: Offset = 0):
    """List members."""
    return controller.list_members(group_id, limit, offset)


@router.delete(
    "/groups/{group_id}/members/{user_id}", response_model=None, status_code=204, tags=["Members"]
)
def remove_member(controller: Controller, group_id: UUID, user_id: UUID):
    """Remove member."""
    return controller.remove_member(group_id, user_id)


@router.post(
    "/groups/{group_id}/messages", response_model=MessageRead, status_code=201, tags=["Messages"]
)
def create_message(controller: Controller, group_id: UUID, data: MessageCreate):
    """Create message."""
    return controller.create_message(group_id, data)


@router.get(
    "/groups/{group_id}/messages",
    response_model=list[MessageRead],
    status_code=200,
    tags=["Messages"],
)
def list_messages(controller: Controller, group_id: UUID, limit: Limit = 50, offset: Offset = 0):
    """List messages."""
    return controller.list_messages(group_id, limit, offset)


@router.get(
    "/groups/{group_id}/messages/{message_id}",
    response_model=MessageRead,
    status_code=200,
    tags=["Messages"],
)
def get_message(controller: Controller, group_id: UUID, message_id: UUID):
    """Get message."""
    return controller.get_message(group_id, message_id)


@router.put(
    "/groups/{group_id}/messages/{message_id}",
    response_model=MessageRead,
    status_code=200,
    tags=["Messages"],
)
def update_message(controller: Controller, group_id: UUID, message_id: UUID, data: MessageUpdate):
    """Update message."""
    return controller.update_message(group_id, message_id, data)


@router.delete(
    "/groups/{group_id}/messages/{message_id}",
    response_model=None,
    status_code=204,
    tags=["Messages"],
)
def delete_message(controller: Controller, group_id: UUID, message_id: UUID):
    """Delete message."""
    return controller.delete_message(group_id, message_id)
