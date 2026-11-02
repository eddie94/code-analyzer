import os


class Settings:
    shelf_path: str = os.environ.get("SHELF_PATH", "shelf.db")
