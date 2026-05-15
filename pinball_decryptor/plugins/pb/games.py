"""Pinball Brothers game database — internal layouts, filename prefixes,
Clonezilla ISO hints."""

# Each entry's `iso` block (if any) describes the Clonezilla restore image:
#   image_name      — directory under `home/partimag/` inside the ISO
#                     (informational; we auto-discover at runtime)
#   partition       — preferred partition (e.g. "sda2"); falls back to the
#                     largest ext4 partition if missing
#   filename_hints  — substrings matched against the ISO filename
#   subtrees        — absolute paths inside the partition to dump

GAME_DB = {
    "abba": {
        "display": "ABBA",
        "internal_dir": "game/abba",
        "filename_prefixes": ["pbap"],
        "platform": "Custom C++ on FAST Pinball hardware",
        "iso": None,
    },
    "alien": {
        "display": "Alien",
        "internal_dir": "game/alien",
        "filename_prefixes": ["pbap"],
        "platform": "Custom C++ on FAST Pinball hardware",
        "iso": {
            "image_name": "alien40",
            "partition": "sda2",
            "filename_hints": ["alien40", "alien4"],
            "subtrees": ["/game", "/opt/game"],
        },
    },
    "queen": {
        "display": "Queen",
        "internal_dir": "game/queen",
        "filename_prefixes": ["pbq"],
        "platform": "Custom C++ on FAST Pinball hardware",
        "iso": {
            "image_name": "queen20d",
            "partition": "sda2",
            "filename_hints": ["queen10", "queen20", "queen"],
            "subtrees": ["/game", "/opt/game"],
        },
    },
    "predator": {
        "display": "Predator",
        "internal_dir": "opt/game",
        "filename_prefixes": ["pbpp"],
        "platform": "Custom C++ on FAST Pinball hardware",
        "iso": None,
    },
}
