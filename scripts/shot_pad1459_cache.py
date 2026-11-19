r"""PAD-1459 proof shot: the Emulate tab's Card cache window over six builds of one title.

    python scripts/shot_pad1459_cache.py <app tree> <out.png> [--disk]

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). The rig's
`cardmount.sh --cache-list` is answered with the six Godzilla builds cached on the emulator machine for this ticket:
the stock LE and Pro and four Heisei custom builds, each card's size as `du` gave it. Without --disk the cache is
where a user's is today, inside Linux (kind `distro`, used = the cards added up: 36.3 GB); with --disk it is on its
own XFS disk (kind `disk`, used = the disk's real use measured there with the blocks shared: 16.0 GB). Nothing runs
in WSL.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad739_cache as base  # noqa: E402

# label, du KB, last boot, copied - measured on the emulator machine (PAD-1459, proof_custom.sh)
CARDS = [
    ("godzilla_le-1_16_0_spike2", 6287508, "11-12 18:02", "11-12 18:02"),
    ("godzilla_pro-1_16_0_spike2", 6287508, "11-14 20:31", "11-14 20:31"),
    ("Godzilla Premium 1.15 Heisei Custom V1.0", 4803552, "11-16 21:10", "11-16 21:10"),
    ("Godzilla Premium 1.16 Heisei Custom V1.5 Orchestral Edition", 4806996, "11-17 19:44", "11-17 19:44"),
    ("Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition", 4803728, "11-18 20:05", "11-18 20:05"),
    ("Godzilla Premium 1.16 Heisei Custom V1.6 Orchestral Edition.multi", 11027420, "11-19 13:34", "11-19 13:34"),
]
SIZE = {c[0]: 7861174272 for c in CARDS}
SIZE["Godzilla Premium 1.16 Heisei Custom V1.6 Orchestral Edition.multi"] = 14723055616
REAL_KB = 16766020          # df of the cache disk, less the empty filesystem, after the copier shared the blocks


def listing(disk):
    out = []
    for label, kb, boot, copied in CARDS:
        src = ("/mnt/d/Pinball/images/Stern/spike2/%s.Release.8G.sdcard.raw" % label if label[0].islower()
               else "/mnt/c/Users/u/Desktop/Heisei/%s.raw" % label)
        out.append("entry\t%s\t%d\t%d\t%d\t%s" % (label, kb, SIZE[label] // 1024, base._epoch(boot), src))
        out.append("state\t%s\tok\t-\t%d" % (label, base._epoch(copied)))
    used = sum(c[1] for c in CARDS)
    if disk:
        out.append("limit\t64\t%d\t/mnt/wsl/padcache/cardcache\tdisk" % REAL_KB)
        out.append("disk\t%d\t%d" % (100597760 - REAL_KB - 1959324, 100597760))
    else:
        out.append("limit\t64\t%d\t/home/pad/cardcache\tdistro" % used)
        out.append("disk\t%d\t%d" % (1007 * base.G - used - 60 * base.G, 1007 * base.G))
    return "\n".join(out) + "\n"


def main():
    disk = "--disk" in sys.argv[3:]
    base.listing = lambda: listing(disk)
    sys.argv = sys.argv[:3]
    base.main()


if __name__ == "__main__":
    main()
