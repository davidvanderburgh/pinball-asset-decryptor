"""Stern Pinball plugin entry point (Spike 2 audio extract + replace)."""


def register():
    # Imported in here, not at module level: a leaf module of this
    # package must not cost the whole app.  See plugins/__init__.py.
    from ...core.registry import register_manufacturer
    from .manufacturer import SternManufacturer

    register_manufacturer(SternManufacturer())
