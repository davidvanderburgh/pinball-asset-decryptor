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
* **And past the codec's LEAD-IN FRAME when it has to be.**  The first frame
  a Spike 2 sound decodes to is read from the word BELOW its body — i.e. out
  of whatever ``image.bin`` happens to pack in front of it (see
  ``plugins.stern.spike2.emulator.Spike2Emu._decode_with_entry``).  Repacking
  moves those neighbours, so on some builds EVERY sound comes out one frame
  different and byte-identical after it: measured on Jaws LE 1.01 vs 1.02,
  all 1,733 sounds differ in exactly their first 2 (mono) or 4 (stereo)
  bytes and in nothing else.  That is 23 microseconds of packing, not audio,
  and a diff that counts it reports "1,733 sounds changed" when none did.  A
  tester on a build like that: "PAD tells me that 3,968 audio files have
  changed, but it looks like only the numbering changed — hashes should take
  precedence over indexes."  They do; the hash just has to be of the sound.
* **And past a whole FRAME OF SHIFT when it has to be.**  A build can also
  resolve its codec onto the dispatch entry that emits that predecessor word
  as sample 0 instead of reading past it, which pushes the entire sound along
  one frame — so the two cards hold every sample of the same callout at
  offsets one frame apart, and no digest of the whole file can ever match.
  Measured on Venom LE 1.06 vs 1.07: 1,356 sounds, every one of them stereo.
  Blind to that, the report called 484 of them "changed", 889 "added" and
  876 "removed"; seeing it, the pair is 3,964 of 3,968 sounds moved, 17 added
  and 4 removed.  The tester who found it had matched one up by ear: "the
  screenshot shows 00m02s331 - idx0004.wav as added in 1.07, but this callout
  was in fact already present in 1.06 under the name 00m02s331 - idx3562.wav."
  :mod:`mod_transfer` has forgiven this since PAD-77 and carries mods across
  it; the diff simply never learned the same trick.
