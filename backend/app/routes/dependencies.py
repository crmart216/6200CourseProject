from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.controllers.chat import ChatController
from app.db.session import get_db


def get_controller(db: Annotated[Session, Depends(get_db)]):
    return ChatController(db)


Controller = Annotated[ChatController, Depends(get_controller)]


def security_hook() -> None:
    """No-op for now. Replace with a verified identity dependency later."""
