"""Jersey Jack Pinball plugin entry point."""

# Lifted from the upstream JJP package; kept for any code that does
# `from . import __version__`.
__version__ = "3.7.0"


from ...core.registry import register_manufacturer
from .manufacturer import JJPManufacturer


def register():
    register_manufacturer(JJPManufacturer())
