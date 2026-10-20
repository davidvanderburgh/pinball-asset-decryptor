"""PAD-637: multi-band Spike 2 records - N variants of one sound interleaved frame by frame.

Led Zeppelin LE/Pro 1.22's ten (mono, 12 or 24 variants) and Foo Fighters 1.04's one (stereo, 2 variants)
decoded as stationary noise and failed the encoder's self-test. Each variant is now decoded and encoded on its
own (the voice's 1-based band picks it), Extract writes them one after another, and Write cuts an edited file
back into them or gives one new sound to all of them."""
import os
import struct
import tempfile

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import codec as CODEC
from pinball_decryptor.plugins.stern.spike2 import emulator as EMU
from pinball_decryptor.plugins.stern.spike2 import locate as LOC

MONO12 = {"idx": 31, "chan": 1, "stride": 12, "length": 1200, "body_off": 0x1000, "scale": 8}
STEREO2 = {"idx": 3206, "chan": 2, "stride": 4, "length": 1200, "body_off": 0x1000, "scale": 11}
PLAIN = {"idx": 0, "chan": 1, "stride": 1, "length": 1200, "body_off": 0x1000, "scale": 24}
PLAIN_ST = {"idx": 1, "chan": 2, "stride": 2, "length": 1200, "body_off": 0x1000, "scale": 3}


def test_a_record_s_variants_come_from_its_stride_and_channels():
    assert EMU.bands_of(MONO12) == 12 and EMU.bands_of(STEREO2) == 2
    assert EMU.bands_of(PLAIN) == 1 and EMU.bands_of(PLAIN_ST) == 1
    assert [EMU.frame_bytes(p) for p in (MONO12, STEREO2, PLAIN, PLAIN_ST)] == [24, 8, 2, 4]
    assert EMU.emitted_total(MONO12) == 12 * 1000
    assert EMU.emitted_total(EMU.band_params(MONO12, 3)) == 1000
    # the obj's band count (+0x1c) has to agree; a layout not seen stays one plain sound
    raw = bytearray(0x80)
    raw[0x1c] = 6
    assert EMU.bands_of(dict(MONO12, _rawobj=bytes(raw))) == 1
    raw[0x1c] = 12
    assert EMU.bands_of(dict(MONO12, _rawobj=bytes(raw))) == 12


def test_the_voice_carries_the_band():
    class _E:
        OBJ_VA = 0x18000000
    v = EMU.Spike2Emu._voice(_E(), 1, 7)
    assert v[0x20] == 7 and struct.unpack_from("<I", v, 0)[0] == 0x18000000
    assert EMU.Spike2Emu._voice(_E(), 2)[0x20] == 0


def test_an_edited_file_is_cut_back_into_its_variants_any_other_sound_goes_to_all():
    n, nb = 1000, 12
    edited = np.arange(n * nb)
    parts = E._band_pieces(edited, n, nb, np)
    assert len(parts) == nb and all(len(x) == n for x in parts)
    assert parts[4][0] == 4 * n
    # a couple of percent off (trimmed in an editor) is still that file
    parts = E._band_pieces(edited[:-150], n, nb, np)
    assert len(parts) == nb and parts[11][-1] == n * nb - 151
    one = np.ones(3 * n)
    parts = E._band_pieces(one, n, nb, np)
    assert len(parts) == nb and all(len(x) == 3 * n for x in parts)
    # a plain sound is its one piece
    assert len(E._band_pieces(one, n, 1, np)) == 1
    st = np.zeros((n * 2, 2))
    assert [len(x) for x in E._band_pieces(st, n, 2, np)] == [n, n]


def test_a_multi_band_replacement_keeps_its_record_length(tmp_path):
    wav = tmp_path / "idx0031.wav"
    import wave
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 20000)
    byidx = {31: MONO12, 0: PLAIN}
    fits, grows = E._classify_audio_edits(byidx, {31: str(wav), 0: str(wav)}, str(tmp_path))
    assert 31 in fits and 0 in grows


def test_a_multi_band_record_is_never_lengthened(monkeypatch):
    msgs = []
    monkeypatch.setattr(E, "_recovery_valid", lambda *a, **k: pytest.fail("no emulator for it"))
    kept = E._grows_reencodable("g", "i", {31: (1, 2)}, {31: MONO12},
                                lambda m, lvl="info": msgs.append(m))
    assert kept == {} and "12 variants" in msgs[0] and "trimmed to fit" in msgs[0]


class _MM:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, sl):
        return self.data[sl]


def _rec(cls, mm):
    r = cls.__new__(cls)
    r.emu = type("_Emu", (), {"mm": _MM(mm)})()
    return r


