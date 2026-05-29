"""American Pinball plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import AmericanPinballManufacturer


def register():
    register_manufacturer(AmericanPinballManufacturer())
