"""Back of Flipper game database + pipeline tunables."""

GAME_DB = {
    "labyrinth": {
        "display": "Jim Henson's Labyrinth",
        "fun_file": "lab.fun",
        "passphrase": "funkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "dune": {
        "display": "Dune",
        "fun_file": "dune.fun",
        "passphrase": "dunekey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
    "winchester": {
        "display": "Winchester Mystery House",
        "fun_file": "winchester.fun",
        "passphrase": "winchesterkey",
        "platform": "Arch Linux, FAST hardware, Godot 4.5 custom build",
    },
}

# .fun filename -> game key
FUN_FILE_TO_GAME = {info["fun_file"]: key for key, info in GAME_DB.items()}


# Phase names retained for the BOF pipeline's internal logic.  The unified
# GUI uses its own EXTRACT_PHASES/WRITE_PHASES (4 phases each); BOF's 5-step
# flows render as the first 4 plus a silently-clamped tail.
DECRYPT_PHASES = ["Detect", "Decrypt", "Extract", "Checksums", "Cleanup"]
MODIFY_PHASES = ["Decrypt", "Patch", "Repack", "Encrypt", "Cleanup"]


# Timeouts for long-running shell ops (large .fun files take real time)
GPG_DECRYPT_TIMEOUT = 7200
TAR_EXTRACT_TIMEOUT = 7200
GDRE_TIMEOUT = 7200
CHECKSUM_TIMEOUT = 7200
GPG_ENCRYPT_TIMEOUT = 7200
TAR_PACK_TIMEOUT = 7200
