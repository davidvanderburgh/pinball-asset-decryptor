"""musiccheck.py <job out dir> - musicjob.sh's verdict (PAD-1555; PAD-724's verdict.py, re-made): the first two fires
the slot's 500 Hz tone and the last two its MUSIC MODE 2 file's 1000 Hz (audio.raw, 44.1 kHz s16 stereo, as
turncheck.py), and the settings store (codeselect/nvm.c: 44-byte records, a SHA1-of-caption key, the value u32 at +36,
its check at +40) holding MUSIC MODE = 2 and EDITION = 2. Exit 0 when all hold."""
import hashlib
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
from pinball_decryptor.plugins.stern import menu_settings as MS  # noqa: E402

RATE, FRAME = 44100, 4


def tone(left, at):
    seg = left[at:at + int(1.6 * RATE)]
    n = np.arange(len(seg))
    mags = {hz: float(np.abs(np.dot(seg, np.exp(-2j * np.pi * hz * n / RATE)))) / max(len(seg), 1) for hz in (500, 1000)}
    best = max(mags, key=mags.get)
    return best if mags[best] > 0.005 else None


def stored(data, caption):
    key = hashlib.sha1(caption.encode("ascii")).digest()
    i = data.find(key)
    while i >= 0:
        if i + 44 <= len(data):
            v, check = struct.unpack_from("<II", data, i + 36)
            if (check & 0xFF) == 0xFF - (v & 0xFF):
                return v
        i = data.find(key, i + 1)
    return None


def main(d):
    raw = np.fromfile(os.path.join(d, "audio.raw"), dtype="<i2").astype(np.float32) / 32768.0
    marks = [int(x) // FRAME for x in open(os.path.join(d, "marks.txt")).read().split()]
    heard = [tone(raw[0::2], m) for m in marks]
    ok = heard == [500, 500, 1000, 1000]
    print("heard", heard)
    nvm = os.path.join(d, "NVM")
    if os.path.isfile(nvm):
        data = open(nvm, "rb").read()
        vals = {k: stored(data, MS.SETTINGS[k][1]) for k in (MS.MUSIC_MODE, MS.EDITION)}
        print("stored", vals)
        ok = ok and vals.get(MS.MUSIC_MODE) == 2 and vals.get(MS.EDITION) == 2
    else:
        print("stored: no NVM copied")
        ok = False
    print("pass" if ok else "fail")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
