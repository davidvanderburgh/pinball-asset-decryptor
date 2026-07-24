"""Spike 2 audio re-encode TAIL round-trip guard (heavy; gated on a bundled card).

The codec emits exactly ``length - BLOCK`` samples (see emulator.emitted_length).
Regression guarded here: decode() must return that many samples, and re-encoding
a target whose FINAL partial block is loud must round-trip bit-exact — i.e. the
last <200 samples are no longer dropped (which clicked at the loop point of
looping music).  Covers the validated build (turtles) AND a generic/located
build (led_zeppelin, the title the original bug was reported on).

These boot the firmware in unicorn (~1-2 min/title) and need a 7.8 GB card image
under images/Stern/spike2/, so they skip cleanly in CI where the cards aren't
present.  Extracted game_real/image.bin are cached in the temp dir between runs.
"""
import os
import struct
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO, "images", "Stern", "spike2")
CARDS = {
    "turtles": "turtles_pro-1_58_0.Release.8G.sdcard.raw",      # validated build
    "led_zeppelin": "led_zeppelin_le-1_20_0.Release.8G.sdcard.raw",  # generic build
    # LE 1.22.0: a build whose PLT thunks unicorn mistranslates -- exercises the
    # _plt_branch entry-intercept (without it, derive_params can't map the codec).
    "led_zeppelin_122": "led_zeppelin_le-1_22_0.Release.8G.sdcard.raw",
}


# --------------------------------------------------------------------------
# Fast unit tests (no card, no boot) — guard the emit-length contract + wiring.
# --------------------------------------------------------------------------

def test_emitted_length_formula():
    from pinball_decryptor.plugins.stern.spike2.emulator import (
        emitted_length, BLOCK)
    assert BLOCK == 200
    assert emitted_length(0) == 0
    assert emitted_length(200) == 0          # one block is the cursor lead-in
    assert emitted_length(150) == 0          # shorter than a block -> nothing
    assert emitted_length(250) == 50
    assert emitted_length(84878) == 84678    # TMNT idx0 (mono)
    assert emitted_length(74750) == 74550    # TMNT idx4 (stereo)


def test_encoders_fit_target_to_emitted_length(monkeypatch):
    """_encode_mono/_encode_stereo must size the re-encode target to the codec's
    TRUE emitted length (length-BLOCK), not the raw header length -- otherwise
    encode_sound drops the user's final ~200 samples (a click at the loop point
    of looping music)."""
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 5000
    want = emitted_length(length)
    assert want == length - 200

    # a source LONGER than the emitted length, so a wrong fit-to-`length` would
    # keep ~200 extra samples that encode_sound then silently drops.
    monkeypatch.setattr(E, "_load_wav", lambda path, stereo, np_: (
        np.ones((length + 500, 2), np.int64) * 1000 if stereo
        else np.ones(length + 500, np.int64) * 1000))

    captured = {}

    class FakeGR:
        def encode_sound(self, pp, tgt):
            captured["mono"] = len(tgt)
            return 0, b""

    class FakeSR:
        def encode_sound(self, pp, L, R):
            captured["L"] = len(L)
            captured["R"] = len(R)
            return 0, b""

    E._encode_mono(None, FakeGR(), {"length": length, "chan": 1}, "x.wav", np)
    E._encode_stereo(None, FakeSR(), {"length": length, "chan": 2}, "x.wav", np)
    assert captured["mono"] == want
    assert captured["L"] == captured["R"] == want


