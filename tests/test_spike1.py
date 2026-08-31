"""Stern Spike 1 era: detection, partition walk, master-directory parse,
WAV slot naming, and the Write path's sample-fitting helpers.

The container model these tests pin down was verified byte-complete against
all four real Spike 1 titles (WWE LE 1.35, KISS LE 1.41, GOT LE 1.37,
Ghostbusters LE 1.17): the referenced bodies tile 100.0% of the audio region
and every record's tick length matches its primary body.  A gated test
re-checks the real GOT card when the image is present locally.
"""

import os

import pytest

from pinball_decryptor.plugins.stern import spike1
from pinball_decryptor.plugins.stern.formats import (
    SPIKE1_GENERIC_KEY, detect_spike1_game, is_spike1_card_parts,
    parse_all_partitions, spike1_linux_partitions)
from tests import synthetic

_GOT_ISO = os.path.join(os.path.dirname(__file__), "..", "images", "Stern",
                        "spike1", "GOT_LE-1_37.iso")


# ---------------------------------------------------------------------------
# partition walk + detection
# ---------------------------------------------------------------------------

def test_parse_all_partitions_walks_ebr_chain(tmp_path):
    iso = synthetic.make_spike1_mbr(tmp_path / "card.iso")
    parts = parse_all_partitions(str(iso))
    # 3 primaries (extended container not listed) + 2 logicals
    assert [(t, lba) for _i, t, lba, _s in parts] == [
        (0x01, 35), (0xda, 7000), (0x83, 14000),
        (0x83, 16384 + 8), (0x83, 16384 + 2048 + 8)]
    # logical indexes continue after the primaries
    assert [p[0] for p in parts] == [0, 1, 2, 4, 5]


def test_spike1_linux_partitions_includes_logicals(tmp_path):
    iso = synthetic.make_spike1_mbr(tmp_path / "card.iso")
    parts = spike1_linux_partitions(str(iso))
    # rootfs (2000 sectors) largest first, then the two 1024-sector logicals
    assert parts[0] == (14000 * 512, 2000 * 512)
    assert len(parts) == 3


def test_detect_spike1_game_by_signature_and_hint(tmp_path):
    for name, key in (("GOT_LE-1_37.iso", "game_of_thrones"),
                      ("KISS_LE-1_41_0.iso", "kiss"),
                      ("WWE_LE-1_35.iso", "wwe_wrestlemania"),
                      ("ghostbusters_le-1_17.iso", "ghostbusters"),
                      ("some_random_dump.img", SPIKE1_GENERIC_KEY)):
        iso = synthetic.make_spike1_mbr(tmp_path / name)
        assert detect_spike1_game(str(iso)) == key, name


def test_detect_spike1_game_declines_wrong_extension(tmp_path):
    iso = synthetic.make_spike1_mbr(tmp_path / "card.dat")
    assert detect_spike1_game(str(iso)) is None


def test_detect_spike1_game_declines_non_spike1(tmp_path):
    p = tmp_path / "other.iso"
    p.write_bytes(b"\x00" * 4096)
    assert detect_spike1_game(str(p)) is None


def test_is_spike1_card_parts_needs_all_three_anchors():
    good = [(0, 0x01, 35, 6965), (1, 0xda, 7000, 7000),
            (2, 0x83, 14000, 2000)]
    assert is_spike1_card_parts(good)
    assert not is_spike1_card_parts(good[:2])
    # a Spike 2 card's shape must not read as Spike 1
    spike2 = [(0, 0x0c, 8192, 16384), (1, 0x83, 24576, 100000)]
    assert not is_spike1_card_parts(spike2)


def test_stern_detect_reports_spike1_era(manufacturers_by_key, tmp_path):
    stern = manufacturers_by_key["stern"]
    iso = synthetic.make_spike1_mbr(tmp_path / "GOT_LE-1_37.iso")
    game = stern.detect(str(iso))
    assert game is not None
    assert game.era == "spike1"
    assert game.key == "game_of_thrones"
    assert "Spike 1" in game.display


