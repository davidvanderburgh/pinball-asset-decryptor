"""First-launch disclaimer text.

Shown once when the user has never accepted the terms.  Acceptance is
persisted in ``settings.json`` as a simple boolean (``disclaimer_accepted``)
and survives across app updates — the flag is intentionally NOT
versioned, so reinstalls and version bumps do not re-prompt.

After acceptance the same text stays reachable from the settings gear
(View disclaimer…), read-only.
"""


DISCLAIMER_TITLE = "Important — Read Before Use"

DISCLAIMER_HEADER = "Please read carefully before using this tool"

# Bulleted body — assembled paragraph-style so wrap behaves nicely on
# resize.
DISCLAIMER_BODY = (
    "Pinball Asset Decryptor lets you extract, modify, and repack the "
    "firmware files used by commercial pinball machines.\n"
    "\n"
    "If you install modified firmware on a physical machine, please "
    "understand:\n"
    "\n"
    "  •  Doing so WILL LIKELY VOID YOUR WARRANTY.  Manufacturers are "
    "under no obligation to honor warranty claims on machines running "
    "unsigned, third-party, or user-modified code.\n"
    "\n"
    "  •  Modifications can break gameplay, audio, video, scoring, or "
    "hardware control in subtle ways.  Some failures may only appear "
    "hours or days after install.\n"
    "\n"
    "  •  ALWAYS MAKE A COMPLETE, WORKING BACKUP before modifying a "
    "machine.  A failed, interrupted, or incorrect update can leave the "
    "machine unbootable (\"bricked\"); without a known-good backup image "
    "you may be unable to recover it.  This app is not responsible for "
    "bricked machines.\n"
    "\n"
    "  •  DO NOT contact the manufacturer's support team about issues "
    "that may have been caused — directly or indirectly — by modified "
    "code.  Revert to stock firmware before opening a support ticket, "
    "and disclose any past modifications.  Support resources exist for "
    "real defects, not for self-inflicted ones; creating noise in that "
    "queue makes the experience worse for every other owner.\n"
    "\n"
    "  •  This tool is provided \"as-is\" with no warranty of any kind. "
    " The authors and contributors accept no liability for damage to "
    "your machine, lost data, voided warranties, or other consequences "
    "of use.\n"
    "\n"
    "By clicking \"I Agree\" you acknowledge that you understand these "
    "risks, that you take full responsibility for any modifications you "
    "install on a physical machine, and that you will not create "
    "support burden for the manufacturer based on issues caused by "
    "user modifications."
)
