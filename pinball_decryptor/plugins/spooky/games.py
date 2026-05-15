"""Spooky Pinball game database, format constants, and per-format USB hints.

This module holds everything the rest of the spooky plugin needs to know
about a game beyond the source code itself: encryption keys, GPG passphrases,
filename patterns, file-format types, and USB naming conventions.
"""

# ---------------------------------------------------------------------------
# Encryption keys & passphrases
# ---------------------------------------------------------------------------

# AES-256-CBC key for Rick & Morty .pkg files
# Source: pkgprocess script on R&M restore ISO
RM_AES_KEY = rb"4t7w!z%C*F-J@NcRfUjXn2r5u8x/A?D("

# AES-256-CBC key for Alice Cooper .pkg files
# Source: pkgprocess script on Halloween H78 Clonezilla restore image
AC_AES_KEY = rb"cc180ac8e1239a56fcc5d3dcccccaaac"

# AES chunk size (matches original pkgprocess)
AES_CHUNK_SIZE = 24 * 1024

# GPG symmetric passphrases for .pkg files
# Source: Assembly-CSharp.dll (Unity C#) on game partition of Clonezilla images
UM_GPG_PASSPHRASE = "DSgosjd34sDGok42Dfojjos"
H78_GPG_PASSPHRASE = "SDsfksjg23fhusjgwihwgQosjd"

GPG_PASSPHRASES = {
    "um_pkg": UM_GPG_PASSPHRASE,
    "h78_pkg": H78_GPG_PASSPHRASE,
}

# GPG signing key ID for Beetlejuice
BJ_GPG_KEYID = "A25DAD3A15F2B254"


# ---------------------------------------------------------------------------
# Game database
# ---------------------------------------------------------------------------
# Format types:
#   rm_pkg         - AES-256-CBC encrypted ZIP (R&M, key known)
#   ac_pkg         - AES-256-CBC encrypted ZIP (AC, key known)
#   aes_pkg        - AES-256-CBC encrypted ZIP (TNA, key unknown)
#   um_pkg         - GPG symmetric encrypted tar.gz (Ultraman)
#   h78_pkg        - GPG symmetric encrypted tar.gz (Halloween)
#   tar_gz         - plain tar.gz (ED, Scooby, TCM)
#   gpg_tar_gz     - GPG-signed tar.gz (Beetlejuice)
#   plain_tar      - plain tar (Looney Tunes .looney)
#   plain_zip      - plain ZIP archive (P3 DMD games)
#   clonezilla     - Clonezilla restore image

GAME_DB = {
    "rick_and_morty": {
        "display": "Rick and Morty",
        "platform": "Arch Linux, P-ROC, Python 2 / pyprocgame",
        "era": "warden",
    },
    "evil_dead": {
        "display": "Evil Dead",
        "platform": 'Debian Linux ("Haunted Mansion"), Warden hardware',
        "era": "warden",
    },
    "scooby_doo": {
        "display": "Scooby-Doo",
        "platform": "Debian Linux, eMMC, Unity engine",
        "era": "warden",
    },
    "beetlejuice": {
        "display": "Beetlejuice",
        "platform": "Debian Linux, Warden hardware, Unity engine",
        "era": "warden",
    },
    "texas_chainsaw": {
        "display": "Texas Chainsaw Massacre",
        "platform": "Debian Linux, eMMC, Unity engine, Warden hardware",
        "era": "warden",
    },
    "alice_cooper": {
        "display": "Alice Cooper's Nightmare Castle",
        "platform": "Debian Linux, eMMC, P-ROC controller",
        "era": "p_roc",
    },
    "total_nuclear": {
        "display": "Total Nuclear Annihilation",
        "platform": "Arch Linux, P-ROC controller",
        "era": "p_roc",
    },
    "halloween_78": {
        "display": "Halloween",
        "platform": "Debian Linux, eMMC, Warden hardware",
        "era": "warden",
    },
    "ultraman": {
        "display": "Ultraman",
        "platform": "Debian Linux, eMMC, Warden hardware",
        "era": "warden",
    },
    "americas_most_haunted": {
        "display": "America's Most Haunted",
        "platform": "P3 / Multimorphic platform, DMD display",
        "era": "p3",
    },
    "rob_zombie": {
        "display": "Rob Zombie's Spookshow International",
        "platform": "P3 / Multimorphic platform, DMD display",
        "era": "p3",
    },
    "dominos": {
        "display": "Domino's Spectacular Pinball Adventure",
        "platform": "P3 / Multimorphic platform, DMD display",
        "era": "p3",
    },
    "jetsons": {
        "display": "Jetsons",
        "platform": "P3 / Multimorphic platform, DMD display",
        "era": "p3",
    },
    "legends_of_tera": {
        "display": "Looney Tunes",
        "platform": "Debian Linux, eMMC/SSD, Warden hardware, Godot engine",
        "era": "warden",
    },
}


# ---------------------------------------------------------------------------
# Extension- and filename-based detection tables
# ---------------------------------------------------------------------------

# Unique extensions: ext -> (game_key, format_type)
KNOWN_GAMES = {
    ".ed":          ("evil_dead",       "tar_gz"),
    ".scooby":      ("scooby_doo",      "tar_gz"),
    ".beetlejuice": ("beetlejuice",     "gpg_tar_gz"),
    ".looney":      ("legends_of_tera", "plain_tar"),
}

# Filename pattern -> (game_key, format_type) for .pkg files
# Checked in order; first match wins.
PKG_FILENAME_PATTERNS = [
    ("rm-gamecode",  "rick_and_morty",  "rm_pkg"),
    ("ac-gamecode",  "alice_cooper",    "ac_pkg"),
    ("tna-gamecode", "total_nuclear",   "aes_pkg"),
    ("code_UM",      "ultraman",        "um_pkg"),
    ("code_H78",     "halloween_78",    "h78_pkg"),
    ("tcm-",         "texas_chainsaw",  "tar_gz"),
]

# Filename patterns for .zip game update files (NOT Clonezilla)
ZIP_GAME_PATTERNS = [
    ("AMH",      "americas_most_haunted", "plain_zip"),
    ("rzupdate", "rob_zombie",            "plain_zip"),
    ("DOM_",     "dominos",               "plain_zip"),
    ("Jetsons",  "jetsons",               "plain_zip"),
]


# ---------------------------------------------------------------------------
# Per-engine routing (drives loose-asset extraction after decompression)
# ---------------------------------------------------------------------------

# Games that use Unity (need UnityPy for loose asset extraction)
UNITY_GAMES = {"Beetlejuice", "Scooby-Doo", "Texas Chainsaw Massacre",
               "Halloween", "Ultraman"}

# Games that use Godot (assets embedded in PCK inside executable)
GODOT_GAMES = {"Looney Tunes"}

# P3 DMD games (Ben Heck's Multimorphic P3 platform)
P3_GAMES = {"America's Most Haunted",
            "Rob Zombie's Spookshow International",
            "Domino's Spectacular Pinball Adventure",
            "Jetsons"}


# ---------------------------------------------------------------------------
# USB naming conventions for machine updates (for the "How to install" hint)
# ---------------------------------------------------------------------------

USB_NAMING = {
    ".pkg": "rm-gamecode-YYYYMMDD.pkg",
    ".ed": "YYYY.MM.DD.ed",
    ".scooby": "vYYYY.MM.DD.HH.scooby",
    ".beetlejuice": "vYYYY.MM.DD.HH.beetlejuice",
    ".looney": "YYYY.MM.DD.looney",
}
