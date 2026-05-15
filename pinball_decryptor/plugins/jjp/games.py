"""JJP game database for the unified-app plugin.

A superset of :data:`config.KNOWN_GAMES` (which the underlying JJP pipeline
uses for runtime filesystem detection).  This adds games shipped on Jersey
Jack hardware that don't decrypt cleanly via the standalone pipeline yet
but should still light up the GUI's "Detected: …" badge from the filename.
"""

# game_key -> display name + filename-prefix list (case-insensitive substring
# match against the ISO basename)
GAME_DB = {
    "wonka": {
        "display": "Willy Wonka & the Chocolate Factory",
        "filename_prefixes": ["wonka"],
        "supported": True,
    },
    "guns_n_roses": {
        "display": "Guns N' Roses",
        "filename_prefixes": ["gunsnroses", "gnr"],
        "supported": True,
    },
    "elton_john": {
        "display": "Elton John",
        "filename_prefixes": ["eltonjohn", "elton"],
        "supported": True,
    },
    "the_hobbit": {
        "display": "The Hobbit",
        "filename_prefixes": ["hobbit"],
        "supported": True,
    },
    "the_godfather": {
        "display": "The Godfather",
        "filename_prefixes": ["godfather"],
        "supported": True,
    },
    "avatar": {
        "display": "Avatar",
        "filename_prefixes": ["avatar"],
        "supported": True,
    },
    # --- Older Jersey Jack titles --------------------------------------
    "pirates_of_the_caribbean": {
        "display": "Pirates of the Caribbean",
        "filename_prefixes": ["pirates", "potc"],
        "supported": True,
    },
    "wizard_of_oz": {
        "display": "The Wizard of Oz",
        "filename_prefixes": ["wizardofoz", "woz"],
        "supported": True,
    },
    "toy_story": {
        "display": "Toy Story 4",
        "filename_prefixes": ["toystory"],
        "supported": True,
    },
    "dialed_in": {
        "display": "Dialed In!",
        "filename_prefixes": ["dialedin"],
        "supported": True,
    },
    "harry_potter": {
        "display": "Harry Potter",
        "filename_prefixes": ["harrypotter"],
        "supported": True,
    },
}


def detect_iso_game(iso_path):
    """Return ``(game_key, display)`` for *iso_path*, or ``(None, None)``."""
    import os

    name = os.path.basename(iso_path).lower()
    for key, info in GAME_DB.items():
        for prefix in info["filename_prefixes"]:
            if prefix in name:
                return key, info["display"]
    return None, None
