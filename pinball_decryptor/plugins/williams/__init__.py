"""Williams (WPC-era) plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import WilliamsManufacturer


def register():
    register_manufacturer(WilliamsManufacturer())
