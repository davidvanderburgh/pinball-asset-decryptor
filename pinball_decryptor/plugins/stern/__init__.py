"""Stern Pinball plugin entry point (Spike 2 audio extract + replace)."""

from ...core.registry import register_manufacturer
from .manufacturer import SternManufacturer


def register():
    register_manufacturer(SternManufacturer())