"""

import hashlib
import os

from .checksums import md5_file, read_baseline_any
from .mod_transfer import audio_slot_key, wav_frame

#: Where an extract puts its decoded sounds (flat, one WAV per slot).
AUDIO_DIR = "audio"

#: Enough of a decoded WAV to hold its header and first frame in one read.
_HEAD_READ = 4096


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


def sound_digest(path):
    """MD5 of one decoded WAV with the codec's LEAD-IN FRAME zeroed.

    The first frame of a decoded Spike 2 sound is not the sound: it is the
    word the codec reads from below the body, which is whatever ``image.bin``
    packs in front of it that build.  Blanking it — 2 bytes mono, 4 stereo,
    located by the file's own header rather than assumed at 44 — makes two
    builds' copies of one unchanged sound hash alike, and leaves every other
    sample in the comparison.

    Anything that isn't a PCM WAV we can walk (a truncated file, a format the
    header doesn't describe) is hashed whole: an identity that is merely
    stricter, never wrong.
    """
    h = hashlib.md5()
    with open(path, "rb") as f:
        head = f.read(_HEAD_READ)
        frame = wav_frame(head)
        if frame is not None:
            off, size = frame
            if off + size <= len(head):
                head = head[:off] + b"\x00" * size + head[off + size:]
        h.update(head)
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def shift_digests(path):
    """``(without the FIRST frame, without the LAST frame)`` — the pair of
    MD5s that recognises one sound decoded a frame apart on the two cards.

    A build can resolve its codec onto the dispatch entry that emits the
    layout predecessor's body word as sample 0, which pushes the whole sound
    along one frame and drops its last one (see
    ``plugins.stern.spike2.emulator.Spike2Emu._resolve_entry`` and
    :func:`mod_transfer._one_sample_apart`).  Sound *X* then decodes as
    ``[stray] + X[:-1]`` on one card and as ``X`` on the other, so NO digest
    of the whole thing can match: the two files share every sample but at
    different offsets.  They do agree exactly on ``X[:-1]``, which is this
    pair — the shifted card's samples past its first frame against the other
    card's samples short of its last.

    Whole-file read, one file at a time, like the byte-wise fallback in
    :mod:`mod_transfer` this mirrors.  Anything that isn't a walkable PCM WAV
    gets its plain MD5 in both slots: still an identity, just a stricter one.
    """
    with open(path, "rb") as f:
        data = f.read()
    frame = wav_frame(data[:_HEAD_READ])
    if frame is None or len(data) <= frame[0] + frame[1]:
        whole = hashlib.md5(data).hexdigest()
        return whole, whole
    off, size = frame
    return (hashlib.md5(data[off + size:]).hexdigest(),
            hashlib.md5(data[off:len(data) - size]).hexdigest())


def _sound_digests(folder, rest):
    """``{slot_key: digest}`` past the lead-in, for the slots still unpaired.

    Only these: on a build that left the packing alone the exact pass already
    matched everything and not one file is read here, and on a build that
    repacked, the read is the price of the right answer (1.6 GB of Jaws in a
    couple of seconds).  A file that can't be read keeps an identity nothing
    can equal, exactly as :func:`digests` does."""
    out = {}
    for key, (rel, _md5) in rest.items():
        try:
            out[key] = sound_digest(os.path.join(folder, rel))
        except OSError:
            out[key] = "?%s" % rel
    return out


def _shift_digests(folder, rest):
    """``({slot_key: no-first-frame}, {slot_key: no-last-frame})`` for the
    slots still unpaired — :func:`shift_digests` over what is left.

    Unreadable files keep an identity nothing can equal, and a DIFFERENT one
    per side, so a pair of unreadable slots never pairs with each other."""
    first, last = {}, {}
    for key, (rel, _md5) in rest.items():
        try:
            first[key], last[key] = shift_digests(os.path.join(folder, rel))
        except OSError:
            first[key], last[key] = "?first%s" % rel, "?last%s" % rel
    return first, last


def _pair_off(rest_a, rest_b, key_a, key_b):
    """Pair what's left on identity:
    ``(same count, [(slot_key, rel_a, rel_b)] moved)``.

    *key_a* / *key_b* map a slot key to the identity to match on, so the same
    pairing runs twice — once on the files' own MD5s, then on their lead-in
    blind digests — and the second pass only ever sees what the first could
    not place.  Matching entries are consumed out of *rest_a* / *rest_b*.

    Same slot first, then anywhere: a build that inserts one sound renumbers
    every sound after it, so the moved pass is what stops that from reading as
    thousands of changes."""
    same = 0
    for key in sorted(rest_a):
        if key in rest_b and key_a[key] == key_b[key]:
            same += 1
            del rest_a[key]
            del rest_b[key]

    pools = {}
    for key in rest_b:
        pools.setdefault(key_b[key], []).append(key)
    for keys in pools.values():
        keys.sort()

    moved = []
    for key in sorted(rest_a):
        pool = pools.get(key_a[key])
        if pool:
            other = pool.pop(0)
            moved.append((key, rest_a[key][0], rest_b[other][0]))
            del rest_b[other]
            del rest_a[key]
    return same, moved


def diff_audio(folder_a, folder_b):
    """What changed between two extracts' decoded sounds.

    Returns a dict:

    ``count_a`` / ``count_b``
        how many sounds each extract holds.
    ``same``
        slots present on both holding the same sound (a count — listing 2,000
        unchanged sounds helps nobody).
    ``changed``
        ``[(rel_a, rel_b)]`` — the same slot on both cards, different audio.
    ``moved``
        ``[(rel_a, rel_b)]`` — the same sound at a different slot.
    ``removed`` / ``added``
        ``[rel]`` — audio on only one of the two cards.
    ``lead_in``
        how many of the ``same`` + ``moved`` pairs only matched once the
        codec's lead-in frame was set aside (:func:`sound_digest`) — i.e. how
        much of the agreement this build's repack would otherwise have hidden.
    ``shifted``
        how many only matched once one side was read a frame later
        (:func:`shift_digests`) — the same sound, decoded through the codec
        entry that emits its predecessor's word first.

    Order matters: exact bytes first (free, off the baselines), then the same
    passes again past the lead-in for whatever is left, then again a frame
    apart, and only then same-slot-different-audio.  Every reordering of those
    is a way to report a repack as a rewrite — and running the shift pass
    AFTER "changed" would be worse than not running it at all, because
    "changed" consumes any slot that exists on both cards, and would eat the
    very pairs it is there to find.
    """
    a, b = digests(folder_a), digests(folder_b)
    rest_a, rest_b = dict(a), dict(b)
    md5_a = {k: v[1] for k, v in a.items()}
    md5_b = {k: v[1] for k, v in b.items()}
    same, moved = _pair_off(rest_a, rest_b, md5_a, md5_b)

    lead_in = 0
    if rest_a and rest_b:
        more_same, more_moved = _pair_off(
            rest_a, rest_b,
            _sound_digests(folder_a, rest_a), _sound_digests(folder_b, rest_b))
        lead_in = more_same + len(more_moved)
        same += more_same
        moved += more_moved

    shifted = 0
    if rest_a and rest_b:
        first_a, last_a = _shift_digests(folder_a, rest_a)
        first_b, last_b = _shift_digests(folder_b, rest_b)
        # Both directions, tried in turn: whichever card decoded a frame late
        # is a property of that build, not something the caller can order.
        for key_a, key_b in ((first_a, last_b), (last_a, first_b)):
            more_same, more_moved = _pair_off(rest_a, rest_b, key_a, key_b)
            shifted += more_same + len(more_moved)
            same += more_same
            moved += more_moved
            if not (rest_a and rest_b):
                break

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
        # Listed in the A card's slot order, whichever pass found the pair:
        # a report that runs idx0000, idx0001, … reads as the sound directory
        # it is, not as two lists stapled together.
        "moved": [(rel_a, rel_b) for _key, rel_a, rel_b in sorted(moved)],
        "removed": [rest_a[k][0] for k in sorted(rest_a)],
        "added": [rest_b[k][0] for k in sorted(rest_b)],
        "lead_in": lead_in,
        "shifted": shifted,
    }