def test_stern_spike1_era_surface(manufacturers_by_key):
    stern = manufacturers_by_key["stern"]
    era_before = stern.current_era
    try:
        stern.set_era("spike1")
        assert stern.current_era == "spike1"
        caps = stern.capabilities
        assert caps.extract and caps.write and caps.replace_audio
        assert not caps.direct_ssd and not caps.emulate
        assert stern.write_output_ext() == ".iso"
        from pinball_decryptor.plugins.stern.pipeline import (
            Spike1ExtractPipeline, Spike1WritePipeline)
        assert stern.extract_phases == Spike1ExtractPipeline.PHASES
        assert stern.write_phases == Spike1WritePipeline.PHASES
        nul = lambda *a, **k: None
        assert isinstance(
            stern.make_extract_pipeline("x.iso", "o", nul, nul, nul, nul),
            Spike1ExtractPipeline)
        assert isinstance(
            stern.make_write_pipeline("x.iso", "a", "o.iso",
                                      nul, nul, nul, nul),
            Spike1WritePipeline)
        # unknown era keys still snap back to spike2 (the pill contract)
        stern.set_era("nonsense")
        assert stern.current_era == "spike2"
    finally:
        stern.set_era(era_before)


# ---------------------------------------------------------------------------
# master-directory parse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("front_header", [True, False])
def test_parse_master_synthetic(front_header):
    blob, expected = synthetic.make_spike1_image_bin(
        front_header=front_header)
    master = spike1.parse_master(blob)
    got = [(r["idx"], [(f, c, d) for (_o, f, c, d) in r["tracks"]])
           for r in master["records"]]
    assert got == expected


def test_parse_master_erased_front_uses_fixed_page():
    blob, _ = synthetic.make_spike1_image_bin(front_header=False)
    assert spike1.find_header2(blob) == 0x120000


def test_parse_master_rejects_garbage():
    with pytest.raises(spike1.Spike1Error):
        spike1.parse_master(b"\x00" * 4096)


def test_parse_master_ticks_field():
    blob, _ = synthetic.make_spike1_image_bin()
    master = spike1.parse_master(blob)
    rec0 = master["records"][0]
    frames, _ch, div = rec0["tracks"][0][1:]
    assert rec0["ticks"] == (frames * div + 5) // 6


# ---------------------------------------------------------------------------
# WAV slot naming
# ---------------------------------------------------------------------------

def test_wav_name_and_parse_round_trip():
    assert spike1.wav_name(21, 0) == "idx0021.wav"
    assert spike1.wav_name(21, 1) == "idx0021-t2.wav"
    assert spike1.parse_wav_stem("idx0021") == (21, 0)
    assert spike1.parse_wav_stem("idx0021-t2") == (21, 1)


def test_parse_wav_stem_survives_renames():
    # duration prefix (Length-prefix-names option)
    assert spike1.parse_wav_stem("01m22s235 - idx0301") == (301, 0)
    # transcribe / music-id rename keeps the idx token
    assert spike1.parse_wav_stem("idx0301 - Winter Is Coming") == (301, 0)
    assert spike1.parse_wav_stem("00m03s100 - idx0301-t2 - Layer") == (301, 1)
    assert spike1.parse_wav_stem("not_a_slot") is None


def test_wav_name_duration_prefix():
    assert spike1.wav_name(7, 0, frames=44100, rate=44100,
                           duration_names=True) == "00m01s000 - idx0007.wav"


# ---------------------------------------------------------------------------
# write-path sample fitting
# ---------------------------------------------------------------------------

def test_fit_frames_trims_and_pads():
    np = pytest.importorskip("numpy")
    a = np.ones((1000, 1), dtype=np.float32)
    trimmed = spike1._fit_frames(a, 500)
    assert trimmed.shape == (500, 1)
    assert trimmed[-1, 0] == 0.0          # faded to silence at the cut
    padded = spike1._fit_frames(a, 1500)
    assert padded.shape == (1500, 1)
    assert padded[-1, 0] == 0.0


def test_match_level_matches_rms_without_clipping():
    np = pytest.importorskip("numpy")
    t = np.arange(4410, dtype=np.float32) / 44100.0
    quiet = (1000 * np.sin(2 * np.pi * 440 * t))[:, None]
    loud = (20000 * np.sin(2 * np.pi * 440 * t))[:, None]
    out = spike1._match_level(quiet, loud)
    rms = float(np.sqrt(np.mean(np.square(out))))
    target = float(np.sqrt(np.mean(np.square(loud))))
    assert abs(rms - target) / target < 0.05
    assert float(np.max(np.abs(out))) <= 32767.0


def test_resample_halves_and_doubles():
    np = pytest.importorskip("numpy")
    a = np.arange(1000, dtype=np.float32)[:, None]
    down = spike1._resample(a, 44100, 22050)
    assert abs(len(down) - 500) <= 1
    up = spike1._resample(a, 22050, 44100)
    assert abs(len(up) - 2000) <= 1


