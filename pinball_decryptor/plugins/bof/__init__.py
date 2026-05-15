"""Back of Flipper plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import BOFManufacturer


def register():
    register_manufacturer(BOFManufacturer())
