"""Dutch Pinball game database and detection metadata.

Two very different on-disk formats live under one manufacturer:

* **The Big Lebowski (tbl)** — software updates are plain ``.zip`` archives
  of a Linux ``pyprocgame`` build.  Assets are ``.wav`` audio plus ``.cdmd``
  color-display video (see :mod:`.cdmd`).  No encryption.

* **Alice's Adventures in Wonderland (aaiw)** — distributed as a Clonezilla
  USB *auto-installer* ``.img``.  The real game SSD is stored inside as a
  partclone-v2 + zstd image; once reconstructed the game assets are plain
  ``.mp4`` / ``.mov`` / ``.wav`` / ``.png`` under ``/opt/assets/alice``.
"""

GAME_DB = {
    "tbl": {
        "display": "The Big Lebowski",
        "format": "zip",
        # Filename substrings that strongly imply TBL.
        "filename_hints": ["tbl", "lebowski"],
        # The asset subtree inside the update where moddable media live.
        "asset_root": "assets",
    },
    "aaiw": {
        "display": "Alice's Adventures in Wonderland",
        "format": "clonezilla_img",
        "filename_hints": ["aaiw", "alice", "wonderland"],
        # Subtree (inside the reconstructed SSD root) to extract.
        "asset_subtree": "/opt/assets/alice",
    },
}