# ---------------------------------------------------------------------------
# real card (gated on the local image library)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.path.isfile(_GOT_ISO),
                    reason="GOT_LE-1_37.iso not present locally")
def test_real_got_master_directory():
    parts = spike1_linux_partitions(_GOT_ISO)
    assert parts
    with open(_GOT_ISO, "rb") as f:
        reader, game_dir, image_node, sidx_path, sidx_node = \
            spike1.locate_assets(f, parts)
        assert game_dir == "GOT_LE"
        assert sidx_path and sidx_path.endswith(".sidx")
        fmap = spike1._FileMap(reader, image_node)
        master = spike1.parse_master(spike1._CardWindow(f, fmap), fmap.size)
    recs = master["records"]
    assert len(recs) == 1930
    assert sum(len(r["tracks"]) for r in recs) == 1940
    # every sound is mono/stereo PCM at 44.1k or 22.05k
    for r in recs:
        for _off, frames, ch, div in r["tracks"]:
            assert frames > 0 and ch in (1, 2) and div in (1, 2)


# ---------------------------------------------------------------------------
# full card I/O on a synthetic Spike 1 card (real ext2, real sidx digests)
# ---------------------------------------------------------------------------

def _synth_extract(tmp_path, **image_kwargs):
    from pinball_decryptor.core import checksums
    from pinball_decryptor.plugins.stern.formats import (
        spike1_linux_partitions as _parts)
    card = str(tmp_path / "synth.iso")
    _p, expected, image_bin = synthetic.make_spike1_card(card, **image_kwargs)
    out_dir = str(tmp_path / "extract")
    os.makedirs(out_dir)
    res = spike1.extract_all(card, _parts(card), out_dir)
    checksums.generate_checksums(out_dir)
    return card, out_dir, expected, image_bin, res


def test_synth_card_extract_pcm_exact(tmp_path):
    import wave
    card, out_dir, expected, _ib, res = _synth_extract(tmp_path)
    assert res["sounds"] == 2 and res["tracks"] == 3
    assert sorted(os.listdir(os.path.join(out_dir, "audio"))) == [
        "idx0000.wav", "idx0001-t2.wav", "idx0001.wav"]
    # idx0000's PCM must be byte-identical to the synthetic body (seed 1)
    with wave.open(os.path.join(out_dir, "audio", "idx0000.wav")) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 44100)
        raw = w.readframes(w.getnframes())
    assert raw == bytes((1 + i) & 0xff for i in range(200))
    # the -t2 layer decodes with its own rate/channels (seed 3, 22.05k mono)
    with wave.open(os.path.join(out_dir, "audio", "idx0001-t2.wav")) as w:
        assert (w.getnchannels(), w.getframerate()) == (1, 22050)


