#!/usr/bin/env python3
"""Append a record carrying a mode's OWN audio to a standalone image.bin (item 130).

A sound the game never shipped, without retiring a stock slot.

WHY THIS IS NOT A CARD BUILD. The rig boots the extracted title
(``$ROOT/games/<title>/``), so the sound bank is a plain file: a grown bank can be
staged beside it in ninety seconds instead of rebuilding eight gigabytes. Item 104's
own path (``engine.write_image``) does a whole card AND re-points a descriptor at the
appended record, which retires the stock sound - the very thing a mode's own audio is
meant to avoid.

WHAT MAKES AN APPENDED RECORD PLAYABLE. The boot-time band build registers every
record in the bank with the sound container under an 8-byte key, and that key moves
with the record's GEOMETRY - so an appended record, even one copied from a stock
sound, registers as its own entry under its own key. Nothing names it, which is why
item 104 had to re-point a descriptor to make a grown sound audible. A mode does not:
mode.so hooks the container lookup and points it at this key (see MODE_API.md).

Everything here runs through the SHIPPED masterdir/emulator/codec code.

  grow_mode_sound.py <repo> <game_elf> <stock_image> <out_image> <src_idx|-1> <seconds>

``src_idx`` -1 picks the source itself: the encoder used here is the MONO path, and
``warm_slots_for_grown`` seeds a grown sound's codec entry from a stock sound of the
same (scale, chan), so a short mono record satisfies both.

Prints the appended record's key, which is what a mode file's ``sound_key`` wants.
"""
import os
import shutil
import struct
import sys
import time
import wave

REPO, GAME, SRC_IMG, OUT_IMG = sys.argv[1:5]
SRC_IDX = int(sys.argv[5])
SECONDS = float(sys.argv[6])
sys.path.insert(0, REPO)

from pinball_decryptor.plugins.stern.spike2 import masterdir as MD       # noqa: E402
from pinball_decryptor.plugins.stern.spike2.emulator import (            # noqa: E402
    Spike2Emu, collapse_shadowed, emitted_length)

T0 = time.time()
RATE = 44100


def say(m):
    print("%7.1fs %s" % (time.time() - T0, m))
    sys.stdout.flush()


