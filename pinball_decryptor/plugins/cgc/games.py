"""CGC (Chicago Gaming Company) game database.

CGC ships factory installer `.img` files: raw MBR-partitioned disk images
that the machine's USB-boot kernel writes to its internal eMMC.  Layout
is consistent across all four titles:

  Installer .img:
    P1  FAT16  64 MB    uBoot + kernel + initrd
    P2  ext4   ~3 GB    Installer Debian rootfs
    P3  ext4   3-9 GB   "data" partition containing emmc.img, package.dat,
                        config.dat

  emmc.img (lives inside P3 as a regular file):
    P1  FAT16  ~64 MB   Game uBoot + kernel
    P2  ext4   ~1-3 GB  Game Debian rootfs - contains the assets

Three of CGC's four titles are WPC-emulator remakes (MM, AFM, MB) that
run the original Williams ROM under a CGC-built emulator binary
(`/home/debian/emumm/emumm`).  Each game names its data dir per-title
-- ``appdata/`` for MM, ``afmdata/`` for AFM, ``mbdata/`` for MB -- so
we extract the entire ``/home/debian/emumm/`` tree for all three:

  /home/debian/emumm/
      emumm                     game executable (ARM ELF, ~340-410 KB)
      cgc.so                    engine shared library (40-115 MB)
      <gamedata>/
          rom/<game>_<rev>.rom  original WPC ROM (drop a different
                                rev to change the game version)
          wav48000/<GAME>_*.wav 1300+ DCS audio samples pre-extracted
                                to 48 kHz mono WAV
          bootlogo.raw          raw RGB framebuffer for the splash
          logo.bmp              splash bitmap
      *.sh                      init / launch / gpio / spi scripts
      samadj.bin, samadj.bin, etc.

The fourth title (Pulp Fiction) is a CGC original on a BeagleBone Black
with a 1080p LCD backbox.  Its `pin` binary renders all video in real
time via SDL/OpenGL ES, so there are no video files to mod -- only audio:

  /home/ubuntu/pin/
      pin                       game executable (ARM ELF)
      data/pfsndui.bnk          Wwise UI sounds
      data/pfsndfx.bnk          Wwise SFX
      data/pfmusic.bnk          Wwise music
      data/pfspeech.bnk         Wwise speech (uncensored)
      data/pfspeechBEEPD.bnk    Wwise speech (clean/beeped)
      data/pfsnddiag.bnk        Wwise diagnostic sounds

Each ``filename_hints`` entry is matched case-insensitively against the
.img basename.  Detection is filename-based because reading P3 to peek
at the version string takes 20+ seconds per probe -- not acceptable for
the picker's auto-detect path.
"""

# Subtree(s) extracted from emmc.img P2 into the user's output folder.
# Tuned to "just the modifiable game assets" -- skipping /etc, /lib,
# /usr, etc. keeps the output folder ~600 MB instead of 3 GB.
GAME_DB = {
    "mm_remake": {
        "display": "Medieval Madness Remake",
        "filename_hints": ["medievalmadness", "mm_remake", "mmremake"],
        "platform": "CGC emumm (WPC emulator) on BeagleBone Black",
        "asset_subtree": "/home/debian/emumm",
        "data_dir": "appdata",
    },
    "afm_remake": {
        "display": "Attack From Mars Remake",
        "filename_hints": ["attackfrommars", "afm_remake", "afmremake"],
        "platform": "CGC emumm (WPC emulator) on BeagleBone Black",
        "asset_subtree": "/home/debian/emumm",
        "data_dir": "afmdata",
    },
    "mb_remake": {
        "display": "Monster Bash Remake",
        "filename_hints": ["monsterbash", "mb_remake", "mbremake"],
        "platform": "CGC emumm (WPC emulator) on BeagleBone Black",
        "asset_subtree": "/home/debian/emumm",
        "data_dir": "mbdata",
    },
    "pulp_fiction": {
        "display": "Pulp Fiction",
        "filename_hints": ["pulpfiction"],
        "platform": "CGC pin binary (SDL/OpenGL ES) on BeagleBone Black",
        "asset_subtree": "/home/ubuntu/pin",
        "data_dir": "data",
    },
    # Cactus Canyon remake: a CGC original-engine (`pin`) title that runs
    # the original 1998 Bally Cactus Canyon WPC-95 game ROM + DCS sound
    # ROMs under emulation, with CGC's colour-LCD art layered on.  Unlike
    # the four titles above it ships only on a physical microSD master
    # card (a paid expansion, no web download), but the card is structured
    # exactly like an installer .img (P1 boot / P2 installer rootfs / P3
    # data with emmc.img), so the same nested dd/debugfs chain applies.
    # The `pin` engine lives at /home/debian/pin (debian user, vs Pulp
    # Fiction's ubuntu user).  Assets are in ccdata/: the DCS sound ROMs
    # (rom/s2..s7.rom -> decoded to WAV via DCSExplorer), the WPC-95 game
    # ROM (rom/cc_g11.*), custom packed display art (art/wmsimg.bin,
    # newimg.bin, gels.bin), encrypted blobs (cgc.so, usb.so), fonts and
    # logos.  See docs/CC_REVISITED_RE.md.
    "cactus_canyon": {
        "display": "Cactus Canyon",
        "filename_hints": ["cactuscanyon", "cactus_canyon", "cc113",
                           "cc_113", "ccrevisited", "cactus"],
        "platform": "CGC pin binary (SDL/OpenGL ES) on BeagleBone Black",
        "asset_subtree": "/home/debian/pin",
        "data_dir": "ccdata",
    },
}