def test_synth_card_write_patches_and_refreshes_sidx(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import wave
    np = pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import sidx as sidx_mod
    from pinball_decryptor.plugins.stern.formats import (
        spike1_linux_partitions as _parts)

    card, out_dir, _exp, _ib, _res = _synth_extract(tmp_path)
    newpcm = np.full(100, 1234, dtype="<i2")
    with wave.open(os.path.join(out_dir, "audio", "idx0000.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(newpcm.tobytes())
    # loudness match off -> the patched body must be byte-exact
    monkeypatch.setenv("PAD_STERN_MATCH_LOUDNESS", "0")
    out_card = str(tmp_path / "out.iso")
    res = spike1.write_image(card, out_dir, out_card)
    assert res == {"audio": 1, "skipped": []}

    with open(out_card, "rb") as f:
        reader, game_dir, node, _sp, sn = spike1.locate_assets(
            f, _parts(out_card))
        fmap = spike1._FileMap(reader, node)
        new_ib = fmap.read(f, 0, fmap.size)
        sdata = reader.read_file_bytes(sn)
    master = spike1.parse_master(new_ib)
    body_off, frames, ch, _div = master["records"][0]["tracks"][0]
    assert new_ib[body_off + 8:body_off + 8 + 2 * ch * frames] \
        == newpcm.tobytes()
    # the card's own validation record now matches the patched image.bin
    recs, _crc, fmt = sidx_mod.parse_records(sdata)
    po = recs["%s/image.bin" % game_dir]
    assert fmt == "FINF"
    assert sdata[po + 21:po + 41] == hmac.new(
        sidx_mod.SIDX_KEY, new_ib, hashlib.sha1).digest()
    assert sdata[po + 41:po + 57] == hashlib.md5(new_ib).digest()


def test_synth_card_write_skips_bad_wav(tmp_path, monkeypatch):
    import struct as _struct
    np = pytest.importorskip("numpy")
    import wave
    card, out_dir, _exp, image_bin, _res = _synth_extract(tmp_path)
    # slot idx0000: a float32 (format tag 3) WAV — a common editor export
    data = np.zeros(50, dtype="<f4").tobytes()
    hdr = (b"RIFF" + _struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
           + _struct.pack("<IHHIIHH", 16, 3, 1, 44100, 44100 * 4, 4, 32)
           + b"data" + _struct.pack("<I", len(data)))
    with open(os.path.join(out_dir, "audio", "idx0000.wav"), "wb") as f:
        f.write(hdr + data)
    # slot idx0001: a good change that must still land
    with wave.open(os.path.join(out_dir, "audio", "idx0001.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(np.full(120, 99, dtype="<i2").tobytes())
    monkeypatch.setenv("PAD_STERN_MATCH_LOUDNESS", "0")
    out_card = str(tmp_path / "out.iso")
    res = spike1.write_image(card, out_dir, out_card)
    assert res["audio"] == 1
    assert res["skipped"] == ["idx0000.wav"]
    # the bad slot kept its stock bytes
    from pinball_decryptor.plugins.stern.formats import (
        spike1_linux_partitions as _parts)
    with open(out_card, "rb") as f:
        reader, _gd, node, _sp, _sn = spike1.locate_assets(
            f, _parts(out_card))
        fmap = spike1._FileMap(reader, node)
        new_ib = fmap.read(f, 0, fmap.size)
    master = spike1.parse_master(new_ib)
    b0 = master["records"][0]["tracks"][0]
    span = slice(b0[0] + 8, b0[0] + 8 + 2 * b0[2] * b0[1])
    assert new_ib[span] == image_bin[span]


def test_synth_card_write_cancel_removes_output(tmp_path):
    card, out_dir, _exp, _ib, _res = _synth_extract(tmp_path)
    out_card = str(tmp_path / "cancelled.iso")
    with pytest.raises(spike1.Spike1Cancelled):
        spike1.write_image(card, out_dir, out_card, cancel=lambda: True)
    assert not os.path.exists(out_card)


def test_synth_card_revert_restores_baseline(tmp_path):
    from pinball_decryptor.core import checksums
    card, out_dir, _exp, _ib, _res = _synth_extract(tmp_path)
    target = os.path.join(out_dir, "audio", "idx0000.wav")
    with open(target, "wb") as f:
        f.write(b"garbage")
    reverted, failed = spike1.revert_assets(card, out_dir,
                                            ["audio/idx0000.wav"])
    assert reverted == ["audio/idx0000.wav"] and not failed
    base = checksums.read_checksums(out_dir)["audio/idx0000.wav"]
    assert checksums.md5_file(target) == base


def test_parse_master_fixed_page_0x120038():
    blob, expected = synthetic.make_spike1_image_bin(front_header=False,
                                                     h2_at=0x120038)
    assert spike1.find_header2(blob) == 0x120038
    got = [(r["idx"], [(f, c, d) for (_o, f, c, d) in r["tracks"]])
           for r in spike1.parse_master(blob)["records"]]
    assert got == expected


def test_parse_master_rejects_zeroed_table():
    # a zeroed pointer table must fail cleanly, not materialize the file
    blob, _ = synthetic.make_spike1_image_bin()
    b = bytearray(blob)
    b[0xC0:0xC0 + 80] = bytes(80)
    with pytest.raises(spike1.Spike1Error):
        spike1.parse_master(bytes(b))


def test_parse_all_partitions_survives_cyclic_ebr(tmp_path):
    import struct as _struct
    iso = synthetic.make_spike1_mbr(tmp_path / "cyclic.iso")
    with open(iso, "r+b") as f:
        # make EBR2's chain link point back at EBR1 (rel 0 from ext base)
        ebr2 = (16384 + 2048) * 512
        f.seek(ebr2 + 462)
        f.write(bytes([0, 0, 0, 0, 0x05, 0, 0, 0])
                + _struct.pack("<II", 0, 2048))
    parts = parse_all_partitions(str(iso))
    # terminates, and each logical appears once
    lbas = [p[2] for p in parts if p[0] >= 4]
    assert len(lbas) == len(set(lbas))


# ---------------------------------------------------------------------------
# write-path helpers, pinned hard
# ---------------------------------------------------------------------------

def test_fit_frames_preserves_content():
    np = pytest.importorskip("numpy")
    a = np.arange(1000, dtype=np.float32)[:, None]
    trimmed = spike1._fit_frames(a, 500)
    # untouched region is identical; only the 5 ms edge fade differs
    assert (trimmed[:280, 0] == a[:280, 0]).all()
    assert trimmed[-1, 0] == 0.0
    padded = spike1._fit_frames(a, 1500)
    assert (padded[:1000, 0] == a[:1000, 0]).all()
    assert (padded[1000:, 0] == 0.0).all()


def test_resample_interpolates_values():
    np = pytest.importorskip("numpy")
    a = np.arange(0, 1000, dtype=np.float32)[:, None]
    up = spike1._resample(a, 22050, 44100)
    # doubling the rate interpolates midpoints of the ramp
    assert abs(float(up[1, 0]) - 0.5) < 1e-3
    assert abs(float(up[100, 0]) - 50.0) < 1e-3


def test_match_level_limiter_engages():
    np = pytest.importorskip("numpy")
    t = np.arange(4410, dtype=np.float32) / 44100.0
    # a peaky quiet source against a loud reference: the RMS gain drives the
    # peaks past the knee, so the limiter must engage without hard clipping
    rep = (300 * np.sin(2 * np.pi * 440 * t))[:, None]
    rep[::100] *= 40.0                          # sparse transients
    orig = (20000 * np.sin(2 * np.pi * 440 * t))[:, None]
    out = spike1._match_level(rep, orig)
    peak = float(np.max(np.abs(out)))
    assert peak <= 32767.0
    assert peak > 0.89 * 32767.0                # limited, not untouched


def test_match_level_extra_db_and_match_off():
    np = pytest.importorskip("numpy")
    t = np.arange(4410, dtype=np.float32) / 44100.0
    rep = (1000 * np.sin(2 * np.pi * 440 * t))[:, None]
    orig = (1000 * np.sin(2 * np.pi * 440 * t))[:, None]

    def rms(x):
        return float(np.sqrt(np.mean(np.square(x))))

    plus6 = spike1._match_level(rep, orig, extra_db=6.0)
    assert abs(rms(plus6) / rms(rep) - 10 ** (6 / 20)) < 0.01
    # match off: only the offset applies, whatever the original's level
    loud_orig = orig * 20
    off = spike1._match_level(rep, loud_orig, extra_db=0.0, match=False)
    assert abs(rms(off) - rms(rep)) < 1.0


def test_match_level_silent_original_keeps_replacement_level():
    np = pytest.importorskip("numpy")
    rep = np.full((1000, 1), 5000.0, dtype=np.float32)
    silent = np.zeros((1000, 1), dtype=np.float32)
    out = spike1._match_level(rep, silent)
    assert abs(float(out[0, 0]) - 5000.0) < 1.0


def test_build_gain_db_clamps(monkeypatch):
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "40")
    assert spike1._build_gain_db() == 12.0
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "-3.5")
    assert spike1._build_gain_db() == -3.5
    monkeypatch.setenv("PAD_STERN_MATCH_GAIN_DB", "junk")
    assert spike1._build_gain_db() == 0.0


def test_parse_wav_stem_rejects_t0_t1():
    # wav_name never emits -t0/-t1; a hand-typed one must not silently remap
    assert spike1.parse_wav_stem("idx0021-t0") is None
    assert spike1.parse_wav_stem("idx0021-t1") is None
    assert spike1.parse_wav_stem("idx0021-t2") == (21, 1)


def test_select_changed_wavs_and_slot_gains(tmp_path):
    import json
    import wave
    from pinball_decryptor.core import checksums
    assets = tmp_path / "assets"
    audio = assets / "audio"
    audio.mkdir(parents=True)

    def wav(name, val):
        with wave.open(str(audio / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(bytes([val]) * 200)

    wav("idx0001.wav", 1)
    wav("idx0002.wav", 2)
    checksums.generate_checksums(str(assets))
    wav("idx0002.wav", 9)               # changed after baseline
    wav("idx0003.wav", 3)               # not in baseline -> treated changed
    (audio / "notes.txt").write_text("not a wav")
    changed = spike1._select_changed_wavs(str(assets), lambda *a, **k: None)
    assert set(changed) == {(2, 0), (3, 0)}

    (assets / ".staged_changes.json").write_text(json.dumps(
        {"audio_levels": {"audio/idx0002.wav": 4.5,
                          "audio/idx0009-t2.wav": -2,
                          "audio/junk.wav": 1}}))
    gains = spike1._slot_gains(str(assets))
    assert gains == {(2, 0): 4.5, (9, 1): -2.0}
