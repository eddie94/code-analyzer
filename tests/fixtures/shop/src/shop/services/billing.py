from shop import Order
import requests

try:
    import ujson as json
except ImportError:
    import json


class Invoice:
    def __init__(self, order: Order) -> None:
        self.order = order

    async def pay(self) -> str:
        from ..notify import send

        return send(json.dumps({"total": self.order.total()}))
