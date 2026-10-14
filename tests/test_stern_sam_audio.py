"""Stern S.A.M. sounds (PAD-582): reading the sound table out of a code
update, decoding every sample, and writing edited WAVs back in place with
the image's checksums moved along.

The tests build a small synthetic SAM image with the real layout (code,
section checksum table, sound table, scripts, IMA ADPCM samples, file
checksum); the format itself was proven on 24 real titles and their
writes in PinMAME by hand (docs/plans/sam_compatibility.md).
"""

import os
import struct
import wave
import zlib

import numpy as np
import pytest

from pinball_decryptor.plugins.pinmame_classic import sam, sam_sound
from pinball_decryptor.plugins.pinmame_classic.sam_games import SAM_GAME_DB
from pinball_decryptor.plugins.stern import sam_audio
from pinball_decryptor.plugins.stern.pipeline import (
    SamExtractPipeline, SamExtractPlusCapturePipeline, SamRevertPipeline,
    SamWritePipeline)

M32 = 0xFFFFFFFF
BASE = 0x1000                # section table; the data area starts at +0x48


def _tone(n, freq, rate, amp=8000):
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16).tolist()


def _script(engine, voice, ptr, extra=b""):
    """``05 <mask> <voices> <u32>`` + optional ops + PLAY + END."""
    args, play = sam_sound.ENGINES[engine]
    assert args[play] == 5
    return (bytes([5, 1, 1]) + struct.pack("<I", 1) + extra
            + bytes([play, voice]) + struct.pack("<I", ptr) + b"\x00")


