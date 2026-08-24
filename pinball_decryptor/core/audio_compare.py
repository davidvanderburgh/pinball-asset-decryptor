"""Per-sound diff between two extract folders — the audio half of the
Compare report.

WHY THIS EXISTS.  The Compare tab reads the two CARDS, and a card's packed
audio is one opaque blob (``image.bin``) whose per-sound layout only exists
once the booted firmware has handed it out — i.e. after an Extract.  So the
report could only ever say whether that blob's stored digest moved, and it
always has: Stern repacks and re-keys ``image.bin`` on every build, so two
releases of one title carrying the SAME sounds share their container bytes
only by chance (measured: Led Zeppelin 1.21 vs 1.22, identical 549 sounds and
an identical container length, agree on 2.4% of the body).  A verdict read off
that digest is a guaranteed false alarm, and the advice it carried — "extract
both cards to compare them one by one" — went nowhere: a tester did exactly
that with the tab's own Extract Both button, hit Compare again, and got the
same sentence back.

This module is the comparison that sentence promised.

* **Costs two text reads, not two rescans.**  Every extract folder already
  holds a ``.checksums.md5`` baseline with an MD5 per decoded WAV, so a
  4,000-sound pair is compared without hashing a single gigabyte.  Only files
  the baseline is missing get hashed (same MD5 space, so the two sources mix
  safely).
* **Slots pair up by the ``idxNNNN`` token**, not by file name: every extract
  naming option (length prefix, Auto-transcribe / Music-ID rename, Sound Test
  names) preserves that token, so two folders extracted with different
  settings still line up.  That is :func:`mod_transfer.audio_slot_key`, the
  same identity the mod transfer uses.
* **Content is matched before slots.**  A build that inserts one sound
  renumbers every sound after it; pairing on the index alone would report
  "2,000 sounds changed" and bury the handful that really did.  So bytes
  found on both cards under DIFFERENT indices are reported as *moved*, and
  only a slot that exists on both sides with different bytes is *changed* —
  which is precisely the modded-card-against-its-stock-base case.
"""

import os

from .checksums import md5_file, read_baseline_any
from .mod_transfer import audio_slot_key

#: Where an extract puts its decoded sounds (flat, one WAV per slot).
AUDIO_DIR = "audio"


def _wav_names(folder):
    """The decoded-WAV file names in ``folder``/audio, sorted.

    Dot-files are skipped the way every other slot scanner skips them, so the
    baseline and the sidecars never read as sounds."""
    d = os.path.join(folder, AUDIO_DIR)
    if not os.path.isdir(d):
        return []
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(n for n in names
                  if not n.startswith(".") and n.lower().endswith(".wav"))


def digests(folder):
    """``{slot_key: (rel, md5)}`` for every decoded sound in *folder*.

    The extract's own baseline answers for almost every file; anything it
    doesn't list (a sound renamed after the baseline was written, a folder
    whose ``.checksums.md5`` is missing) is hashed here, so the result is
    never partly-populated.  A duplicate slot key deterministically keeps the
    first name — same rule as the mod transfer's scan."""
    baseline = read_baseline_any(folder)
    out = {}
    for name in _wav_names(folder):
        key = audio_slot_key(name)
        if key in out:
            continue
        rel = "%s/%s" % (AUDIO_DIR, name)
        md5 = baseline.get(rel)
        if not md5:
            try:
                md5 = md5_file(os.path.join(folder, AUDIO_DIR, name))
            except OSError:
                # Unreadable (locked, a OneDrive placeholder): give it an
                # identity nothing else can equal rather than dropping the
                # slot, so it lists as changed instead of vanishing.
                md5 = "?%s" % rel
        out[key] = (rel, md5)
    return out


def diff_audio(folder_a, folder_b):
    """What changed between two extracts' decoded sounds.

    Returns a dict:

    ``count_a`` / ``count_b``
        how many sounds each extract holds.
    ``same``
        slots present on both with identical bytes (a count — listing 2,000
        unchanged sounds helps nobody).
    ``changed``
        ``[(rel_a, rel_b)]`` — the same slot on both cards, different audio.
    ``moved``
        ``[(rel_a, rel_b)]`` — identical audio that sits at a different slot.
    ``removed`` / ``added``
        ``[rel]`` — audio on only one of the two cards.

    Order matters: identical-at-the-same-slot first, then identical-anywhere,
    then same-slot-different-bytes, then the leftovers.  Reversing the middle
    two would turn one inserted sound into thousands of "changed" rows.
    """
    a, b = digests(folder_a), digests(folder_b)
    same = 0
    rest_a, rest_b = {}, dict(b)
    for key, (rel, md5) in a.items():
        other = b.get(key)
        if other is not None and other[1] == md5:
            same += 1
            del rest_b[key]
        else:
            rest_a[key] = (rel, md5)

    by_md5 = {}
    for key, (rel, md5) in rest_b.items():
        by_md5.setdefault(md5, []).append(key)
    for keys in by_md5.values():
        keys.sort()

    moved = []
    for key in sorted(rest_a):
        rel, md5 = rest_a[key]
        pool = by_md5.get(md5)
        if pool:
            other = pool.pop(0)
            moved.append((rel, rest_b[other][0]))
            del rest_b[other]
            del rest_a[key]

    changed = []
    for key in sorted(rest_a):
        if key in rest_b:
            changed.append((rest_a[key][0], rest_b[key][0]))
            del rest_b[key]
            del rest_a[key]

    return {
        "count_a": len(a),
        "count_b": len(b),
        "same": same,
        "changed": changed,
        "moved": moved,
        "removed": [rest_a[k][0] for k in sorted(rest_a)],
        "added": [rest_b[k][0] for k in sorted(rest_b)],
    }
