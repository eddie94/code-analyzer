from app.repo import db


def get_user(user_id: int) -> str:
    return db.load(user_id)
