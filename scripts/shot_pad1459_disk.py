r"""PAD-1459 proof shot: Settings > Manage disk space on a user's PC that has the card cache's own disk.

    python scripts/shot_pad1459_disk.py <app tree> <out_dir> <prefix>

The PAD-819 shot (shot_pad819_disk.py) with one difference: beside its stand-in rows (the app's Linux, the emulators'
data disk), the tree's OWN wsl_place.items() is asked about a card cache disk - a 9 GB sparse stand-in file named by
PAD_CACHE_DISK - so a tree that knows the disk lists it and one that does not, does not. Nothing runs in WSL.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad819_disk as base  # noqa: E402

_STUB = "    wsl_place.items = lambda: ["
assert _STUB in base.LAUNCHER
base.LAUNCHER = base.LAUNCHER.replace(_STUB, (
    "    _real_items = wsl_place.items\n"
    "    wsl_place.items = lambda: _stub_items() + [i for i in _real_items() if i['key'] == 'cardcache']\n"
    "    _stub_items = lambda: ["), 1)


def main():
    scratch = tempfile.mkdtemp(prefix="pad1459-")
    disk = os.path.join(scratch, "pad-cardcache.vhdx")
    with open(disk, "wb") as f:
        f.truncate(9 * 2 ** 30)                     # what the disk costs with six Godzilla builds on it, roughly
    os.environ["PAD_CACHE_DISK"] = disk
    os.environ["PAD_CARDS_DISK"] = os.path.join(scratch, "no-store.vhdx")
    os.environ["PAD_DATA_DISK"] = os.path.join(scratch, "no-data.vhdx")
    base.main()


if __name__ == "__main__":
    main()