def test_encode_sound_preserves_stock_words_beyond_emitted_range():
    """encode_sound must seed the body from the ORIGINAL card bytes, not zeros.
    The encode only covers the emitted range (length - BLOCK); the lead-out
    block past it can't be re-encoded (keystream recovery captures nothing
    there), and shipping raw 0x0000 words in it made the real machine play a
    deterministic noise burst right after every replaced callout (monkeybug's
    LZ end-click, diagnosed from his cabinet recording — stock bodies are
    encoded to the last word and never click)."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import GenRecover
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)                       # 400
    stock = (np.arange(length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    gr = object.__new__(GenRecover)
    gr.emu = types.SimpleNamespace(mm=MM())
    gr._calibrate = lambda p: (0, 0, 0)                    # delta = 0
    gr.recover_block = lambda p, cursor, n=200: (
        np.zeros(n, np.int64), np.zeros(n, np.int64))
    gr.encode_block = lambda seg, K, rb: (
        np.full(len(seg), 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 1, "scale": 3}
    off, raw = gr.encode_sound(p, np.zeros(emitted, np.int64))
    body = np.frombuffer(raw, dtype="<u2")
    assert off == 0                                        # delta=0: unshifted
    assert len(body) == length
    assert (body[:emitted] == 0xBEEF).all()                # target covered
    assert (body[emitted:] == stock[emitted:]).all()       # tail = stock words
    assert body[emitted:].all()                            # no raw zero words


def test_encode_sound_stereo_preserves_stock_frames_beyond_emitted_range():
    """Stereo variant of the tail-click guard: uncovered interleaved frames
    keep the original card's words instead of raw zeros."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import StereoRecover
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)                       # 400
    stock = (np.arange(2 * length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    sr = object.__new__(StereoRecover)
    sr.emu = types.SimpleNamespace(mm=MM())
    sr._calibrate = lambda p: 0                            # delta = 0
    sr.recover_block = lambda p, cursor, nf=200: {"m": nf}
    sr.encode_block = lambda L, R, rec: (
        np.full(2 * rec["m"], 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 2, "scale": 3}
    z = np.zeros(emitted, np.int64)
    off, raw = sr.encode_sound(p, z, z)
    body = np.frombuffer(raw, dtype="<u2")
    assert off == 0                                        # delta=0: unshifted
    assert len(body) == 2 * length
    assert (body[:2 * emitted] == 0xBEEF).all()            # frames covered
    assert (body[2 * emitted:] == stock[2 * emitted:]).all()   # tail = stock
    assert body[2 * emitted:].all()                        # no raw zero words


def test_encode_sound_writes_first_word_on_shifted_builds():
    """delta=-1 keys: output sample 0 reads the word BELOW body_off, and the
    machine plays it at the trigger.  encode_sound must return a window
    shifted one word down with enc[0] written at its head — the old
    fixed-at-body_off window clipped enc[0] and left the stock word there,
    which real hardware rendered as a one-sample stock-amplitude tick right
    in front of the replacement's fade-in (monkeybug's start-of-callout
    click, lz_click2.mp4: the click followed the slot, never the content)."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import (
        GenRecover, StereoRecover)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)                       # 400
    body_off = 64

    # --- mono ---
    stock = (np.arange(body_off // 2 + length, dtype=np.uint32)
             % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    gr = object.__new__(GenRecover)
    gr.emu = types.SimpleNamespace(mm=MM())
    gr._calibrate = lambda p: (0, 0, -1)                   # delta = -1
    gr.recover_block = lambda p, cursor, n=200: (
        np.zeros(n, np.int64), np.zeros(n, np.int64))
    gr.encode_block = lambda seg, K, rb: (
        np.full(len(seg), 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": body_off, "chan": 1, "scale": 3}
    off, raw = gr.encode_sound(p, np.zeros(emitted, np.int64))
    body = np.frombuffer(raw, dtype="<u2")
    assert off == body_off - 2                 # window shifted one word down
    assert len(body) == length                 # still size-neutral
    assert (body[:emitted] == 0xBEEF).all()    # enc[0] AT THE HEAD, not clipped
    # lead-out = the stock words the hardware actually reads (shifted window)
    w0 = (body_off - 2) // 2
    assert (body[emitted:] == stock[w0 + emitted:w0 + length]).all()

    # --- stereo ---
    stock2 = (np.arange(body_off // 2 + 2 * length, dtype=np.uint32)
              % 60000 + 1).astype("<u2")
    stock2_bytes = stock2.tobytes()

    class MM2:
        def __getitem__(self, sl):
            return stock2_bytes[sl]

    sr = object.__new__(StereoRecover)
    sr.emu = types.SimpleNamespace(mm=MM2())
    sr._calibrate = lambda p: -1                           # delta = -1
    sr.recover_block = lambda p, cursor, nf=200: {"m": nf}
    sr.encode_block = lambda L, R, rec: (
        np.full(2 * rec["m"], 0xBEEF, np.uint16), 0)

    p2 = {"length": length, "body_off": body_off, "chan": 2, "scale": 3}
    z = np.zeros(emitted, np.int64)
    off2, raw2 = sr.encode_sound(p2, z, z)
    body2 = np.frombuffer(raw2, dtype="<u2")
    assert off2 == body_off - 4                # one frame down
    assert len(body2) == 2 * length
    assert (body2[:2 * emitted] == 0xBEEF).all()   # frame 0 written
    f0 = (body_off - 4) // 2
    assert (body2[2 * emitted:] == stock2[f0 + 2 * emitted:f0 + 2 * length]).all()


def test_fit_fades_audio_edges_to_zero():
    """_fit must land BOTH edges of the actual audio at zero via a short
    fade: audio that starts or ends non-zero (cut mid-waveform, DC offset)
    is a step the machine plays as a click at that edge of the callout
    (monkeybug, real-HW — end clicks first, start clicks confirmed after
    the tail-only fix).  Both the truncation point and the last real
    sample before zero-padding are audio ends."""
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _fit

    loud = np.full(5000, 10000, np.int64)
    fade_n = int(round(5.0 * 44.1))          # ~220 samples

    # Truncated: the cut lands mid-audio -> head from 0, tail to 0.
    out = _fit(loud, 4000, np)
    assert len(out) == 4000
    assert out[0] == 0 and out[-1] == 0
    assert out[fade_n] == 10000               # audio after the head fade intact
    assert out[3999 - fade_n] == 10000        # audio before the tail fade intact
    assert 0 < out[fade_n // 2] < 10000       # ramps, not mutes
    assert 0 < out[-fade_n // 2] < 10000

    # Shorter than the slot: tail fade sits at the END OF THE AUDIO, then zeros.
    out = _fit(loud[:3000], 4000, np)
    assert len(out) == 4000
    assert out[0] == 0                        # first real sample faded in
    assert out[2999] == 0                     # last real sample faded out
    assert not out[3000:].any()               # padding stays silent
    assert out[1000] == 10000

    # Exact-length audio still gets both edges faded.
    out = _fit(loud[:4000], 4000, np)
    assert out[0] == 0 and out[-1] == 0 and out[2000] == 10000

    # Clip shorter than two full fades: fades shrink so they can't overlap.
    out = _fit(loud[:300], 400, np)
    assert out[0] == 0 and out[299] == 0 and out[150] == 10000

    # Degenerate inputs don't blow up.
    assert len(_fit(np.zeros(0, np.int64), 100, np)) == 100
    assert list(_fit(np.array([5], np.int64), 1, np)) == [5]


def test_declick_params_toggle(monkeypatch):
    """The GUI 'Auto-fade + cap audio replacements' box maps to one env var:
    default (unset) = a stock-length fade + lower ceiling; unticked
    (PAD_STERN_AUDIO_RAW=1) = the legacy 5 ms fade + 0.97 ceiling."""
    from pinball_decryptor.plugins.stern.engine import _declick_params
    monkeypatch.delenv("PAD_STERN_AUDIO_RAW", raising=False)
    assert _declick_params() == (40.0, 0.80)
    monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
    assert _declick_params() == (5.0, 0.97)


def test_declick_lowpass_toggle(monkeypatch):
    """The band-limit rides the same toggle as the fade/cap: on by default,
    off (None) in RAW mode."""
    from pinball_decryptor.plugins.stern.engine import (
        _declick_lowpass_hz, _DECLICK_LOWPASS_HZ)
    monkeypatch.delenv("PAD_STERN_AUDIO_RAW", raising=False)
    assert _declick_lowpass_hz() == _DECLICK_LOWPASS_HZ
    monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
    assert _declick_lowpass_hz() is None


def test_lowpass_removes_hf_and_raw_is_noop():
    """_lowpass strips energy above its cutoff (the RE-implicated click driver:
    stock callouts are ~5 kHz-limited speech, music replacements carry 10x the
    HF), while a None cutoff (RAW mode) passes samples through untouched."""
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _lowpass

    sr = 44100
    t = np.arange(sr // 2) / sr
    low = np.sin(2 * np.pi * 500 * t)          # 500 Hz (kept)
    high = np.sin(2 * np.pi * 11000 * t)       # 11 kHz (removed by a 5 kHz LP)
    sig = ((low + high) * 8000).astype(np.int64)

    def hf_frac(a):
        a = np.asarray(a, np.float64)
        spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
        f = np.fft.rfftfreq(len(a), 1.0 / sr)
        return spec[f >= 8000].sum() / (spec.sum() + 1e-9)

    filt = _lowpass(sig, 5000.0, np)
    assert hf_frac(sig) > 0.3          # the raw mix is HF-heavy
    assert hf_frac(filt) < 0.01        # the 11 kHz tone is gone
    # The 500 Hz tone survives (RMS is still substantial).
    assert np.sqrt(np.mean(filt.astype(np.float64) ** 2)) > 3000
    # None cutoff (RAW) is a bit-exact passthrough.
    assert np.array_equal(_lowpass(sig, None, np), sig)


def test_encoder_band_limits_unless_raw(monkeypatch):
    """_encode_mono band-limits the replacement to stock bandwidth when declick
    is on, and leaves the HF intact in RAW mode -- the encoder actually consumes
    the new lowpass lever."""
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E

    sr = 44100
    length = sr // 4
    t = np.arange(length) / sr
    hf = ((np.sin(2 * np.pi * 400 * t) + np.sin(2 * np.pi * 12000 * t))
          * 4000).astype(np.int64)
    monkeypatch.setattr(E, "_load_wav", lambda p, stereo, np_: hf.copy())

    class Cap:
        def encode_sound(self, pp, tgt):
            self.tgt = np.asarray(tgt, np.float64)
            return 0, b""

    def hf_frac(a):
        spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
        f = np.fft.rfftfreq(len(a), 1.0 / sr)
        return spec[f >= 8000].sum() / (spec.sum() + 1e-9)

    monkeypatch.delenv("PAD_STERN_AUDIO_RAW", raising=False)
    c_on = Cap()
    E._encode_mono(None, c_on, {"length": length, "chan": 1}, "x.wav", np)

    monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
    c_raw = Cap()
    E._encode_mono(None, c_raw, {"length": length, "chan": 1}, "x.wav", np)

    assert hf_frac(c_on.tgt) < 0.02         # band-limited to stock profile
    assert hf_frac(c_raw.tgt) > 0.2         # RAW keeps the 12 kHz tone


def test_encoders_apply_declick_fade(monkeypatch):
    """_encode_mono actually consumes _declick_params (the toggle's only effect):
    declick-on lays a ~40 ms edge fade and caps to a lower peak; the raw mode
    restores the ~5 ms fade + hotter 0.97 normalization."""
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E

    length = 8000
    monkeypatch.setattr(
        E, "_load_wav",
        lambda path, stereo, np_: np.ones(length, np.int64) * 1000)

    class Cap:
        def encode_sound(self, pp, tgt):
            self.tgt = np.asarray(tgt)
            return 0, b""

    def run(raw):
        if raw:
            monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
        else:
            monkeypatch.delenv("PAD_STERN_AUDIO_RAW", raising=False)
        c = Cap()
        E._encode_mono(None, c, {"length": length, "chan": 1}, "x.wav", np)
        peak = int(np.abs(c.tgt).max())
        assert peak > 0
        # First sample that reaches full level = the length of the head fade-in.
        return int(np.argmax(np.abs(c.tgt) >= peak)), peak

    lead_on, peak_on = run(raw=False)
    lead_raw, peak_raw = run(raw=True)
    # ~40 ms (1764 samples) vs ~5 ms (220): the ramp reaches full level far later
    # when declick is on.
    assert lead_on > 1500
    assert lead_raw < 400
    # ...and declick caps to a lower ceiling (0.80) than the legacy hot 0.97.
    assert peak_on < peak_raw


def test_save_firmware_for_support(tmp_path):
    """When a firmware build can't be codec-mapped, extract copies it next to
    the output so the user can send it in for a locator fix; a bad destination
    degrades to None (logged) and never raises."""
    from pinball_decryptor.plugins.stern import engine as E
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF" + b"stern-firmware-bytes" * 8)
    out = tmp_path / "out"
    out.mkdir()
    logs = []
    dst = E._save_firmware_for_support(str(gr), str(out), lambda *a: logs.append(a))
    assert dst == str(out / "firmware_game_real.bin")
    assert (out / "firmware_game_real.bin").read_bytes() == gr.read_bytes()
    # Un-writable destination (parent dir doesn't exist) -> None, no exception.
    dst2 = E._save_firmware_for_support(
        str(gr), str(tmp_path / "nope" / "deep"), lambda *a: logs.append(a))
    assert dst2 is None


def test_rotimm_arm_modified_immediate():
    """_rotimm decodes the ARM data-processing modified immediate the PLT-thunk
    scanner folds into a GOT address (see Spike2Emu._plt_entry / _plt_branch)."""
    from pinball_decryptor.plugins.stern.spike2.emulator import _rotimm
    assert _rotimm(0x605) == 0x500000   # add ip, pc, #0x500000
    assert _rotimm(0xa50) == 0x50000    # add ip, ip, #0x50000
    assert _rotimm(0xa42) == 0x42000    # add ip, ip, #0x42000
    assert _rotimm(0x0ff) == 0xff       # rotate 0 -> the raw byte
    assert _rotimm(0x000) == 0


def test_rbtree_increment_walks_in_order_and_terminates():
    """RB.increment must yield the in-order successor and return the header at
    the end so a begin()!=end() walk terminates.  The harness previously stubbed
    the imported ``std::_Rb_tree_increment`` to return 0, so any build that
    iterated a non-empty registry map (Led Zeppelin LE 1.22.0's master-directory
    decode) looped off node 0 forever."""
    import struct
    from pinball_decryptor.plugins.stern.spike2 import rbtree as RB

    class Mem:
        def __init__(self):
            self.b = bytearray(0x200)

        def mem_read(self, a, n):
            return bytes(self.b[a:a + n])

        def mem_write(self, a, d):
            self.b[a:a + len(d)] = d

    mu = Mem()

    def wr(a, *vals):                      # node layout: color,parent,left,right,key
        for i, v in enumerate(vals):
            mu.mem_write(a + 4 * i, struct.pack("<I", v & 0xffffffff))

    HDR, n20, n10, n30 = 0x10, 0x40, 0x60, 0x80
    wr(HDR, 0, n20, n10, n30)              # header: parent=root, left/right = ends
    wr(n20, RB.BLACK, HDR, n10, n30, 20)
    wr(n10, RB.RED, n20, 0, 0, 10)
    wr(n30, RB.RED, n20, 0, 0, 30)

    order, node, steps = [], n10, 0
    while node != HDR and steps < 10:
        order.append(struct.unpack("<I", mu.mem_read(node + 0x10, 4))[0])
        node = RB.increment(mu, node)
        steps += 1
    assert order == [10, 20, 30]
    assert node == HDR                     # walk stopped at the header sentinel
    assert RB.decrement(mu, n30) == n20
    assert RB.decrement(mu, n20) == n10


def _card_path(title):
    return os.path.join(IMG_DIR, CARDS[title])


def _have(title):
    return os.path.exists(_card_path(title))


def _extract_inputs_cached(title):
    """Extract (and cache in the temp dir) the card's game_real + image.bin."""
    from pinball_decryptor.plugins.stern import engine as E
    work = os.path.join(tempfile.gettempdir(), "pad_stern_tail_" + title)
    gr = os.path.join(work, "game_real")
    img = os.path.join(work, "image.bin")
    if os.path.exists(gr) and os.path.exists(img) and os.path.getsize(img) > 0:
        return gr, img
    os.makedirs(work, exist_ok=True)
    parts = E._linux_partitions(_card_path(title))
    disk_f = open(_card_path(title), "rb")
    try:
        E._extract_inputs(disk_f, parts, work, lambda *a, **k: None)
    finally:
        disk_f.close()
    return gr, img


def _shortest(rows, chan, minlen=600):
    cand = [r for r in rows if r["chan"] == chan and r["length"] > minlen]
    return min(cand, key=lambda r: r["length"]) if cand else None


@pytest.mark.slow
@pytest.mark.parametrize("title", list(CARDS))
def test_decode_length_and_tail_roundtrip(title):
    if not _have(title):
        pytest.skip("card image %s not present" % CARDS[title])
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.emulator import (
        Spike2Emu, emitted_length)
    from pinball_decryptor.plugins.stern.spike2.codec import (
        GenRecover, StereoRecover)
    from pinball_decryptor.plugins.stern.engine import _BodyOverlay

    gr_path, img_path = _extract_inputs_cached(title)
    emu = Spike2Emu(gr_path, img_path)
    if not emu.audio_supported:
        emu.close()
        pytest.skip("audio decode not supported for %s" % title)
    emu.boot()
    rows = emu.derive_params()
    gr = GenRecover(emu)
    sr = StereoRecover(emu)

    checked = 0
    for chan in (1, 2):
        p = _shortest(rows, chan)
        if p is None:
            continue
        length = p["length"]
        emit = emitted_length(length)
        tail = (length % 200) or 200          # size of the final partial block

        out = emu.decode(p)
        assert out is not None, "%s idx%d decode failed" % (title, p["idx"])
        L = np.asarray(out[0], np.int64)
        R = np.asarray(out[1], np.int64)
        # (1) decode returns exactly the emitted length (no trailing padding).
        assert len(L) == emit, (
            "%s idx%d: decode len %d != emitted_length %d"
            % (title, p["idx"], len(L), emit))

        # (2) force a LOUD, varied final partial block and re-encode it; the
        # round-trip must reproduce it bit-exact (old bug: the tail was dropped
        # to zeros).  Re-encode via the codec directly so the target is exact.
        ramp = (np.arange(tail) * 173 % 6000 + 1500).astype(np.int64)
        tgtL = L.copy(); tgtL[-tail:] = ramp
        if chan == 2:
            tgtR = R.copy(); tgtR[-tail:] = -ramp
            off, body = sr.encode_sound(p, tgtL, tgtR)
        else:
            tgtR = None
            off, body = gr.encode_sound(p, tgtL)

        # patch the one body in-memory (the patched sound's own params don't
        # shift -- the masterdir chain is forward-only -- so decoding it with the
        # same params is faithful, exactly as _recovery_valid relies on).
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        emu.mm.patch = (off, bytes(body))
        try:
            out2 = emu.decode(p)
        finally:
            emu.mm.patch = None
        assert out2 is not None
        L2 = np.asarray(out2[0], np.int64)
        R2 = np.asarray(out2[1], np.int64)
        m = min(len(L2), emit)
        assert int(np.count_nonzero(L2[:m] != tgtL[:m])) == 0, (
            "%s idx%d: mono round-trip not bit-exact" % (title, p["idx"]))
        # the final partial block specifically must be present + correct
        assert int(np.count_nonzero(L2[emit - tail:emit] != tgtL[emit - tail:emit])) == 0
        assert int(np.count_nonzero(L2[emit - tail:emit])) >= tail - 2, (
            "%s idx%d: final block decoded to (near) silence -- tail dropped"
            % (title, p["idx"]))
        if chan == 2:
            mr = min(len(R2), emit)
            assert int(np.count_nonzero(R2[:mr] != tgtR[:mr])) == 0, (
                "%s idx%d: stereo R round-trip not bit-exact" % (title, p["idx"]))
        checked += 1

    emu.close()
    assert checked >= 1, "%s: no codec-0 sound found to test" % title


# --------------------------------------------------------------------------
# Full-length verification of the body we're about to write.
#
# _recovery_valid is only a pre-flight: it re-encodes the sound's OWN audio
# over the first 4 blocks (800 frames -- 4.3% of a 425 ms sound), so a
# keystream recovery that holds at the head and degrades later would ship
# unnoticed and decode to noise on the machine.  _verify_encoded checks the
# ACTUAL bytes over the WHOLE emitted range for one extra decode.
# --------------------------------------------------------------------------
def _verify_fixture(decoded, length=4000, chan=1, body_off=64, delta=0):
    """(emu, p, start) whose decode() returns ``decoded`` (an L array, or an
    (L, R) pair for stereo)."""
    import types
    import numpy as np

    stereo = chan == 2
    step = 4 if stereo else 2
    stock = bytes(len(   # plenty of backing bytes for the overlay to read
        decoded[0] if stereo else decoded) * step + body_off + 4096)

    class MM:
        def __getitem__(self, sl):
            return stock[sl]

        def size(self):
            return len(stock)

    def decode(p, max_secs=None, cancel=None, progress=None):
        if stereo:
            return (np.asarray(decoded[0]), np.asarray(decoded[1]), True)
        return (np.asarray(decoded), None, False)

    emu = types.SimpleNamespace(mm=MM(), decode=decode)
    p = {"length": length, "body_off": body_off, "chan": chan, "scale": 3,
         "idx": 4448}
    return emu, p, body_off + step * delta


def test_verify_encoded_accepts_exact_match():
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _verify_encoded
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    tgt = (np.arange(n) % 900 - 450).astype(np.int64)
    emu, p, start = _verify_fixture(tgt)
    _verify_encoded(emu, p, start, b"\0" * 8, tgt, None, np)   # must not raise


def test_verify_encoded_catches_late_block_divergence():
    """The exact gap _recovery_valid leaves: head fine, tail wrong."""
    import numpy as np
    import pytest
    from pinball_decryptor.plugins.stern.engine import (_verify_encoded,
                                                        _EncodeVerifyError)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    tgt = (np.arange(n) % 900 - 450).astype(np.int64)
    got = tgt.copy()
    bad_at = 3000                       # way past the 4-block (800) pre-flight
    assert bad_at > 800
    got[bad_at] += 5000
    emu, p, start = _verify_fixture(got)
    with pytest.raises(_EncodeVerifyError) as e:
        _verify_encoded(emu, p, start, b"\0" * 8, tgt, None, np)
    assert "5000" in str(e.value) and str(bad_at) in str(e.value)


def test_verify_encoded_exempts_shared_head_only_on_shifted_builds():
    """delta<0: the head word is shared with the layout predecessor and is a
    deliberate compromise, so the first block is exempt.  delta=0 (e.g. the
    Elvira HoH spinner idx4448) has no shared word -- nothing is exempt."""
    import numpy as np
    import pytest
    from pinball_decryptor.plugins.stern.engine import (_verify_encoded,
                                                        _EncodeVerifyError)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    tgt = np.zeros(n, np.int64)
    got = tgt.copy()
    got[0] = 8255                       # a frame-0 impulse like the real ones

    emu, p, start = _verify_fixture(got, delta=-1)
    _verify_encoded(emu, p, start, b"\0" * 8, tgt, None, np)   # exempt

    emu0, p0, start0 = _verify_fixture(got, delta=0)
    with pytest.raises(_EncodeVerifyError):
        _verify_encoded(emu0, p0, start0, b"\0" * 8, tgt, None, np)


def test_verify_encoded_checks_both_stereo_channels():
    import numpy as np
    import pytest
    from pinball_decryptor.plugins.stern.engine import (_verify_encoded,
                                                        _EncodeVerifyError)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    L = (np.arange(n) % 700 - 350).astype(np.int64)
    R = (np.arange(n) % 500 - 250).astype(np.int64)
    badR = R.copy()
    badR[2500] -= 4242
    emu, p, start = _verify_fixture((L, badR), chan=2)
    with pytest.raises(_EncodeVerifyError) as e:
        _verify_encoded(emu, p, start, b"\0" * 8, L, R, np)
    assert "R channel" in str(e.value)


# --------------------------------------------------------------------------
# Lead-out encoding.
#
# encode_sound only covers the emitted range; v0.57.2 seeded the rest from the
# stock card bytes because raw zeros there decoded as a noise burst.  But that
# means a replacement ends with up to 4.5 ms of the sound it REPLACED (up to
# -10 dBFS on real slots).  Recovery works there once the header length is
# extended, so the lead-out is now encoded to silence -- except the last
# LEADOUT_MARGIN frames, which may be the NEXT sound's head word.
# --------------------------------------------------------------------------
def _rawobj_for(length):
    """A raw sound object whose u32 length field at +0x10 extend_length patches."""
    import struct
    b = bytearray(0x20)
    struct.pack_into("<I", b, 0x10, length)
    return bytes(b)


def test_extend_length_patches_header_and_needs_a_rawobj():
    from pinball_decryptor.plugins.stern.spike2.codec import extend_length
    import struct

    p = {"length": 600, "_rawobj": _rawobj_for(600)}
    q = extend_length(p, 200)
    assert q["length"] == 800
    assert struct.unpack_from("<I", q["_rawobj"], 0x10)[0] == 800
    assert p["length"] == 600 and struct.unpack_from(
        "<I", p["_rawobj"], 0x10)[0] == 600          # original untouched
    assert extend_length({"length": 600}, 200) is None   # no raw object -> None


def test_encode_sound_silences_leadout_but_keeps_the_end_margin():
    """The lead-out is encoded (not left as the replaced sound's tail), and the
    final LEADOUT_MARGIN frames stay stock so a delta<0 successor's head word
    is never clobbered."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import (GenRecover,
                                                              LEADOUT_MARGIN)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)                       # 400
    stock = (np.arange(length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    gr = object.__new__(GenRecover)
    gr.emu = types.SimpleNamespace(mm=MM())
    gr._calibrate = lambda p: (0, 0, 0)                     # delta = 0
    gr.recover_block = lambda p, cursor, n=200: (
        np.zeros(n, np.int64), np.zeros(n, np.int64))
    gr.encode_block = lambda seg, K, rb: (
        np.full(len(seg), 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 1, "scale": 3,
         "_rawobj": _rawobj_for(length)}
    off, raw = gr.encode_sound(p, np.zeros(emitted, np.int64))
    body = np.frombuffer(raw, dtype="<u2")

    keep = LEADOUT_MARGIN
    assert (body[:emitted] == 0xBEEF).all()                # body covered
    assert (body[emitted:length - keep] == 0xBEEF).all()   # lead-out ENCODED
    assert (body[length - keep:] == stock[length - keep:]).all()   # margin stock


def test_encode_sound_stereo_silences_leadout_but_keeps_the_end_margin():
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import (StereoRecover,
                                                              LEADOUT_MARGIN)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)
    stock = (np.arange(2 * length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    sr = object.__new__(StereoRecover)
    sr.emu = types.SimpleNamespace(mm=MM())
    sr._calibrate = lambda p: 0
    sr.recover_block = lambda p, cursor, nf=200: {"m": nf}
    sr.encode_block = lambda L, R, rec: (
        np.full(2 * rec["m"], 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 2, "scale": 3,
         "_rawobj": _rawobj_for(length)}
    z = np.zeros(emitted, np.int64)
    off, raw = sr.encode_sound(p, z, z)
    body = np.frombuffer(raw, dtype="<u2")

    keep = LEADOUT_MARGIN
    assert (body[:2 * emitted] == 0xBEEF).all()
    assert (body[2 * emitted:2 * (length - keep)] == 0xBEEF).all()
    assert (body[2 * (length - keep):] == stock[2 * (length - keep):]).all()


def test_leadout_encoding_falls_back_to_stock_when_recovery_fails():
    """Any failure past the emitted range must leave the stock bytes -- never
    regress to the raw-zero noise burst v0.57.2 fixed."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import GenRecover
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    length = 600
    emitted = emitted_length(length)
    stock = (np.arange(length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    calls = {"n": 0}

    def flaky(p, cursor, n=200):
        calls["n"] += 1
        if cursor > emitted:                    # the lead-out block
            raise RuntimeError("no keystream here")
        return np.zeros(n, np.int64), np.zeros(n, np.int64)

    gr = object.__new__(GenRecover)
    gr.emu = types.SimpleNamespace(mm=MM())
    gr._calibrate = lambda p: (0, 0, 0)
    gr.recover_block = flaky
    gr.encode_block = lambda seg, K, rb: (
        np.full(len(seg), 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 1, "scale": 3,
         "_rawobj": _rawobj_for(length)}
    off, raw = gr.encode_sound(p, np.zeros(emitted, np.int64))
    body = np.frombuffer(raw, dtype="<u2")
    assert (body[:emitted] == 0xBEEF).all()
    assert (body[emitted:] == stock[emitted:]).all()   # stock, not zeros
    assert body[emitted:].all()


# --------------------------------------------------------------------------
# Advanced audio options (2026-07 trigger-pop hunt): env-driven experiment
# levers — fade/cap/roll-off overrides, tail-block mode, stock-head mode,
# machine-render previews.
# --------------------------------------------------------------------------
def test_declick_env_overrides(monkeypatch):
    from pinball_decryptor.plugins.stern.engine import (_declick_params,
                                                        _declick_lowpass_hz)

    for var in ("PAD_STERN_AUDIO_RAW", "PAD_STERN_FADE_MS",
                "PAD_STERN_HEADROOM", "PAD_STERN_LOWPASS_HZ"):
        monkeypatch.delenv(var, raising=False)
    assert _declick_params() == (40.0, 0.80)
    assert _declick_lowpass_hz() == 5000.0

    monkeypatch.setenv("PAD_STERN_FADE_MS", "12.5")
    monkeypatch.setenv("PAD_STERN_HEADROOM", "0.6")
    monkeypatch.setenv("PAD_STERN_LOWPASS_HZ", "3000")
    assert _declick_params() == (12.5, 0.6)
    assert _declick_lowpass_hz() == 3000.0

    monkeypatch.setenv("PAD_STERN_LOWPASS_HZ", "0")     # 0 = filter off
    assert _declick_lowpass_hz() is None

    # Overrides apply on top of RAW mode too.
    monkeypatch.setenv("PAD_STERN_AUDIO_RAW", "1")
    assert _declick_params() == (12.5, 0.6)

    # Garbage / out-of-range values fall back to the mode base.
    monkeypatch.setenv("PAD_STERN_FADE_MS", "banana")
    monkeypatch.setenv("PAD_STERN_HEADROOM", "7.5")
    assert _declick_params() == (5.0, 0.97)


def test_leadout_env_keeps_stock(monkeypatch):
    """PAD_STERN_LEADOUT=stock deliberately restores the v0.57.2..v0.71.0
    stock-scrap tail (an A/B lever, not a regression)."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern.spike2.codec import GenRecover
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    monkeypatch.setenv("PAD_STERN_LEADOUT", "stock")
    length = 600
    emitted = emitted_length(length)
    stock = (np.arange(length, dtype=np.uint32) % 60000 + 1).astype("<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    gr = object.__new__(GenRecover)
    gr.emu = types.SimpleNamespace(mm=MM())
    gr._calibrate = lambda p: (0, 0, 0)
    gr.recover_block = lambda p, cursor, n=200: (
        np.zeros(n, np.int64), np.zeros(n, np.int64))
    gr.encode_block = lambda seg, K, rb: (
        np.full(len(seg), 0xBEEF, np.uint16), 0)

    p = {"length": length, "body_off": 0, "chan": 1, "scale": 3,
         "_rawobj": _rawobj_for(length)}
    _off, raw = gr.encode_sound(p, np.zeros(emitted, np.int64))
    body = np.frombuffer(raw, dtype="<u2")
    assert (body[:emitted] == 0xBEEF).all()
    assert (body[emitted:] == stock[emitted:]).all()   # WHOLE lead-out stock


def _stock_head_fixture(np, stock_word=0, body_off=64, length=600):
    """(emu, p, rec, body) for _apply_stock_head: keystream identity
    (r=0, x=0) so a stock word w decodes to (qmul * sxth(w)) >> 16."""
    import types
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK

    stock = np.full(body_off // 2 + length, stock_word, dtype="<u2")
    stock_bytes = stock.tobytes()

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

    emu = types.SimpleNamespace(mm=MM())
    rec = types.SimpleNamespace(
        recover_block=lambda p, cursor, n=200: (
            np.zeros(n, np.int64), np.zeros(n, np.int64)),
        qmul=0x10000)                        # decode == sxth(word)
    p = {"idx": 231, "length": length, "body_off": body_off, "chan": 1}
    body = np.full(length, 0xBEEF, dtype="<u2").tobytes()
    return emu, p, rec, body


def test_stock_head_applied_when_all_gates_pass(monkeypatch):
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _apply_stock_head
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK

    monkeypatch.setenv("PAD_STERN_HEAD_MODE", "stock")
    emu, p, rec, body = _stock_head_fixture(np, stock_word=0)
    tgt = np.zeros(400, np.int64)
    out, applied = _apply_stock_head(emu, p, p["body_off"], body, tgt, rec, np)
    assert applied
    got = np.frombuffer(out, dtype="<u2")
    assert (got[:BLOCK] == 0).all()                   # stock words in place
    assert (got[BLOCK:] == 0xBEEF).all()              # rest untouched


def test_stock_head_gates(monkeypatch):
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _apply_stock_head

    monkeypatch.setenv("PAD_STERN_HEAD_MODE", "stock")
    emu, p, rec, body = _stock_head_fixture(np, stock_word=0)

    # Gate: replacement head must be silent.
    hot = np.zeros(400, np.int64)
    hot[3] = 5000
    out, applied = _apply_stock_head(emu, p, p["body_off"], body, hot, rec, np)
    assert not applied and out == body

    # Gate: stock head must decode silent (0x4000 -> sxth 0x4000 -> loud).
    emu2, p2, rec2, body2 = _stock_head_fixture(np, stock_word=0x4000)
    tgt = np.zeros(400, np.int64)
    out, applied = _apply_stock_head(emu2, p2, p2["body_off"], body2, tgt,
                                     rec2, np)
    assert not applied and out == body2

    # Gate: shifted delta<0 window (head word shared with the predecessor).
    out, applied = _apply_stock_head(emu, p, p["body_off"] - 2, body, tgt,
                                     rec, np)
    assert not applied and out == body

    # Gate: stereo slots are skipped (mono-only for now).
    p_st = dict(p, chan=2)
    out, applied = _apply_stock_head(emu, p_st, p["body_off"], body, tgt,
                                     rec, np)
    assert not applied and out == body

    # Off by default: no env var, no change even when every gate would pass.
    monkeypatch.delenv("PAD_STERN_HEAD_MODE", raising=False)
    out, applied = _apply_stock_head(emu, p, p["body_off"], body, tgt, rec, np)
    assert not applied and out == body


def test_verify_encoded_exempts_head_for_stock_head_mode():
    """exempt_head=True (block 0 deliberately restored to stock words) skips
    the head block exactly like delta<0 does; without it the same decode
    fails."""
    import numpy as np
    import pytest
    from pinball_decryptor.plugins.stern.engine import (_verify_encoded,
                                                        _EncodeVerifyError)
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    tgt = np.zeros(n, np.int64)
    got = tgt.copy()
    got[5] = 7                       # the stock head's own tiny residue
    emu, p, start = _verify_fixture(got, delta=0)
    _verify_encoded(emu, p, start, b"\0" * 8, tgt, None, np, exempt_head=True)
    with pytest.raises(_EncodeVerifyError):
        _verify_encoded(emu, p, start, b"\0" * 8, tgt, None, np)


def test_write_machine_render(monkeypatch, tmp_path):
    import wave
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _write_machine_render

    out = tmp_path / "previews"
    monkeypatch.setenv("PAD_STERN_PREVIEW_DIR", str(out))
    _write_machine_render({"idx": 7}, [np.array([0, 100, -100, 40000])],
                          False, np)
    path = out / "idx0007_machine_render.wav"
    assert path.is_file()
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 44100
        pcm = np.frombuffer(w.readframes(4), np.int16)
    assert list(pcm) == [0, 100, -100, 32767]          # clipped, not wrapped

    # No env var -> no file, never an error.
    monkeypatch.delenv("PAD_STERN_PREVIEW_DIR", raising=False)
    _write_machine_render({"idx": 8}, [np.array([1])], False, np)
    assert not (out / "idx0008_machine_render.wav").exists()


def test_slot_seed_dbfs_env(monkeypatch):
    from pinball_decryptor.plugins.stern.engine import _slot_seed_dbfs
    monkeypatch.delenv("PAD_STERN_SLOT_SEED_DB", raising=False)
    assert _slot_seed_dbfs() is None            # off by default
    monkeypatch.setenv("PAD_STERN_SLOT_SEED_DB", "-65")
    assert _slot_seed_dbfs() == -65.0
    monkeypatch.setenv("PAD_STERN_SLOT_SEED_DB", "5")   # positive = off
    assert _slot_seed_dbfs() is None
    monkeypatch.setenv("PAD_STERN_SLOT_SEED_DB", "-200")  # clamp
    assert _slot_seed_dbfs() == -90.0


def test_apply_slot_seed_makes_silence_tonal_but_inaudible():
    """The seed turns flat silence into a spectrally-peaked (low flatness),
    still-inaudible signal -- the whole point (silence loses the codec-slot
    resolver, a tone wins it)."""
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import (_apply_slot_seed,
                                                        _MONO_RANGE)

    def specflat(x):
        x = np.asarray(x, float)
        if len(x) < 64 or np.std(x) < 1e-6:
            return 1.0
        m = 1 << int(np.floor(np.log2(len(x))))
        X = np.abs(np.fft.rfft((x[:m] - x[:m].mean()) * np.hanning(m)))[1:]
        X = np.maximum(X, 1e-9)
        return float(np.exp(np.mean(np.log(X))) / np.mean(X))

    n = 22050
    silent = np.zeros(n, np.int64)
    # off -> unchanged
    assert (_apply_slot_seed(silent, np, _MONO_RANGE, None) == 0).all()
    seeded = _apply_slot_seed(silent, np, _MONO_RANGE, -65.0)
    pk = int(np.abs(seeded).max())
    # inaudible: -65 dBFS ~= 18 counts
    assert 5 <= pk <= 40, pk
    # spectrally peaked (a tone) -> far below the noise codec's ~0.67 flatness
    assert specflat(seeded[:8192]) < 0.3
    # flat silence reads ~1.0 -> confirm the seed changed that
    assert specflat(np.zeros(4096)) > 0.9
    # edges land at (near) zero -> no step that itself clicks
    assert abs(int(seeded[0])) <= 1 and abs(int(seeded[-1])) <= 1


def test_encoders_apply_slot_seed(monkeypatch):
    """_encode_mono/_stereo feed the seed into the fitted target when on."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    monkeypatch.setenv("PAD_STERN_SLOT_SEED_DB", "-65")
    captured = {}

    class FakeGR:
        def encode_sound(self, p, tgt):
            captured["tgt"] = np.asarray(tgt)
            return 0, b"\0" * 8

    # patch the wav loader + the post-encode steps to isolate the seed path
    monkeypatch.setattr(E, "_load_wav", lambda *a, **k: np.zeros(4000, np.int64))
    monkeypatch.setattr(E, "_resolve_shared_boundary",
                        lambda *a, **k: b"\0" * 8)
    monkeypatch.setattr(E, "_apply_stock_head",
                        lambda *a, **k: (b"\0" * 8, False))
    monkeypatch.setattr(E, "_verify_encoded", lambda *a, **k: None)
    E._encode_mono(None, FakeGR(), {"length": 4000, "chan": 1, "idx": 1},
                   "x.wav", np)
    pk = int(np.abs(captured["tgt"]).max())
    assert 5 <= pk <= 40, pk            # the silent target now carries the seed

    # per-slot gate: with an idx list that excludes this sound, no seed
    monkeypatch.setenv("PAD_STERN_EXPERIMENT_IDXS", "999")
    captured.clear()
    E._encode_mono(None, FakeGR(), {"length": 4000, "chan": 1, "idx": 1},
                   "x.wav", np)
    assert int(np.abs(captured["tgt"]).max()) == 0     # gated out -> silent


def test_experiment_covers_idx_scope(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2.codec import experiment_covers

    monkeypatch.delenv("PAD_STERN_EXPERIMENT_IDXS", raising=False)
    assert experiment_covers({"idx": 231})            # unset = all
    monkeypatch.setenv("PAD_STERN_EXPERIMENT_IDXS", "231, 258")
    assert experiment_covers({"idx": 231})
    assert experiment_covers({"idx": 258})
    assert not experiment_covers({"idx": 99})
    monkeypatch.setenv("PAD_STERN_EXPERIMENT_IDXS", "  ")   # blank = all
    assert experiment_covers({"idx": 99})
    monkeypatch.setenv("PAD_STERN_EXPERIMENT_IDXS", "garbage")
    assert experiment_covers({"idx": 99})              # unparseable = all


def test_stock_head_respects_experiment_scope(monkeypatch):
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _apply_stock_head

    monkeypatch.setenv("PAD_STERN_HEAD_MODE", "stock")
    monkeypatch.setenv("PAD_STERN_EXPERIMENT_IDXS", "999")   # not our idx
    emu, p, rec, body = _stock_head_fixture(np, stock_word=0)   # idx 231
    tgt = np.zeros(400, np.int64)
    out, applied = _apply_stock_head(emu, p, p["body_off"], body, tgt, rec, np)
    assert not applied and out == body


def test_audit_audio_patches_clean_and_anomalies():
    from pinball_decryptor.plugins.stern.engine import _audit_audio_patches

    # Two mono sounds packed back-to-back: idx1 at 0 (len 100 -> 200 bytes),
    # idx2 at 200 (len 50 -> 100 bytes).
    params = [{"idx": 1, "body_off": 0, "length": 100, "chan": 1},
              {"idx": 2, "body_off": 200, "length": 50, "chan": 1}]
    logs = []
    log = lambda m, lv="info": logs.append((lv, m))

    clean = {0: b"\0" * 200, 200: b"\0" * 100}
    assert _audit_audio_patches(params, clean, log) == 0

    # A patch at an offset no sound owns.
    logs.clear()
    bad = {0: b"\0" * 200, 512: b"\0" * 40}
    assert _audit_audio_patches(params, bad, log) >= 1
    assert any("matches no sound" in m for _lv, m in logs)

    # A delta=-1 shifted window (start one word below body_off) is legitimate.
    logs.clear()
    shifted = {0: b"\0" * 200, 198: b"\0" * 100}     # idx2 window shifted -1
    assert _audit_audio_patches(params, shifted, log) == 0


def test_audio_profile_report(tmp_path):
    """Stock population + a hot bright replacement -> flagged row + CSV."""
    import csv
    import wave
    import numpy as np
    from pinball_decryptor.core.checksums import md5_file
    from pinball_decryptor.plugins.stern.engine import audio_profile_report

    def write_wav(path, samples):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(np.asarray(samples, np.int16).tobytes())

    n = 22050
    t = np.arange(n) / 44100.0
    # Stock-style: 60 ms ease-in, 500 Hz tone at moderate level.
    ramp = np.clip(t / 0.060, 0, 1)
    stock = (4000 * ramp * np.sin(2 * np.pi * 500 * t))
    # Replacement-style: instant hot 9 kHz tone.
    hot = (30000 * np.sin(2 * np.pi * 9000 * t))

    a = tmp_path / "audio"
    a.mkdir()
    for i in (1, 2, 3):
        write_wav(a / ("idx%04d.wav" % i), stock)
    write_wav(a / "idx0004.wav", hot)

    # Baseline: idx0001-3 unchanged, idx0004's hash deliberately stale.
    lines = []
    for i in (1, 2, 3):
        lines.append("audio/idx%04d.wav\t%s"
                     % (i, md5_file(str(a / ("idx%04d.wav" % i)))))
    lines.append("audio/idx0004.wav\t" + "0" * 32)
    (tmp_path / ".checksums.md5").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")

    logged = []
    csv_path, n_sounds, n_rep, n_flagged = audio_profile_report(
        str(tmp_path), lambda m, lv="info": logged.append((lv, m)))
    assert n_sounds == 4 and n_rep == 1 and n_flagged == 1
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    by_idx = {r["idx"]: r for r in rows}
    assert by_idx["idx0004"]["status"] == "replaced"
    assert "brighter" in by_idx["idx0004"]["flags"] or \
           "hotter" in by_idx["idx0004"]["flags"]
    assert by_idx["idx0001"]["status"] == "stock"
    assert by_idx["idx0001"]["flags"] == ""


# ---------------------------------------------------------------------------
# Master-directory window feathering (2026-07-24, the callout-click root cause:
# the ~two 512-byte forced-stock windows per re-encoded sound play a bit-exact
# fragment of the ORIGINAL audio; feathering blends the target into it so the
# fragment can't butt a hard edge against foreign content).
# ---------------------------------------------------------------------------

def test_feather_ms_env(monkeypatch):
    from pinball_decryptor.plugins.stern.engine import _feather_ms

    monkeypatch.delenv("PAD_STERN_FEATHER_MS", raising=False)
    assert _feather_ms() == 15.0                  # on by default
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "30")
    assert _feather_ms() == 30.0
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "0")
    assert _feather_ms() == 0.0                   # the A/B kill switch
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "-4")
    assert _feather_ms() == 0.0
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "9999")
    assert _feather_ms() == 200.0
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "garbage")
    assert _feather_ms() == 15.0                  # unparseable -> default


def test_consumed_sample_runs_mapping():
    import numpy as np
    from pinball_decryptor.plugins.stern.engine import _consumed_sample_runs
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    # Mono: one clean byte run, one run straddling the emitted end (clipped),
    # plus offsets outside the body (ignored, before and after).
    p = {"body_off": 1000, "length": 4000, "chan": 1}
    n = emitted_length(4000)
    run1 = np.arange(1200, 1200 + 256)            # samples 100..227
    run2 = np.arange(1000 + 2 * (n - 10), 1000 + 2 * (n + 50))
    consumed = np.unique(np.concatenate(
        [np.arange(100, 110), run1, run2, [1000 + 2 * 4000 + 8]]))
    spans = _consumed_sample_runs(consumed, p, np)
    assert spans == [(100, 228), (n - 10, n)]

    # Stereo: 4 bytes per frame -> frame index, not word index.
    p2 = {"body_off": 0, "length": 2000, "chan": 2}
    spans2 = _consumed_sample_runs(np.arange(400, 912), p2, np)
    assert spans2 == [(100, 228)]

    # No consumed bytes inside the body at all.
    assert _consumed_sample_runs(np.array([50, 60]), p, np) == []


def _feather_fixture(np, n, stock, runs, chan=1):
    import types

    if chan == 2:
        decode = lambda p, **k: (np.asarray(stock[0]), np.asarray(stock[1]),
                                 True)
    else:
        decode = lambda p, **k: (np.asarray(stock), None, False)
    emu = types.SimpleNamespace(decode=decode)
    p = {"idx": 231, "length": n + 200, "body_off": 0, "chan": chan,
         "consumed_runs": runs}
    return emu, p


def test_feather_stock_windows_blends_smooth(monkeypatch):
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E

    monkeypatch.delenv("PAD_STERN_FEATHER_MS", raising=False)
    n = 4000
    t = np.arange(n)
    stock = np.round(2000.0 * np.sin(2 * np.pi * 100.0 * t / 44100.0)) \
        .astype(np.int64)
    emu, p = _feather_fixture(np, n, stock, [(1500, 1756)])
    tgt = np.zeros(n, np.int64)
    out = E._feather_stock_windows(emu, p, [tgt], np,
                                   -E._MONO_RANGE, E._MONO_RANGE - 1)[0]
    assert out is tgt                              # mutated in place
    F = int(round(E._feather_ms() * 44.1))
    # the window (and the 4-sample pad) carries the exact original audio
    assert (out[1500:1756] == stock[1500:1756]).all()
    assert (out[1496:1760] == stock[1496:1760]).all()
    # untouched far outside the blend
    assert (out[:1496 - F] == 0).all() and (out[1760 + F:] == 0).all()
    # smooth everywhere: worst step must be ~content-slope, nowhere near the
    # ~2000-count cliff a raw paste of the fragment would leave
    assert int(np.abs(np.diff(out)).max()) < 120
    # int dtype preserved for the exact-encode contract
    assert out.dtype == np.int64


def test_feather_stock_windows_noops(monkeypatch):
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E

    n = 2000
    stock = np.full(n, 3000, np.int64)
    tgt0 = np.zeros(n, np.int64)

    # no consumed_runs key (bank rows, non-feathered builds) -> untouched
    emu, p = _feather_fixture(np, n, stock, [(500, 700)])
    del p["consumed_runs"]
    assert (E._feather_stock_windows(emu, p, [tgt0.copy()], np,
                                     -11147, 11146)[0] == 0).all()

    # PAD_STERN_FEATHER_MS=0 -> untouched
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "0")
    emu, p = _feather_fixture(np, n, stock, [(500, 700)])
    assert (E._feather_stock_windows(emu, p, [tgt0.copy()], np,
                                     -11147, 11146)[0] == 0).all()
    monkeypatch.delenv("PAD_STERN_FEATHER_MS", raising=False)

    # decode failure -> untouched (feathering must never break an encode)
    import types
    emu = types.SimpleNamespace(decode=lambda p, **k: None)
    p = {"idx": 1, "length": n + 200, "body_off": 0, "chan": 1,
         "consumed_runs": [(500, 700)]}
    assert (E._feather_stock_windows(emu, p, [tgt0.copy()], np,
                                     -11147, 11146)[0] == 0).all()

    # clip bound respected even for pathological stock values
    emu, p = _feather_fixture(np, n, np.full(n, 99999, np.int64), [(500, 700)])
    out = E._feather_stock_windows(emu, p, [tgt0.copy()], np, -11147, 11146)[0]
    assert int(out.max()) == 11146


def test_encoders_feather_consumed_windows(monkeypatch):
    """_encode_mono/_encode_stereo blend the forced-stock windows into the
    fitted target (the same array the zero-error verify checks)."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    monkeypatch.delenv("PAD_STERN_FEATHER_MS", raising=False)
    n = emitted_length(4000)
    t = np.arange(n)
    stockL = np.round(1500.0 * np.sin(2 * np.pi * 80.0 * t / 44100.0)) \
        .astype(np.int64)
    stockR = -stockL
    captured = {}

    class FakeGR:
        def encode_sound(self, p, tgt):
            captured["tgt"] = np.asarray(tgt)
            return 0, b"\0" * 8

    class FakeSR:
        def encode_sound(self, p, L, R):
            captured["L"], captured["R"] = np.asarray(L), np.asarray(R)
            return 0, b"\0" * 8

    monkeypatch.setattr(E, "_load_wav",
                        lambda path, stereo, np_: (np.zeros((6000, 2), np.int64)
                                                   if stereo else
                                                   np.zeros(6000, np.int64)))
    monkeypatch.setattr(E, "_resolve_shared_boundary",
                        lambda *a, **k: b"\0" * 8)
    monkeypatch.setattr(E, "_apply_stock_head",
                        lambda *a, **k: (b"\0" * 8, False))
    monkeypatch.setattr(E, "_verify_encoded", lambda *a, **k: None)

    emu = types.SimpleNamespace(
        decode=lambda p, **k: (stockL, None, False))
    p = {"length": 4000, "chan": 1, "idx": 1, "body_off": 0,
         "consumed_runs": [(1500, 1756)]}
    E._encode_mono(emu, FakeGR(), p, "x.wav", np)
    tgt = captured["tgt"]
    assert (tgt[1500:1756] == stockL[1500:1756]).all()
    assert int(np.abs(np.diff(tgt)).max()) < 120
    # without runs the silent target stays silent (bank rows keep old behavior)
    E._encode_mono(emu, FakeGR(), {"length": 4000, "chan": 1, "idx": 1,
                                   "body_off": 0}, "x.wav", np)
    assert int(np.abs(captured["tgt"]).max()) == 0

    emu2 = types.SimpleNamespace(
        decode=lambda p, **k: (stockL, stockR, True))
    p2 = {"length": 4000, "chan": 2, "idx": 2, "body_off": 0,
          "consumed_runs": [(1500, 1756)]}
    E._encode_stereo(emu2, FakeSR(), p2, "x.wav", np)
    assert (captured["L"][1500:1756] == stockL[1500:1756]).all()
    assert (captured["R"][1500:1756] == stockR[1500:1756]).all()


def test_verify_final_reports_feathered_snippet(monkeypatch):
    """_verify_final_patches: rev_pk comes from the consumed spans and the log
    line says feathered-blend (info) when feathering is on, scrap-warning when
    it's off."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    from pinball_decryptor.plugins.stern.spike2.emulator import emitted_length

    n = emitted_length(4000)
    decoded = np.zeros(n, np.int64)
    decoded[1000:1256] = 5000                  # the forced original fragment

    stock_bytes = b"\x11\x22" * 8000

    class MM:
        def __getitem__(self, sl):
            return stock_bytes[sl]

        def size(self):
            return len(stock_bytes)

    class FakeEmu:
        def __init__(self, gr, img):
            self.mm = MM()

        def boot(self):
            pass

        def decode(self, p, max_secs=None, cancel=None, progress=None):
            return (decoded, None, False)

        def close(self):
            pass

    monkeypatch.setattr(EM, "Spike2Emu", FakeEmu)
    p = {"idx": 7, "length": 4000, "body_off": 64, "chan": 1,
         "consumed_runs": [(1000, 1256)]}
    patches = {64: b"\x33\x44" * 4000}
    logs = []
    log = lambda m, lv="info": logs.append((lv, m))

    monkeypatch.delenv("PAD_STERN_FEATHER_MS", raising=False)
    monkeypatch.delenv("PAD_STERN_PREVIEW_DIR", raising=False)
    out = E._verify_final_patches("gr", "img", patches, [p], np, log)
    assert len(out) == 1
    idx, peak_db, head_db, rev_db = out[0]
    assert idx == 7 and abs(rev_db - peak_db) < 0.01   # rev_pk == the fragment
    assert any(lv == "info" and "feathered" in m for lv, m in logs)
    assert not any(lv == "warning" for lv, m in logs)

    # feathering off -> the honest scrap warning
    logs.clear()
    monkeypatch.setenv("PAD_STERN_FEATHER_MS", "0")
    E._verify_final_patches("gr", "img", patches, [p], np, log)
    assert any(lv == "warning" and "scrap" in m for lv, m in logs)


def test_ensure_consumed_survives_cache_save_failure(monkeypatch):
    """A successful derive must feed THIS build even when the cache can't be
    persisted (_save_consumed swallows write errors)."""
    import types
    import numpy as np
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM

    class FakeEmu:
        mu = types.SimpleNamespace(hook_del=lambda h: None)

        def __init__(self, gr, img):
            pass

        def boot(self):
            pass

        def derive_params(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr(EM, "Spike2Emu", FakeEmu)
    monkeypatch.setattr(E, "_load_consumed", lambda g, i: None)
    monkeypatch.setattr(E, "_install_consumed_hook",
                        lambda emu: ({9, 3, 5}, "hh"))
    monkeypatch.setattr(E, "_save_consumed", lambda fp, reads: None)  # "fails"
    monkeypatch.setattr(E, "_fingerprint", lambda g, i: "f" * 64)
    out = E._ensure_consumed("g", "i", lambda *a, **k: None)
    assert out is not None and list(out) == [3, 5, 9]