def test_each_mono_variant_is_written_into_its_own_lane_only(monkeypatch):
    p = dict(MONO12, body_off=0)
    stock = np.arange(12 * 1200, dtype="<u2").tobytes()
    seen = []

    def window(self, q, seg, blocks, body=None):
        seen.append((q["band"], len(seg)))
        body[:] = 0xF000 + q["band"]          # every frame's word of this variant
        return q["body_off"], body.tobytes()

    monkeypatch.setattr(CODEC.GenRecover, "_encode_window", window)
    gr = _rec(CODEC.GenRecover, stock)
    tgt = np.zeros(12 * 1000)
    tgt_only_2 = tgt[:1500]                      # reaches variant 2's first 500 samples
    off, body = gr.encode_sound(p, tgt_only_2)
    words = np.frombuffer(body, "<u2").reshape(1200, 12)
    assert off == 0 and seen == [(1, 1000), (2, 500)]
    assert (words[:, 0] == 0xF001).all() and (words[:, 1] == 0xF002).all()
    assert (words[:, 2:] == np.frombuffer(stock, "<u2").reshape(1200, 12)[:, 2:]).all()
    seen.clear()
    off, body = gr.encode_sound(EMU.band_params(p, 12), np.zeros(1000))
    assert seen == [(12, 1000)]
    assert (np.frombuffer(body, "<u2").reshape(1200, 12)[:, 11] == 0xF00C).all()


def test_each_stereo_variant_is_written_into_its_own_pair_only(monkeypatch):
    p = dict(STEREO2, body_off=0)
    stock = np.arange(4 * 1200, dtype="<u2").tobytes()

    def window(self, q, L, R, blocks, body=None):
        assert body.shape == (1200, 2)
        body[:, 0] = 0xA000 + q["band"]
        body[:, 1] = 0xB000 + q["band"]
        return q["body_off"], b""

    monkeypatch.setattr(CODEC.StereoRecover, "_encode_window", window)
    sr = _rec(CODEC.StereoRecover, stock)
    off, body = sr.encode_sound(p, np.zeros(2000), np.zeros(2000))
    fr = np.frombuffer(body, "<u2").reshape(1200, 4)
    assert (fr[:, 0] == 0xA001).all() and (fr[:, 1] == 0xB001).all()
    assert (fr[:, 2] == 0xA002).all() and (fr[:, 3] == 0xB002).all()
    flat = np.zeros(8, "<u2")
    CODEC._put_frames(flat, 1, 3, np.array([[1, 2], [3, 4]]))
    assert list(flat) == [0, 0, 1, 2, 3, 4, 0, 0]


class _Fw:
    """Just enough of locate._FwView for the selector search: a .text of hand-assembled words."""

    def __init__(self, words, addr=0x1000):
        self.raw = b"".join(struct.pack("<I", w) for w in words)
        self.secs = {".text": {"off": 0, "addr": addr, "size": len(self.raw)}}

    def w_text(self, va):
        o = va - self.secs[".text"]["addr"]
        return struct.unpack_from("<I", self.raw, o)[0]


NOP = 0xE1A00000                                  # mov r0, r0
SELECTOR = [
    0xE5D3201B,   # ldrb r2, [r3, #0x1b]     chan
    0xE5D3101C,   # ldrb r1, [r3, #0x1c]     bands
    0xE2422001,   # sub r2, r2, #1
    0xE5D3301D,   # ldrb r3, [r3, #0x1d]     scale
    0xE16F2F12,   # clz r2, r2
    0xE3510001,   # cmp r1, #1
    0xE594102C,   # ldr r1, [r4, #0x2c]
    0xE1A022A2,   # lsr r2, r2, #5
    0x9A000010,   # bls <one band>
    0xE3510000,   # cmp r1, #0
    0x0A000010,   # beq
    0xE3520000,   # cmp r2, #0
    0xE30A21B0,   # movw r2, #0xa1b0
    0xE340204E,   # movt r2, #0x4e
    0xE0823303,   # add r3, r2, r3, lsl #6
    0x15132D2C,   # ldrne r2, [r3, #-0xd2c]  mono render
    0x05132D30,   # ldreq r2, [r3, #-0xd30]  stereo render
    0x15133D0C,   # ldrne r3, [r3, #-0xd0c]
    0x05133D10,   # ldreq r3, [r3, #-0xd10]
]


def test_the_multi_band_codec_slot_is_read_from_the_voice_setup():
    fw = _Fw([NOP] * 8 + SELECTOR + [NOP] * 24)
    # Led Zeppelin Pro 1.22's shape: its table base is the multi-band row itself
    assert LOC.find_band_codecs(fw, 0x4ea1b0 - 0xd30) == {"BAND_RENDER": 0}
    # Foo Fighters 1.04's: the 0x40-aligned base sits 0x10 before it
    assert LOC.find_band_codecs(fw, 0x4ea1b0 - 0xd40) == {"BAND_RENDER": 0x10}
    # no selector, no answer
    assert LOC.find_band_codecs(_Fw([NOP] * 40), 0) is None


