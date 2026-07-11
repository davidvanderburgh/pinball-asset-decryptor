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
