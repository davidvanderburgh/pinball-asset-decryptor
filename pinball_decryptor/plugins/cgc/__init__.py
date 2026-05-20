"""Chicago Gaming Company plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import CGCManufacturer


def register():
    register_manufacturer(CGCManufacturer())
