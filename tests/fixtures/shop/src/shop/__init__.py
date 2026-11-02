"""Toy shop package used by the codemap test suite."""

from .models import Order
from . import registry

__all__ = ["Order", "registry"]
