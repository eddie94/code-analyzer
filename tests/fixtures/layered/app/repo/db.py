from typing import TYPE_CHECKING

from app.api import users

if TYPE_CHECKING:
    from app.service.users import get_user


def load(user_id: int) -> str:
    return f"user {user_id} via {users.__name__}"
