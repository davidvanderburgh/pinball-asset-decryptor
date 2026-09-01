"""PinMAME classic-DMD plugins (Data East / Sega / Stern Whitestar/SAM).

The registration lives in ``manufacturer.py`` (this one entry point
registers several machines), so ``register`` is a thin forwarder rather
than a re-export — a re-export would import that module eagerly.
"""

__all__ = ["register"]


def register():
    # Imported in here, not at module level: a leaf module of this
    # package must not cost the whole app.  See plugins/__init__.py.
    from .manufacturer import register as _register

    _register()
