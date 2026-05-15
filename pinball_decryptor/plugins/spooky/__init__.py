"""Spooky Pinball plugin entry point."""

from ...core.registry import register_manufacturer
from .manufacturer import SpookyManufacturer


def register():
    register_manufacturer(SpookyManufacturer())
