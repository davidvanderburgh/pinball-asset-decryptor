"""Stern **Spike 3** title table + filename -> game-key mapping.

Spike 3 cards are named ``<title>_<edition>-<version>.Release.64G.sdcard-secure.raw``.
The game **key** is the title stem before the version (``star_wars_2025_pro``);
the display name is a prettified form of it.

``supported`` says whether PAD can decrypt this title **offline today**.  That
turns on whether a key for it is in hand, not on the code: the extractor is the
same for every Spike 3 card.  The fleet customer-OTP unlock key is now in hand,
and it unlocks the LUKS keyslot of **every** Spike 3 card's partitions — so
every title below is decryptable.  The user still supplies that key through
their own keyfile (``$PAD_SPIKE3_KEYFILE`` / a ``*.padkeys.json`` sidecar);
nothing secret ships in the repo.  A title is greyed only if no key for it can
exist, which is no longer the case for any Spike 3 card.
"""

from __future__ import annotations

import os

# key (title stem) -> display / support.  Keep order = display order.
# All Spike 3 titles are decryptable: the fleet OTP keyfile (user-supplied)
# derives any card's master keys through its LUKS keyslots.
SPIKE3_DB = {
    "star_wars_2025_pro":      {"display": "Star Wars 2025 PRO",
                                "supported": True},
    "star_wars_2025_le":       {"display": "Star Wars 2025 LE",
                                "supported": True},
    "star_wars_elg":           {"display": "Star Wars (Elwin)",
                                "supported": True},
    "fallout_le":              {"display": "Fallout LE",
                                "supported": True},
    "pokemon_le":              {"display": "Pokemon LE",
                                "supported": True},
    "walking_dead_remastered_le": {"display": "Walking Dead Remastered LE",
                                   "supported": True},
}

#: key used when a Spike 3 card's filename matches no known title.
SPIKE3_GENERIC_KEY = "spike3_generic"


def spike3_key_for_path(path):
    """Return the Spike 3 game key for a card path (the title stem before the
    version), or :data:`SPIKE3_GENERIC_KEY` if it matches no known title."""
    stem = os.path.basename(path).split(".", 1)[0].split("-", 1)[0].lower()
    if stem in SPIKE3_DB:
        return stem
    # tolerate a trailing edition the DB keyed without, or vice versa
    for key in SPIKE3_DB:
        if stem == key or stem.startswith(key + "_") or key.startswith(stem):
            return key
    return SPIKE3_GENERIC_KEY


def spike3_display(key, path=None):
    info = SPIKE3_DB.get(key)
    if info:
        return "%s (Spike 3)" % info["display"]
    # generic: prettify the filename stem
    if path:
        stem = os.path.basename(path).split(".", 1)[0].split("-", 1)[0]
        words = [w.upper() if w.lower() in ("le", "pro", "se") else w.capitalize()
                 for w in stem.replace("_", " ").split() if w]
        if words:
            return "%s (Spike 3)" % " ".join(words)
    return "Stern Spike 3 card"
