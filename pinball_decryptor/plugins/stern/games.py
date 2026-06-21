"""Stern Pinball game database and detection metadata.

Stern's modern games run on the **Spike** hardware platform and ship their
content on an SD card / SSD as a raw disk image with multiple partitions:

* A data partition holds ``image.bin`` — a single packed container of every
  audio "category-0" sound (and other assets), each encoded with a per-sound
  stream cipher whose keystream is produced by the game firmware.
* The rootfs partition holds the game executable (``game_real``) — the
  firmware that owns the codec.  The decode/replace engine drives this
  firmware (in an emulator) to recover each sound's keystream.

Currently implemented: **Spike 2** (i.MX6, unencrypted ext4 card).  The audio
codec is fully reverse-engineered — every cat-0 sound decodes to WAV from
``image.bin`` + ``game_real`` alone, and new audio can be re-encoded back in
(size-neutral), bit-exact, for all 32 codec "scale" variants, mono and stereo.

Nothing title-specific is bundled: every sound's decode params are derived at
runtime by driving the card's own ``game_real`` firmware, then cached by a
fingerprint of ``game_real`` + ``image.bin`` (so re-runs are instant).  A new
Spike 2 title works as soon as its card is recognized.
"""

# Every Stern Spike 2 title.  The engine is title-agnostic (any Spike 2 card is
# recognised by its partition signature and decoded from its own firmware — see
# formats.detect_game), so this list isn't what makes a card *work*; it gives the
# picker a full roster and lets a recognised card show its proper title instead
# of a name derived from the filename.  ``filename_hints`` are substrings matched
# (case-insensitively) against the card filename to pick the title.
GAME_DB = {
    "star_wars":      {"display": "Star Wars (Spike 2)",
                       "filename_hints": ["star_wars", "starwars", "star wars"]},
    "guardians":      {"display": "Guardians of the Galaxy (Spike 2)",
                       "filename_hints": ["guardians"]},
    "iron_maiden":    {"display": "Iron Maiden (Spike 2)",
                       "filename_hints": ["iron_maiden", "ironmaiden", "iron maiden"]},
    "deadpool":       {"display": "Deadpool (Spike 2)",
                       "filename_hints": ["deadpool"]},
    "munsters":       {"display": "The Munsters (Spike 2)",
                       "filename_hints": ["munsters"]},
    "sword_of_rage":  {"display": "Black Knight: Sword of Rage (Spike 2)",
                       "filename_hints": ["sword_of_rage", "sword of rage",
                                          "black_knight", "swordofrage"]},
    "jurassic_park":  {"display": "Jurassic Park (Spike 2)",
                       "filename_hints": ["jurassic"]},
    "stranger_things": {"display": "Stranger Things (Spike 2)",
                        "filename_hints": ["stranger"]},
    "elvira3":        {"display": "Elvira's House of Horrors (Spike 2)",
                       "filename_hints": ["elvira"]},
    "tmnt":           {"display": "Teenage Mutant Ninja Turtles (Spike 2)",
                       "filename_hints": ["tmnt", "turtle", "ninja"]},
    "led_zeppelin":   {"display": "Led Zeppelin (Spike 2)",
                       "filename_hints": ["led_zeppelin", "ledzep", "zeppelin"]},
    "avengers":       {"display": "Avengers: Infinity Quest (Spike 2)",
                       "filename_hints": ["avengers"]},
    "mando":          {"display": "The Mandalorian (Spike 2)",
                       "filename_hints": ["mando", "mandalorian"]},
    "godzilla":       {"display": "Godzilla (Spike 2)",
                       "filename_hints": ["godzilla"]},
    "rush":           {"display": "Rush (Spike 2)",
                       "filename_hints": ["rush"]},
    "james_bond":     {"display": "James Bond 007 (Spike 2)",
                       "filename_hints": ["james_bond", "_bond", "007"]},
    "foo_fighters":   {"display": "Foo Fighters (Spike 2)",
                       "filename_hints": ["foo_fighters", "foofighters", "foo fighters"]},
    "venom":          {"display": "Venom (Spike 2)",
                       "filename_hints": ["venom"]},
    "john_wick":      {"display": "John Wick (Spike 2)",
                       "filename_hints": ["john_wick", "johnwick", "john wick"]},
    "uncanny_xmen":   {"display": "The Uncanny X-Men (Spike 2)",
                       "filename_hints": ["xmen", "x-men", "x_men", "uncanny"]},
    "jaws":           {"display": "Jaws (Spike 2)",
                       "filename_hints": ["jaws"]},
    "metallica":      {"display": "Metallica Remastered (Spike 2)",
                       "filename_hints": ["metallica"]},
    "dnd":            {"display": "Dungeons & Dragons (Spike 2)",
                       "filename_hints": ["dungeons", "dragons"]},
    "aerosmith":      {"display": "Aerosmith (Spike 2)",
                       "filename_hints": ["aerosmith"]},
    "king_kong":      {"display": "King Kong (Spike 2)",
                       "filename_hints": ["king_kong", "kong"]},
    "batman":         {"display": "Batman (Spike 2)",
                       "filename_hints": ["batman"]},
}
