from app.service.users import get_user


def handle(user_id: int) -> str:
    return get_user(user_id)