def distinctive_wav(path, seconds, rate=RATE):
    """A clip nobody could mistake for a stock callout: a rising three-tone figure,
    three tones a second, with a gap between tones so a rig capture can be judged by
    COUNTING ONSETS as well as by correlation. Item 104 used the same shape on its
    tilt card, for the same reason: you can check it by ear without a tool."""
    import math
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        t = i / float(rate)
        hz = (440.0, 660.0, 880.0)[int(t * 3) % 3]
        env = min(1.0, min(i, n - i) / (0.01 * rate))
        gate = 0.0 if (t * 3) % 1.0 > 0.75 else 1.0
        v = int(9000 * env * gate * math.sin(2 * math.pi * hz * t))
        frames += struct.pack("<h", max(-32768, min(32767, v)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


def main():
    global SRC_IDX
    say("booting on the stock bank %s" % SRC_IMG)
    emu = Spike2Emu(GAME, SRC_IMG)
    emu.boot()
    rows = emu.derive_params()
    say("derived %d rows" % len(rows))
    byidx = {r["idx"]: r for r in collapse_shadowed(rows)}
    if SRC_IDX < 0:
        cands = [r for r in rows if r.get("chan") == 1
                 and r.get("length", 0) > 20000 and r.get("findkey")]
        if not cands:
            raise SystemExit("no mono source record long enough to copy")
        src = min(cands, key=lambda r: r["length"])
        SRC_IDX = src["idx"]
        say("auto-picked source idx %d (mono, length %d) from %d candidates"
            % (SRC_IDX, src["length"], len(cands)))
    else:
        src = byidx[SRC_IDX]
    say("source idx %d: body_off 0x%x length %d scale %s chan %s"
        % (SRC_IDX, src["body_off"], src["length"], src["scale"], src["chan"]))

    old_length = src["length"]
    new_length = max(old_length + 1, int(SECONDS * RATE) + 200)
    body_bytes = 2 * new_length + 64
    say("appending a record: length %d -> %d (%.2f s), body %d bytes"
        % (old_length, new_length, emitted_length(new_length) / float(RATE),
           body_bytes))

    directory = MD.read_directory(SRC_IMG, emu)
    say("stock directory: %r" % (directory,))
    grown, places = MD.plan_grow_records(
        directory, [MD.GrowEdit(SRC_IDX, old_length, new_length, body_bytes)])
    place = places[0]
    writes = MD.write_directory(grown, emu)
    emu.close()

    say("copying -> %s" % OUT_IMG)
    shutil.copyfile(SRC_IMG, OUT_IMG)
    with open(SRC_IMG, "rb") as f:
        f.seek(src["body_off"])
        scaffold = f.read(min(2 * old_length, body_bytes))
    if not scaffold:
        raise SystemExit("could not read the source body for the scaffold")
    # REAL card audio, never zeros: the codec is driven over these bytes to recover
    # the keystream, and a degenerate body gives a degenerate one.
    scaffold = (scaffold * -(-body_bytes // len(scaffold)))[:body_bytes]
    with open(OUT_IMG, "r+b") as f:
        for off, data in sorted(writes.items()):
            f.seek(off)
            f.write(data)
        f.seek(place.body_off)
        f.write(scaffold)
        f.truncate(place.body_off + len(scaffold))
    say("wrote grown bank: %d bytes (was %d)"
        % (os.path.getsize(OUT_IMG), os.path.getsize(SRC_IMG)))

    say("booting on the GROWN bank")
    emu2 = Spike2Emu(GAME, OUT_IMG)
    emu2.boot()
    rows2 = emu2.derive_params()
    say("derived %d rows (stock had %d)" % (len(rows2), len(rows)))
    if len(rows2) != len(rows) + 1:
        emu2.close()
        raise SystemExit("the band build did NOT take the appended record")

    appended = rows2[place.new_idx]
    fk_new, fk_src = appended.get("findkey"), src.get("findkey")
    say("appended row %d: body_off 0x%x length %d findkey %s"
        % (place.new_idx, appended["body_off"] or 0, appended["length"],
           (fk_new or b"").hex()))
    if not fk_new:
        emu2.close()
        raise SystemExit("the appended record registered no container key")
    if fk_new == fk_src:
        emu2.close()
        raise SystemExit("appended key EQUALS the source key: it would shadow, not add")
    keys = [r["findkey"] for r in rows2 if r.get("findkey")]
    say("grown bank: %d rows, %d keyed, %d distinct" % (len(rows2), len(keys), len(set(keys))))
    moved = [r["idx"] for r in rows2[:len(rows)]
             if (r["body_off"], r["length"]) !=
                (rows[r["idx"]]["body_off"], rows[r["idx"]]["length"])]
    say("stock records that moved: %d %s" % (len(moved), moved[:5]))
    if moved:
        emu2.close()
        raise SystemExit("a stock record moved; refusing to call this bank good")

    wav = os.path.join(os.path.dirname(OUT_IMG), "mode_own_sound.wav")
    distinctive_wav(wav, SECONDS)
    say("wrote %s (%.2f s)" % (wav, SECONDS))

    params2 = collapse_shadowed(rows2)
    for p in params2:
        if p.get("shadows") is not None or p["idx"] == place.new_idx:
            p["grown"] = True
    emu2.warm_slots_for_grown(params2)   # or the re-encode will not round-trip

    import numpy as np                                                   # noqa: E402
    from pinball_decryptor.plugins.stern.spike2.codec import GenRecover  # noqa: E402
    with wave.open(wav, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.int64)
    n = emitted_length(appended["length"])
    tgt = np.zeros(n, np.int64)
    tgt[:min(n, len(pcm))] = pcm[:n]
    say("encoding %d samples into the appended record" % n)
    start, body = GenRecover(emu2).encode_sound(appended, tgt)
    with open(OUT_IMG, "r+b") as f:
        f.seek(start)
        f.write(body)

    out = emu2.decode(appended)
    emu2.close()
    if out is None:
        raise SystemExit("the appended record did not decode back")
    got = np.asarray(out[0], np.int64)[:n]
    err = float(np.abs(got - tgt[:len(got)]).max()) if len(got) else -1
    corr = (float(np.corrcoef(got, tgt[:len(got)])[0, 1])
            if len(got) > 16 and got.std() > 0 else float("nan"))
    say("round trip: %d samples, peak error %.0f, corr %.5f" % (len(got), err, corr))
    if err != 0:
        say("NOTE: the round trip is not bit-exact; the rig will hear the difference")
    print("\nsound_key      %s" % fk_new.hex())
    print("# appended idx %d, %.2f s, in %s" % (place.new_idx, SECONDS, OUT_IMG))


if __name__ == "__main__":
    main()
