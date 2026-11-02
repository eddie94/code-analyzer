from shop.services import billing


def send(message: str) -> str:
    return f"sent: {message} via {billing.__name__}"
