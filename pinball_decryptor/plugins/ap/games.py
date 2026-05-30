"""American Pinball game database, format constants, and decryption key.

Everything the rest of the ``ap`` plugin needs to know about a title beyond
the code itself: the (universal) AES key, the filename hints used for
detection + display, and Clonezilla image hints (reserved for future ISO
support).
"""

# ---------------------------------------------------------------------------
# Encryption key
# ---------------------------------------------------------------------------

# AES-256-CBC key for American Pinball "*-gamecode_*.pkg" game-code updates.
#
# Source: ``PACKAGE_SIGNING_KEY`` in /usr/bin/pkgprocess on the Houdini,
# Oktoberfest and Hot Wheels Clonezilla restore images.  It is identical on
# all three images and also decrypts the 2024 Barry-O's BBQ package, so it is
# a single static key shared across the entire product line (2020-2024).
#
# pkgprocess passes the 32-character string straight to PyCrypto's
# ``AES.new(key, ...)``, i.e. the ASCII bytes ARE the key -> AES-256.
AP_AES_KEY = b"2f5fc7a0cae8aaf63aef767ceb998b7f"

# AES chunk size — matches the original pkgprocess (24 KiB).
AES_CHUNK_SIZE = 24 * 1024


# ---------------------------------------------------------------------------
# Game database
# ---------------------------------------------------------------------------
# American Pinball games run a P-ROC / pyprocgame (SkeletonGame) Python stack
# on a Linux SSD.  The decrypted .pkg payload is a ZIP of the game tree.
#
# Each entry's optional ``iso`` block describes the Clonezilla restore image
# (filename hints only for now — partclone ext4 restore is not yet wired up).

GAME_DB = {
    "houdini": {
        "display": "Houdini: Master of Mystery",
        "internal_dir": "houdini",
        "platform": "Arch Linux, P-ROC, Python 2 / pyprocgame",
        "iso": {"filename_hints": ["houdini"]},
    },
    "oktoberfest": {
        "display": "Oktoberfest: Pinball on Tap",
        "internal_dir": "oktoberfest",
        "platform": "Linux, P-ROC, Python 2 / pyprocgame",
        "iso": {"filename_hints": ["okto"]},
    },
    "hot_wheels": {
        "display": "Hot Wheels",
        "internal_dir": "hotwheels",
        "platform": "Linux, P-ROC, Python 2 / pyprocgame",
        "iso": {"filename_hints": ["hot_wheels", "hotwheels", "hot wheels"]},
    },
    "legends_of_valhalla": {
        "display": "Legends of Valhalla",
        "internal_dir": "valhalla",
        "platform": "Linux, P-ROC, pyprocgame",
        "iso": None,
    },
    "galactic_tank_force": {
        "display": "Galactic Tank Force",
        "internal_dir": "gtf",
        "platform": "Linux, P-ROC, pyprocgame",
        "iso": None,
    },
    "bbq": {
        "display": "Barry-O's BBQ",
        "internal_dir": "bbq",
        "platform": "Linux, P-ROC, pyprocgame (ApiLib)",
        "iso": None,
    },
}


# ---------------------------------------------------------------------------
# Filename-based detection
# ---------------------------------------------------------------------------

# Lowercased substring -> game_key, matched against the .pkg basename.
# AP names its updates like "houdini-gamecode_21.10.25.pkg", so a simple
# substring hit picks the right title.  Checked in order; first match wins.
PKG_FILENAME_PATTERNS = [
    ("houdini",     "houdini"),
    ("oktoberfest", "oktoberfest"),
    ("okto",        "oktoberfest"),
    ("hotwheels",   "hot_wheels"),
    ("hot_wheels",  "hot_wheels"),
    ("hot-wheels",  "hot_wheels"),
    ("valhalla",    "legends_of_valhalla"),
    ("lov",         "legends_of_valhalla"),
    ("galactic",    "galactic_tank_force"),
    ("gtf",         "galactic_tank_force"),
    ("tank",        "galactic_tank_force"),
    ("bbq",         "bbq"),
]
