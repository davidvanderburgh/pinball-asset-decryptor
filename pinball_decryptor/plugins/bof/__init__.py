"""Barrels of Fun (BOF) plugin entry point."""


def register():
    # Imported in here, not at module level: a leaf module of this
    # package must not cost the whole app.  See plugins/__init__.py.
    from ...core.registry import register_manufacturer
    from .manufacturer import BOFManufacturer

    register_manufacturer(BOFManufacturer())
