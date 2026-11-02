from shop.models import Order


def check_total() -> None:
    assert Order([1, 2]).total() == 3
