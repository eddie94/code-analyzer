"""Domain models."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shop.services.billing import Invoice


class Base:
    pass


@dataclasses.dataclass
class Order(Base):
    """An order.

    Longer description.
    """

    items: list[int]

    # A comment line.
    def total(self, invoice: Invoice | None = None) -> int:
        if not self.items:
            return 0
        return sum(i for i in self.items if i > 0) or 0
