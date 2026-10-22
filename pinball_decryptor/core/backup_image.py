"""Files picked where a card image goes that are a BACKUP of one, not the card.

A card image is the card's bytes front to back (``.img``/``.raw``/``.bin``, what
the app's own "Save card as image…" and Win32 Disk Imager's Read write).  Disk
backup tools write their own container instead -- Macrium Reflect's
``.mrimg``/``.mrimgx``, Acronis' ``.tib``/``.tibx``, a ``.vhdx`` -- compressed
and indexed, which nothing but that tool reads.  A user who picked one was told
only "Not recognized" (Extract) or, on Emulate, "no MBR signature - not a card
image?" from deep in the rig's log (PAD-659: a Macrium backup of a Spike 2
card).

:func:`backup_kind` names such a file from its extension or its first bytes,
:func:`reason` says what it is and what to pick instead.  Reads at most a few
bytes; a device path or a file that can't be opened is never named.
"""

import os

from .rawdevice import is_device_path

#: Backup tools' own files, by extension (their headers are not documented).
_BY_EXT = {
    ".mrimg": "a Macrium Reflect backup",
    ".mrimgx": "a Macrium Reflect backup",
    ".mrbak": "a Macrium Reflect backup",
    ".tib": "an Acronis backup",
    ".tibx": "an Acronis backup",
    ".gho": "a Norton Ghost backup",
    ".v2i": "a Symantec backup",
    ".vdi": "a VirtualBox disk",
    ".dmg": "a macOS disk image",
}

#: Containers known by their first bytes, whatever the file is called.
_BY_MAGIC = (
    (b"vhdxfile", "a VHDX virtual disk"),
    (b"conectix", "a VHD virtual disk"),
    (b"KDMV", "a VMware disk"),
    (b"QFI\xfb", "a QEMU disk"),
    (b"PK\x03\x04", "a zip archive"),
    (b"7z\xbc\xaf\x27\x1c", "a 7-Zip archive"),
    (b"Rar!\x1a\x07", "a RAR archive"),
    (b"\x1f\x8b", "a gzip-compressed file"),
    (b"\xfd7zXZ\x00", "an xz-compressed file"),
    (b"BZh", "a bzip2-compressed file"),
    (b"\x28\xb5\x2f\xfd", "a zstd-compressed file"),
)

_ARCHIVES = ("archive", "compressed")


def backup_kind(path):
    """What *path* is when it is a backup or archive of a card rather than a
    card image (``"a Macrium Reflect backup"``), else ``""``."""
    if not path or is_device_path(path):
        return ""
    kind = _BY_EXT.get(os.path.splitext(path)[1].lower(), "")
    if kind:
        return kind
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return ""
    for magic, name in _BY_MAGIC:
        if head.startswith(magic):
            return name
    return ""


def reason(path, kind=None):
    """One plain paragraph for a picked backup: what it is, and what the app
    reads instead.  ``""`` when *path* is not one (*kind* skips the read when
    the caller has it already)."""
    kind = backup_kind(path) if kind is None else kind
    if not kind:
        return ""
    name = os.path.basename(path) or "This file"
    if any(w in kind for w in _ARCHIVES):
        return ("%s is %s, not a card image. Unpack it first and pick the "
                ".img or .raw inside." % (name, kind))
    return ("%s is %s, not a card image: it holds the card in a format of "
            "its own that this app cannot open. Use the card itself instead: "
            "put it in a reader and pick From SD card on Select card, or Save "
            "card as image… there to keep a .img copy."
            % (name, kind))


#: What a whole-card image is called: the app's own Save card as image, Win32
#: Disk Imager and Stern's own downloads all use one of these.
CARD_EXTS = (".raw", ".img", ".bin")

#: The files on a Spike 2 card's boot partition (the one Windows gives a
#: drive letter), by their first bytes: a device tree, the kernel.
_BOOT_FILE_MAGIC = (b"\xd0\x0d\xfe\xed",)
_ZIMAGE_MAGIC = b"\x18\x28\x6f\x01"            # at 0x24 in an ARM zImage

_USE_A_CARD = ("Pick a card image instead: Save card as image… on Select card "
               "makes one from the card in the reader.")


def not_a_card(path):
    """:func:`reason`, or why *path* is no card image at all (PAD-659), or "".

    For the Emulate tab, which runs whole-card images only.  Two more cases:

    * one of the files on the card's own boot partition - the partition
      Windows shows as a drive, so ``D:\\stern-spike2.dtb`` is what a user
      browsing to "the card" finds (Level_up did);
    * any other file with no partition table that is not even NAMED like a
      card image.  A ``.raw``/``.img``/``.bin`` without one is left to the
      run, which says so in its own words: a copy still being written can be
      all zeros at its start.
    """
    why = reason(path)
    if why or not path or is_device_path(path):
        return why
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return ""
    name = os.path.basename(path) or "This file"
    if (head.startswith(_BOOT_FILE_MAGIC)
            or head[0x24:0x28] == _ZIMAGE_MAGIC):
        return ("%s is one of the files on the card's boot partition, not a "
                "copy of the whole card. %s" % (name, _USE_A_CARD))
    if (os.path.splitext(path)[1].lower() not in CARD_EXTS
            and not (len(head) == 512 and head[510:512] == b"\x55\xaa")):
        return ("%s is not a card image: it has no partition table, so it is "
                "not a copy of a whole card. %s" % (name, _USE_A_CARD))
    return ""