IMG_DIRS = [d for d in (os.environ.get("PAD_SPIKE2_IMG_DIR"), r"D:\Pinball\images\Stern\spike2") if d]
LZ_PRO = "led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw"


def _card(name):
    for d in IMG_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


@pytest.fixture
def _no_faulthandler():
    """unicorn services guest memory through the host's fault machinery, which pytest's
    faulthandler reports as an access violation on Windows (see test_stern_audio_tail)."""
    import faulthandler
    was = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was:
            faulthandler.enable()


@pytest.mark.slow
def test_led_zeppelin_pro_variants_decode_as_audio_and_re_encode_bit_exact(_no_faulthandler):
    card = _card(LZ_PRO)
    if card is None:
        pytest.skip("card image %s not present" % LZ_PRO)
    work = os.path.join(tempfile.gettempdir(), "pad637_lzpro122")
    gr, img = os.path.join(work, "game_real"), os.path.join(work, "image.bin")
    if not (os.path.exists(gr) and os.path.exists(img)):
        os.makedirs(work, exist_ok=True)
        with open(card, "rb") as f:
            E._extract_inputs(f, E._linux_partitions(card), work, lambda *a, **k: None)
    emu = EMU.Spike2Emu(gr, img)
    try:
        emu.boot()
        params = E._load_or_derive_params(emu, gr, img, lambda *a, **k: None,
                                          lambda *a, **k: None)
        mb = {p["idx"]: p for p in params if EMU.bands_of(p) > 1}
        assert sorted(mb) == [31, 57, 65, 278, 286, 333, 338, 390, 517, 519]
        assert emu.BAND_RENDER == 0
        p = mb[31]
        out = emu.decode(p)
        n = EMU.emitted_length(p["length"])
        assert len(out[0]) == 12 * n
        # twelve pitched variants, none of them the old stationary noise
        for k in range(12):
            assert emu._specflat(out[0][k * n:(k + 1) * n]) < 0.45, k
        gen = CODEC.GenRecover(emu)
        st = CODEC.StereoRecover(emu)
        assert E._recovery_valid(emu, gen, st, p, np)
        # an ordinary sound of the same scale still resolves to the codec that plays it
        q = next(x for x in params if x["scale"] == p["scale"] and EMU.bands_of(x) == 1
                 and x["chan"] == 1 and x["length"] > 8000)
        assert emu._specflat(emu.decode(q, max_secs=1.0)[0]) < 0.6
    finally:
        emu.close()


# ---- the Audio tab ---------------------------------------------------------------------------
def test_extract_lists_the_records_of_variants(tmp_path):
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    from pinball_decryptor.core.registry import get_manufacturer
    assert CS.write_variants(str(tmp_path), [MONO12, PLAIN, STEREO2, PLAIN_ST]) == 2
    assert CS.sound_variants(str(tmp_path)) == {31: 12, 3206: 2}
    rels = ["audio/idx0031.wav", "audio/idx0000.wav", "audio/idx3206 - SONG.wav", "music/Song.wav"]
    assert get_manufacturer("stern").sound_variant_counts(str(tmp_path), rels) == {
        "audio/idx0031.wav": 12, "audio/idx3206 - SONG.wav": 2}
    # a card without any takes a stale list away
    assert CS.write_variants(str(tmp_path), [PLAIN]) == 0
    assert CS.sound_variants(str(tmp_path)) == {}
    assert not os.path.exists(tmp_path / CS.VARIANTS_JSON)


def test_the_audio_tab_says_a_file_is_variants_and_types_it_by_one(tmp_path):
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    from tests.test_webui_audio import _open, _wait, _wav
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    for rel in ("audio/idx0001.wav", "audio/idx0002.wav"):
        _wav(str(proj / rel), seconds=24.0)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(proj))
    CS.write_variants(str(proj), [dict(MONO12, idx=1)])
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, str(proj))
        assert _wait(w, lambda: all(r["len"] != "—" for r in w.state("audio")["rows"]))
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        var, plain = rows["audio/idx0001.wav"], rows["audio/idx0002.wav"]
        assert var["fmt"].endswith(" · 12 variants") and "fmt_tip" not in plain
        assert var["fmt_tip"][0].startswith("This sound comes in 12 variants, 2.00 s each")
        assert "each variant gets its own part back" in var["fmt_tip"][1]
        # 24 s is music by length on a title with no music banks; 12 variants of 2 s are not
        w.call("audio.sort", "type")                     # the list again, lengths known
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        assert rows["audio/idx0002.wav"]["type"] == "Music"
        assert rows["audio/idx0001.wav"]["type"] != "Music"
