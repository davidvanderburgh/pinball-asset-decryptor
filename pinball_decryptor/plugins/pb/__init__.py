"""Pinball Brothers plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import PBManufacturer


def register():
    register_manufacturer(PBManufacturer())