def make_image(engine="v18", n_sounds=20, trailer=True, kinds=None):
    """``(bytes, [pcm per sample])`` of a synthetic SAM image."""
    kinds = kinds or [1, 2, 3]
    code = bytes((i * 7 + 3) & 0xFF for i in range(BASE))
    table_at = BASE + 0x48
    scripts_at = table_at + 4 * n_sounds * 2          # 2 languages each
    # scripts first, so their size is known before the samples
    samples_at = scripts_at + 64 * n_sounds
    samples_at = (samples_at + 15) & ~15
    pcms, sample_offs, blobs = [], [], b""
    for i in range(n_sounds):
        kind = kinds[i % len(kinds)]
        rate = sam_sound.RATES[kind]
        pcm = _tone(rate // 10 + i * 36 + (i & 1), 300 + 40 * i, rate)
        enc = sam_sound.encode_adpcm(pcm)
        off = samples_at + len(blobs)
        hdr = struct.pack("<I", len(pcm)) + bytes([1, 0, kind, kind])
        blob = hdr + enc
        blob += b"\xff" * (-len(blob) % 4)
        blobs += blob
        pcms.append(pcm)
        sample_offs.append(off)
    scripts = b""
    script_offs = []
    for i in range(n_sounds):
        extra = b""
        if engine in ("v18", "v17") and i == 0:
            extra = bytes([9]) + bytes(15)       # the 15-byte envelope op
        if engine == "v18" and i == 1:
            extra = bytes([17]) + bytes(8)       # v18's own 8-byte op
        # v15 and v14 differ only in ops 11-13: give each its own
        if engine == "v15" and i == 0:
            extra = bytes([11]) + bytes(4)
        if engine == "v14" and i == 0:
            extra = bytes([12]) + bytes(4)
        s = _script(engine, 0, sam_sound.bank_pointer(sample_offs[i]),
                    extra)
        script_offs.append(scripts_at + len(scripts))
        scripts += s + b"\xff" * (64 - len(s))
    table = b"".join(struct.pack("<I", sam_sound.bank_pointer(o)) * 2
                     for o in script_offs)
    body = bytearray(code + bytes(0x48) + table)
    body += b"\xff" * (scripts_at - len(body))
    body += scripts
    body += b"\xff" * (samples_at - len(body))
    body += blobs
    body += b"\x00" * 8 + (b"\x00" * 4 if trailer else b"")
    end1 = len(body) - (4 if trailer else 0) - 1
    a = np.frombuffer(bytes(body), np.uint8)
    secs = [(0, BASE - 1), (table_at, end1)]
    for k, (s, e) in enumerate(secs):
        c = (~int(a[s:e + 1].sum(dtype=np.uint64))) & M32
        struct.pack_into("<3I", body, BASE + 12 * k, s, e, c)
    if trailer:
        n = len(body) - 4
        struct.pack_into("<I", body, n,
                         (~int(np.frombuffer(bytes(body), np.uint8, count=n)
                               .sum(dtype=np.uint64))) & M32)
    return bytes(body), pcms


def _sums_ok(data):
    a = np.frombuffer(data, np.uint8)
    return [((~int(a[S:E + 1].sum(dtype=np.uint64))) & M32) == c
            for _at, S, E, c in sam_sound.section_table(data)]


@pytest.fixture
def sam_file(tmp_path, monkeypatch):
    """A synthetic image registered as Mustang romset 'mt_999h'."""
    data, pcms = make_image()
    crc = zlib.crc32(data) & M32
    db = {k: dict(v) for k, v in SAM_GAME_DB.items()}
    db["mustang"]["romsets"] = dict(
        db["mustang"]["romsets"],
        mt_999h=("mt_999h.bin", crc, len(data),
                 "Mustang Limited Edition (V9.99)"))
    monkeypatch.setattr(sam, "SAM_GAME_DB", db)
    monkeypatch.setitem(sam._BY_CRC, (crc, len(data)), ("mustang", "mt_999h"))
    monkeypatch.setitem(sam._BY_SIZE, len(data), {("mustang", "mt_999h")})
    monkeypatch.setattr(sam, "MIN_BIN_SIZE", 1)
    p = tmp_path / "MT999LE.BIN"
    p.write_bytes(data)
    return str(p), data, pcms


def _log():
    lines = []
    return lines, (lambda msg, level="info": lines.append(msg))


def _run(pipe):
    out = {}
    pipe._done = lambda ok, msg: out.update(ok=ok, msg=msg)
    pipe.run()
    return out


def _read_wav(path):
    with wave.open(path) as w:
        return (w.getframerate(), w.getnchannels(),
                np.frombuffer(w.readframes(w.getnframes()), "<i2"))


def _write_wav(path, pcm, rate, ch=1):
    a = np.asarray(pcm, np.int16)
    if ch == 2:
        a = np.repeat(a, 2)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(a.tobytes())


# ---------------------------------------------------------------------------
# The codec
# ---------------------------------------------------------------------------

def _textbook_ima(raw, count):
    """IMA ADPCM straight from the spec, as the game's decoder does it."""
    steps = sam_sound._STEPS
    idx_tab = [-1, -1, -1, -1, 2, 4, 6, 8]
    pred, si, out = 0, 0, []
    for i in range(count):
        nib = raw[i >> 1] >> 4 if i & 1 else raw[i >> 1] & 15
        step = steps[si]
        diff = step >> 3
        if nib & 4:
            diff += step
        if nib & 2:
            diff += step >> 1
        if nib & 1:
            diff += step >> 2
        pred = pred - diff if nib & 8 else pred + diff
        pred = max(-32768, min(32767, pred))
        si = max(0, min(88, si + idx_tab[nib & 7]))
        out.append(pred)
    return out


def test_decoder_matches_the_textbook():
    rng = np.random.default_rng(582)
    raw = rng.integers(0, 256, 3000, dtype=np.uint8).tobytes()
    assert list(sam_sound.decode_adpcm(raw, 5999)) == \
        _textbook_ima(raw, 5999)


def test_encoder_round_trips_close():
    pcm = _tone(24000, 440, 24000, amp=12000)
    enc = sam_sound.encode_adpcm(pcm)
    assert len(enc) == 12000
    dec = np.asarray(sam_sound.decode_adpcm(enc, len(pcm)), float)
    err = np.asarray(pcm, float) - dec
    snr = 10 * np.log10(np.sum(np.square(pcm, dtype=float))
                        / np.sum(err ** 2))
    assert snr > 25


# ---------------------------------------------------------------------------
# Reading the sound table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine", list(sam_sound.ENGINES))
def test_read_bank_every_engine(engine):
    data, pcms = make_image(engine)
    bank = sam_sound.read_bank(data)
    assert bank.engine == engine
    assert bank.table == BASE + 0x48 and bank.entries == 40
    assert [s.count for s in bank.samples] == [len(p) for p in pcms]
    assert [s.rate for s in bank.samples][:3] == [24000, 12000, 8000]
    # each sample is played by its sound's two language entries
    assert bank.played_by[bank.samples[3].offset] == [6, 7]
    for s, p in zip(bank.samples, pcms):
        assert list(sam_sound.decode(data, s)) == \
            list(sam_sound.decode_adpcm(sam_sound.encode_adpcm(p), len(p)))


def test_read_bank_refuses_a_file_that_isnt_sam():
    with pytest.raises(sam_sound.SamSoundError):
        sam_sound.read_bank(bytes(range(256)) * 4096)


def test_read_bank_refuses_unparseable_scripts():
    data, _ = make_image()
    bank = sam_sound.read_bank(data)
    bad = bytearray(data)
    first = sam_sound.file_offset(struct.unpack_from("<I", data,
                                                     bank.table)[0])
    bad[first + 7] = 0x40          # no engine has opcode 0x40
    with pytest.raises(sam_sound.SamSoundError, match="don't parse"):
        sam_sound.read_bank(bytes(bad))


def test_checksums_are_found():
    data, _ = make_image()
    assert sam_sound.has_trailer(data)
    secs = sam_sound.section_table(data)
    assert [(S, E) for _a, S, E, _c in secs][0] == (0, BASE - 1)
    assert all(_sums_ok(data))
    data2, _ = make_image(trailer=False)
    assert not sam_sound.has_trailer(data2)


# ---------------------------------------------------------------------------
# replace + checksums
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("trailer", [True, False])
def test_replace_moves_the_checksums(trailer):
    data, pcms = make_image(trailer=trailer)
    bank = sam_sound.read_bank(data)
    img = bytearray(data)
    changes = []
    for s in bank.samples[2:5]:
        new = _tone(s.count + 500, 1000, s.rate)        # longer: cut
        d = sam_sound.replace(img, s, new)
        changes.append((s.data_offset, s.data_offset + s.data_size, d))
    sam_sound.fix_checksums(img, changes, trailer)
    out = bytes(img)
    assert len(out) == len(data)
    assert all(_sums_ok(out))
    assert sam_sound.has_trailer(out) == trailer
    s = bank.samples[3]
    want = sam_sound.decode_adpcm(
        sam_sound.encode_adpcm(_tone(s.count + 500, 1000, s.rate)[:s.count]),
        s.count)
    assert list(sam_sound.decode(out, s)) == list(want)
    # nothing else moved: same table, same samples
    assert sam_sound.read_bank(out).samples == bank.samples


def test_replace_keeps_a_shipped_files_checksum_offsets():
    # Some shipped files' section sums don't match their bytes; a write
    # keeps whatever offset was there rather than "fixing" it.
    data, _ = make_image()
    img = bytearray(data)
    at = sam_sound.section_table(data)[1][0]
    struct.pack_into("<I", img, at + 8,
                     (struct.unpack_from("<I", img, at + 8)[0] + 77) & M32)
    s = sam_sound.read_bank(data).samples[0]
    d = sam_sound.replace(img, s, _tone(s.count, 700, s.rate))
    sam_sound.fix_checksums(img, [(s.data_offset,
                                   s.data_offset + s.data_size, d)], True)
    a = np.frombuffer(bytes(img), np.uint8)
    _a, S, E, c = sam_sound.section_table(bytes(img))[1]
    assert ((~int(a[S:E + 1].sum(dtype=np.uint64))) & M32) == \
        (c - 77) & M32
    assert sam_sound.has_trailer(bytes(img))


def test_replace_odd_count_keeps_the_spare_nibble():
    data, _ = make_image()
    bank = sam_sound.read_bank(data)
    s = next(x for x in bank.samples if x.count & 1)
    img = bytearray(data)
    last = s.data_offset + s.data_size - 1
    sam_sound.replace(img, s, _tone(s.count, 500, s.rate))
    assert img[last] >> 4 == data[last] >> 4


# ---------------------------------------------------------------------------
# The Stern SAM era: Extract / Write / Revert
# ---------------------------------------------------------------------------

def test_extract_pipeline_writes_every_sample(sam_file, tmp_path):
    path, data, pcms = sam_file
    out_dir = str(tmp_path / "proj")
    res = _run(SamExtractPipeline(path, out_dir, lambda *a, **k: None,
                                  lambda i: None, lambda *a: None, None))
    assert res["ok"], res
    assert "Extracted 20 SAM sound(s)" in res["msg"]
    names = sorted(os.listdir(os.path.join(out_dir, "audio")))
    assert names[0] == "idx0000.wav" and len(names) == 20
    rate, ch, a = _read_wav(os.path.join(out_dir, "audio", "idx0001.wav"))
    assert (rate, ch, len(a)) == (12000, 1, len(pcms[1]))
    assert os.path.isfile(os.path.join(out_dir, ".checksums.md5"))


def test_extract_duration_names(sam_file, tmp_path):
    path, _data, pcms = sam_file
    out_dir = str(tmp_path / "proj")
    sam_audio.extract_all(path, out_dir, duration_names=True)
    names = sorted(os.listdir(os.path.join(out_dir, "audio")))
    ms = round(len(pcms[0]) * 1000 / 24000)
    assert names[0] == "00m00s%03d - idx0000.wav" % ms
    assert sam_audio.parse_wav_stem(names[0][:-4]) == 0
    assert sam_audio.parse_wav_stem("Super jackpot - idx0012") == 12
    assert sam_audio.parse_wav_stem("music") is None


def _extract(path, tmp_path):
    out_dir = str(tmp_path / "proj")
    res = _run(SamExtractPipeline(path, out_dir, lambda *a, **k: None,
                                  lambda i: None, lambda *a: None, None))
    assert res["ok"], res
    return out_dir


def test_write_patches_the_edited_sound(sam_file, tmp_path):
    path, data, pcms = sam_file
    out_dir = _extract(path, tmp_path)
    bank = sam_sound.read_bank(data)
    s = bank.samples[4]
    # a stereo 44.1 kHz replacement, longer than the slot
    wav = os.path.join(out_dir, "audio", "idx0004.wav")
    _write_wav(wav, _tone(int(44100 * (s.seconds + 0.5)), 1000, 44100), 44100,
               ch=2)
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 1 replaced sound(s)" in res["msg"]
    built = open(out, "rb").read()
    assert len(built) == len(data)
    assert all(_sums_ok(built)) and sam_sound.has_trailer(built)
    # only that sample's bytes and the checksums changed
    diff = [i for i in range(len(data)) if built[i] != data[i]]
    secs = sam_sound.section_table(data)
    allowed = set(range(s.data_offset, s.data_offset + s.data_size))
    allowed |= {at + 8 + k for at, *_ in secs for k in range(4)}
    allowed |= set(range(len(data) - 4, len(data)))
    assert diff and set(diff) <= allowed
    # what the game will play is a 1 kHz tone at the slot's own rate
    got = np.asarray(sam_sound.decode(built, s), float)
    spec = np.abs(np.fft.rfft(got))
    peak = np.fft.rfftfreq(len(got), 1 / s.rate)[int(np.argmax(spec))]
    assert abs(peak - 1000) < 30
    # loudness-matched to the original (same RMS within a few dB)
    orig = np.asarray(sam_sound.decode(data, s), float)
    ratio = np.sqrt(np.mean(got ** 2)) / np.sqrt(np.mean(orig ** 2))
    assert 0.6 < ratio < 1.6


def test_write_with_nothing_changed_is_a_copy(sam_file, tmp_path):
    path, data, _ = sam_file
    out_dir = _extract(path, tmp_path)
    out = str(tmp_path / "built.bin")
    res = _run(SamWritePipeline(path, out_dir, out, lambda *a, **k: None,
                                lambda i: None, lambda *a: None, None))
    assert res["ok"] and "No changes found" in res["msg"]
    assert open(out, "rb").read() == data


def test_write_skips_a_bad_wav_and_keeps_the_rest(sam_file, tmp_path):
    path, data, _ = sam_file
    out_dir = _extract(path, tmp_path)
    s = sam_sound.read_bank(data).samples[2]
    _write_wav(os.path.join(out_dir, "audio", "idx0002.wav"),
               _tone(s.count, 800, s.rate), s.rate)
    with open(os.path.join(out_dir, "audio", "idx0003.wav"), "wb") as f:
        f.write(b"not a wav")
    with open(os.path.join(out_dir, "audio", "idx0099.wav"), "wb") as f:
        f.write(b"no such sound")
    out = str(tmp_path / "built.bin")
    lines, log = _log()
    res = _run(SamWritePipeline(path, out_dir, out, log, lambda i: None,
                                lambda *a: None, None))
    assert res["ok"], res
    assert "Wrote 1 replaced sound(s) (2 skipped" in res["msg"]
    assert any("idx0099.wav: no such sound" in x for x in lines)
    assert all(_sums_ok(open(out, "rb").read()))


def test_write_refuses_a_file_that_isnt_sam(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00" * 1024)
    res = _run(SamWritePipeline(str(p), str(tmp_path), str(tmp_path / "o"),
                                lambda *a, **k: None, lambda i: None,
                                lambda *a: None, None))
    assert not res["ok"] and "not a Stern SAM game file" in res["msg"]


def test_write_cancel_leaves_no_output(sam_file, tmp_path):
    path, data, _ = sam_file
    out_dir = _extract(path, tmp_path)
    s = sam_sound.read_bank(data).samples[0]
    _write_wav(os.path.join(out_dir, "audio", "idx0000.wav"),
               _tone(s.count, 800, s.rate), s.rate)
    out = tmp_path / "built.bin"
    with pytest.raises(sam_audio.SamAudioCancelled):
        sam_audio.write_image(path, out_dir, str(out), cancel=lambda: True)
    assert not out.exists()
    assert not (tmp_path / "built.bin.part").exists()


def test_revert_restores_the_original(sam_file, tmp_path):
    path, data, pcms = sam_file
    out_dir = _extract(path, tmp_path)
    wav = os.path.join(out_dir, "audio", "idx0005.wav")
    before = open(wav, "rb").read()
    _write_wav(wav, [0] * 100, 8000)
    res = _run(SamRevertPipeline(path, out_dir, ["audio/idx0005.wav",
                                                 "audio/idx0777.wav"],
                                 lambda *a, **k: None, lambda i: None,
                                 lambda *a: None, None))
    assert res["ok"] and "Restored 1 original file(s)" in res["msg"]
    assert "1 could not be restored" in res["msg"]
    assert open(wav, "rb").read() == before


# ---------------------------------------------------------------------------
# The Stern card's SAM era surface
# ---------------------------------------------------------------------------

@pytest.fixture
def stern(manufacturers_by_key):
    s = manufacturers_by_key["stern"]
    yield s
    s.set_era("")


def test_sam_era_surface(stern, sam_file, tmp_path):
    path, _data, _ = sam_file
    g = stern.detect(path)
    assert g.era == "sam"
    stern.set_era("sam")
    caps = stern.capabilities
    assert caps.extract and caps.capture and caps.write
    assert caps.replace_audio and caps.audio_level_offset and caps.modpack
    assert stern.extract_phases == SamExtractPipeline.PHASES
    assert stern.write_phases == SamWritePipeline.PHASES
    assert stern.combined_phases == SamExtractPlusCapturePipeline.PHASES
    assert stern.write_output_ext() == ".bin"
    assert stern.audio_forces_length_match()
    assert "ADPCM" in stern.audio_length_note()
    noop = (lambda *a, **k: None, lambda *a: None, lambda *a, **k: None,
            lambda *a: None)
    assert isinstance(stern.make_extract_pipeline(path, str(tmp_path), *noop),
                      SamExtractPipeline)
    assert isinstance(stern.make_write_pipeline(path, str(tmp_path), "o.bin",
                                                *noop), SamWritePipeline)
    assert isinstance(stern.make_revert_pipeline(path, str(tmp_path), [],
                                                 *noop), SamRevertPipeline)
    both = stern.make_capture_pipeline(path, str(tmp_path), *noop,
                                       duration_seconds=30,
                                       also_run_static=True)
    assert isinstance(both, SamExtractPlusCapturePipeline)
    from pinball_decryptor.plugins.pinmame_classic import capture
    only = stern.make_capture_pipeline(path, str(tmp_path), *noop,
                                       duration_seconds=30,
                                       also_run_static=False)
    assert isinstance(only, capture.SamCapturePipeline)
    # Whitestar keeps its capture-only surface
    stern.set_era("whitestar")
    assert not stern.capabilities.write and not stern.capabilities.extract


def test_extract_plus_capture_runs_the_sounds_first(stern, sam_file,
                                                    tmp_path, monkeypatch):
    path, _data, _ = sam_file
    from pinball_decryptor.plugins.pinmame_classic import capture
    seen = {}

    def fake_run(self):
        seen["audio"] = sorted(os.listdir(os.path.join(self.output_dir,
                                                       "audio")))
        self._done(True, "captured")

    monkeypatch.setattr(capture.SamCapturePipeline, "run", fake_run)
    out_dir = str(tmp_path / "proj")
    pipe = SamExtractPlusCapturePipeline(
        path, out_dir, lambda *a, **k: None, lambda i: None,
        lambda *a: None, None, duration_seconds=30)
    res = _run(pipe)
    assert res["ok"], res
    assert len(seen["audio"]) == 20
    assert res["msg"].startswith("Sounds: 20 WAV(s)")
    assert res["msg"].endswith("captured")
