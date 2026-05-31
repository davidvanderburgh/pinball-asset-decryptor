"""Dutch Pinball plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import DutchPinballManufacturer


def register():
    register_manufacturer(DutchPinballManufacturer())
