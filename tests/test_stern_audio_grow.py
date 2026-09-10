"""Delivering a replacement callout LONGER than the sound it replaces.

The card's sound bank records where every sound starts and how long it is, so a
sound cannot be made longer in place — every later sound's offset would be
stranded.  ``plans/spike2_longer_audio.md`` proved the way round in the PC
emulator: append a copy of the record pointing at a body past the old end of
the file, leave every stock record and body untouched, and deliver the bank as
one whole-file copy.

What is under test here is the CARD side — the classification, the gate, and
the delivery — with the emulator work stubbed at its own seams:

* a clip longer than its slot is spotted from its WAV header, before the encode
  cache can replay a trimmed body from the last build;
* the gate refuses a direct-SD write, a host that can't grow ext4 files, the
  one firmware build whose sounds can't be driven past their length, and the
  default-off flag — each with a reason in the log, never an error;
* a grown build produces the image grow job (before the firmware's), no
  in-place image writes at all, a ``.sidx`` record carrying the staged file's
  size and digests, and a plan that owns the staged file until the copy;
* the retired record is collapsed away so the sound keeps its own index.
"""

import io
import os
import struct
import wave

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.core import ext4_grow                      # noqa: E402
from pinball_decryptor.plugins.stern import engine, sidx          # noqa: E402
from pinball_decryptor.plugins.stern.explorer import S_IFREG      # noqa: E402
from pinball_decryptor.plugins.stern.spike2.emulator import (     # noqa: E402
    collapse_shadowed)
from tests.test_stern_valpatch import _stub_sidx                  # noqa: E402

IMG_PATH = "/spk/default/data/image.bin"
FW_PATH = "/spk/default/game"
SIDX_PATH = "/spk/index/default.sidx"
BLOCK = 200


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _wav(path, seconds, rate=44100, chan=1):
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chan)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n * chan)
    return str(path)


def _params(n=4, length=44100):
    """A stock params table: n mono sounds, packed back to back."""
    out, off = [], 0x1000
    for i in range(n):
        out.append({"idx": i, "body_off": off, "length": length, "chan": 1,
                    "scale": i % 32, "pred16": 100 + i, "seed_a": i,
                    "stride": 1, "band0_keyoff_rel": 0,
                    "identity": bytes([i]) * 16, "key0": i})
        off += 2 * length
    return out


def _capture():
    msgs = []
    return msgs, lambda m, lvl="info": msgs.append((lvl, m))


def _said(msgs, needle):
    return [m for _l, m in msgs if needle in m]


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def test_gate_is_off_unless_asked_for(monkeypatch):
    """No machine has booted a grown bank, so a build must never produce one
    unless the user asked for it by name."""
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    ok, why = engine._audio_grow_gate(False)
    assert not ok
    assert "no machine has booted" in why


def test_gate_refuses_direct_sd_and_a_host_that_cannot_grow(monkeypatch):
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    ok, why = engine._audio_grow_gate(True)
    assert not ok and "direct-SD" in why

    monkeypatch.setattr(ext4_grow, "available", lambda: (False, "no loop dev"))
    ok, why = engine._audio_grow_gate(False)
    assert not ok and "no loop dev" in why


def test_gate_opens_when_everything_is_in_place(monkeypatch):
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    ok, why = engine._audio_grow_gate(False)
    assert ok and why == ""


def test_gate_refuses_the_build_whose_sounds_cannot_be_lengthened(monkeypatch,
                                                                  tmp_path):
    """The validated build rebuilds each codec object from its record rather
    than replaying a raw one, so its sounds can't be driven past their stock
    range — growing the bank there would produce a card that plays the clip
    trimmed anyway."""
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    monkeypatch.setattr(engine, "_audio_grow_gate",
                        engine._audio_grow_gate)      # keep the real one
    monkeypatch.setattr(EM, "firmware_build_supported", lambda p: True)
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF")
    ok, why = engine._audio_grow_gate(False, str(gr))
    assert not ok and "can't be driven past" in why


# --------------------------------------------------------------------------
# classifying the edits
# --------------------------------------------------------------------------
def test_a_clip_longer_than_its_slot_is_classified_as_a_grow(tmp_path):
    params = _params(length=44100)                 # 1.0 s slots, minus a block
    byidx = {p["idx"]: p for p in params}
    short = _wav(tmp_path / "short.wav", 0.5)
    long_ = _wav(tmp_path / "long.wav", 2.0)
    fits, grows = engine._classify_audio_edits(
        byidx, {0: short, 1: long_}, str(tmp_path))
    assert set(fits) == {0}
    assert set(grows) == {1}
    room, want = grows[1]
    assert room == 44100 - BLOCK
    assert want == 2 * 44100


def test_a_clip_at_a_different_sample_rate_is_measured_in_card_samples(tmp_path):
    """The encoder resamples to the card's rate, so the comparison has to be
    made there: 1.5 s at 22050 Hz is 1.5 s of card audio, not 0.75 s."""
    params = _params(length=44100)
    byidx = {p["idx"]: p for p in params}
    w = _wav(tmp_path / "half_rate.wav", 1.5, rate=22050)
    _fits, grows = engine._classify_audio_edits(byidx, {0: w}, str(tmp_path))
    assert grows[0][1] == int(1.5 * 44100)


def test_an_unreadable_or_unknown_clip_is_left_to_the_encoder(tmp_path):
    params = _params()
    byidx = {p["idx"]: p for p in params}
    junk = tmp_path / "not.wav"
    junk.write_bytes(b"nope")
    fits, grows = engine._classify_audio_edits(
        byidx, {0: str(junk), 99: str(junk)}, str(tmp_path))
    assert set(fits) == {0, 99} and not grows


# --------------------------------------------------------------------------
# collapsing the retired record
# --------------------------------------------------------------------------
def test_collapse_keeps_the_appended_record_under_the_original_index():
    rows = [{"idx": 0, "identity": b"a", "body_off": 10, "length": 100},
            {"idx": 1, "identity": b"b", "body_off": 20, "length": 100},
            {"idx": 2, "identity": b"a", "body_off": 99, "length": 500}]
    out = collapse_shadowed(rows)
    assert [r["idx"] for r in out] == [0, 1]
    assert out[0]["body_off"] == 99 and out[0]["length"] == 500
    assert out[0]["shadows"] == 2
    assert "shadows" not in out[1]


def test_collapse_leaves_a_stock_card_alone():
    rows = _params(5)
    assert collapse_shadowed(rows) is rows


def test_collapse_survives_a_row_whose_record_could_not_be_read():
    rows = [{"idx": 0, "identity": None}, {"idx": 1, "identity": None}]
    assert len(collapse_shadowed(rows)) == 2


# --------------------------------------------------------------------------
# small helpers the delivery depends on
# --------------------------------------------------------------------------
def test_only_the_last_appended_body_is_exempt_from_the_chain():
    """The firmware decodes the record array as one forward chain, so a
    record's bytes set the parameters of every record AFTER it.  Only the last
    appended record has nothing after it.

    Growing two sounds in one build and exempting BOTH from the
    master-directory restore shifted the second one's codec parameters on a
    real card (Godzilla Pro 1.15, idx 597 and idx 1047: scale 18 -> 7,
    predictor 39237 -> 11536) and the integrity check stopped the write."""
    from pinball_decryptor.plugins.stern.spike2.masterdir import Placement
    places = [Placement(597, 2534, 0x8000, 1000, 0x1000),
              Placement(1047, 2535, 0x9010, 1000, 0x1000)]
    patches = {0x8000: b"", 0x9010: b"", 0x1000: b""}
    assert engine._appended_body_offsets(patches, places) == {0x8000, 0x9010}
    assert engine._appended_body_offsets(
        patches, places, last_only=True) == {0x9010}


def test_appended_body_offsets_covers_the_encoder_window():
    """The encoder writes from a word or two BELOW a sound's body offset, so
    the patch key is not always the body offset itself."""
    Placement = engine.masterdir.Placement if hasattr(engine, "masterdir") \
        else None
    from pinball_decryptor.plugins.stern.spike2.masterdir import Placement
    places = [Placement(3, 9, 0x8000, 1000, 4096)]
    patches = {0x1000: b"", 0x7ffe: b"", 0x8000: b"", 0x8ffc: b"",
               0x9010: b""}
    got = engine._appended_body_offsets(patches, places)
    assert got == {0x7ffe, 0x8000, 0x8ffc}
    assert engine._appended_body_offsets(patches, None) == set()


def test_image_identity_changes_with_the_tail(tmp_path):
    """The params cache and the encode cache both key on this; a grown bank
    differs from its stock self only in one header word and the record array
    at the very end."""
    p = tmp_path / "image.bin"
    p.write_bytes(b"\x00" * (12 << 20))
    a = engine._image_identity(str(p))
    with open(p, "r+b") as f:
        f.seek(-16, 2)
        f.write(b"\xff" * 16)
    assert engine._image_identity(str(p)) != a


def test_fingerprint_sees_a_change_in_the_record_array(tmp_path):
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF" + b"\x00" * 1000)
    img = tmp_path / "image.bin"
    img.write_bytes(b"\x00" * (1 << 20))
    a = engine._fingerprint(str(gr), str(img))
    with open(img, "r+b") as f:
        f.seek(-8, 2)
        f.write(b"\x01" * 8)
    assert engine._fingerprint(str(gr), str(img)) != a


# --------------------------------------------------------------------------
# delivery: the whole write, with the emulator work stubbed at its seams
# --------------------------------------------------------------------------
class _CardReader:
    """The slice of Ext4Reader this path touches: a sound bank, a firmware and
    a .sidx manifest, each mapped 1:1 onto a flat disk."""

    base = 0
    IMG_DISK, FW_DISK, SIDX_DISK = 0x100000, 0x10000, 0x80000

    def __init__(self, img, elf, sidx_blob):
        def node(data, disk, ib):
            return {"i_block": ib, "size": len(data), "mode": S_IFREG,
                    "_data": data, "_disk": disk}
        self.img_node = node(img, self.IMG_DISK, b"\x01" * 60)
        self.fw_node = node(elf, self.FW_DISK, b"\x02" * 60)
        self.sidx_node = node(sidx_blob, self.SIDX_DISK, b"\x03" * 60)

    def read_file_bytes(self, node):
        return node["_data"]

    def disk_ranges(self, node, off, length):
        if off + length > node["size"]:
            raise ValueError("past the end of the file")
        return [(node["_disk"] + off, length)]

    def iter_regular_files(self, min_size=1, max_depth=20):
        yield IMG_PATH, 3, self.img_node
        yield FW_PATH, 4, self.fw_node
        yield SIDX_PATH, 5, self.sidx_node

    def extract_file(self, node, out_path, progress=None):
        with open(out_path, "wb") as f:
            f.write(node["_data"])


def _grow_card(monkeypatch, tmp_path, params, grown_rows=None, places=None):
    """Point _compute_patches at a fake card and stub every emulator seam.

    What is left real is exactly what this file is about: the classification,
    the gate, and the delivery."""
    img = b"\x00" * 0x40000
    elf = b"\x7fELF" + b"\x00" * 0x1000
    blob = _stub_sidx([IMG_PATH.lstrip("/"), FW_PATH.lstrip("/"),
                       SIDX_PATH.lstrip("/")])
    reader = _CardReader(img, elf, blob)

    gr_path = tmp_path / "work_game_real"
    gr_path.write_bytes(elf)
    img_path = tmp_path / "work_image.bin"
    img_path.write_bytes(img)

    def extract(disk_f, parts, work, log, prog=None):
        # The real one writes into ``work``; mirror that so the grow's
        # os.replace has something of its own to move.
        w_gr = os.path.join(work, "game_real")
        w_img = os.path.join(work, "image.bin")
        with open(w_gr, "wb") as f:
            f.write(elf)
        with open(w_img, "wb") as f:
            f.write(img)
        return w_gr, w_img, reader, reader.fw_node, reader.img_node

    staged_seen = {}

    def stage(gr, ip, grow_work, byidx, grows, log):
        from pinball_decryptor.plugins.stern.spike2.masterdir import Placement
        out = os.path.join(grow_work, "image.bin")
        os.replace(ip, out)
        pls = []
        off = 0x40000
        for i, idx in enumerate(sorted(grows)):
            _room, want = grows[idx]
            n = 2 * (want + BLOCK)
            pls.append(Placement(idx, len(byidx) + i, off, want + BLOCK, n))
            off += n + 16
        with open(out, "r+b") as f:
            f.truncate(off)
        staged_seen["path"] = out
        staged_seen["places"] = pls
        return out, pls

    def derive(gr, staged, params_stock, log, progress=None):
        return (grown_rows if grown_rows is not None else params_stock), None

    # The play tables name every sound by its key's first word; the re-point
    # itself is an emulator step and is only recorded here.
    def sites(gr, img, log=None):
        return [engine._DescSite(100 + p["idx"], 0x300 + 8 * p["idx"],
                                 b"\x00" * 8, struct.pack("<II", p["key0"], 0),
                                 0x200 + 4 * p["idx"], b"\x00" * 4, 4000)
                for p in params if p.get("key0") is not None]

    repointed = {}

    def repoint(gr, staged, prm, st, log):
        repointed["path"] = staged
        repointed["params"] = prm
        repointed["sites"] = st
        return {}

    staged_seen["repointed"] = repointed
    monkeypatch.setattr(engine, "_descriptor_sites", sites)
    monkeypatch.setattr(engine, "_repoint_descriptors", repoint)
    monkeypatch.setattr(engine, "_locate",
                        lambda f, p: (reader, reader.fw_node, reader.img_node))
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 1 << 30)])
    monkeypatch.setattr(engine, "_extract_inputs", extract)
    # _compute_patches imports this one from the emulator module at call time.
    from pinball_decryptor.plugins.stern.spike2 import emulator as _EM
    monkeypatch.setattr(_EM, "audio_decode_supported", lambda p: True)
    monkeypatch.setattr(engine, "_params_for",
                        lambda gr, img, log, prog: params)
    monkeypatch.setattr(engine, "_stage_grown_image", stage)
    monkeypatch.setattr(engine, "_derive_grown", derive)
    monkeypatch.setattr(engine, "_restore_masterdir_consumed",
                        lambda *a, **k: a[2])
    monkeypatch.setattr(engine, "_assert_param_integrity",
                        lambda *a, **k: None)
    monkeypatch.setattr(engine, "_verify_final_patches", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_audit_audio_patches", lambda *a, **k: 0)
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    monkeypatch.setenv("PAD_STERN_BLIP_FREE", "0")
    return reader, staged_seen


def _edits(tmp_path, seconds):
    """An assets folder whose idx0000.wav is *seconds* long and changed."""
    assets = tmp_path / "assets"
    (assets / "audio").mkdir(parents=True)
    wav = _wav(assets / "audio" / "idx0000.wav", seconds)
    return assets, wav


def _run(monkeypatch, assets, params, encode_off, log, dest_is_device=False):
    def _fake_encode(gr, img, prm, ed, np, lg, pr, cx, **k):
        return {encode_off: b"\xaa" * 64}, []
    monkeypatch.setattr(engine, "_encode_cat0_sounds", _fake_encode)
    monkeypatch.setattr(engine, "_select_changed_idx_wavs",
                        lambda a, b: {0: "audio/idx0000.wav"})
    return engine._compute_patches(
        io.BytesIO(b""), [], str(assets), log=log, progress=None,
        cancel=lambda: False, dest_is_device=dest_is_device)


@pytest.fixture
def _grow_on(monkeypatch):
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")


def test_a_longer_clip_produces_a_whole_file_copy_and_no_in_place_writes(
        monkeypatch, tmp_path, _grow_on):
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True,
                    shadows=4)
    reader, staged = _grow_card(monkeypatch, tmp_path, params, grown_rows=grown)
    assets, _wavp = _edits(tmp_path, 2.0)
    msgs, log = _capture()

    writes, counts, plan, _mode, _vp = _run(
        monkeypatch, assets, params, 0x40000, log)

    # the bank went on the card whole, and nothing was patched inside it
    jobs = plan["jobs"]
    assert (IMG_PATH.lstrip("/"), staged["path"]) in jobs
    img_lo = _CardReader.IMG_DISK
    assert not [d for d, _b in writes
                if img_lo <= d < img_lo + 0x40000], "in-place image write"
    # the manifest describes the staged file, at its new size
    rec = _sidx_size(reader, writes, IMG_PATH)
    assert rec == os.path.getsize(staged["path"])
    # and the plan owns the staged file until the caller has copied it
    assert plan["cleanup"] and os.path.dirname(staged["path"]) == plan["cleanup"]
    assert counts[0] == 1
    assert _said(msgs, "the sound bank grows to keep it whole")


def test_the_bank_is_queued_before_the_firmware(monkeypatch, tmp_path,
                                                _grow_on):
    """Grow jobs fail from the end and the firmware is the sentinel the write
    reads a partial run by, so the bank must never be last."""
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True,
                    shadows=4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params,
                                 grown_rows=grown)
    # after _grow_card, which pins the OFF default the other cases want
    monkeypatch.setenv("PAD_STERN_BLIP_FREE", "1")
    monkeypatch.delenv("PAD_STERN_SKIP_KEYPATCH", raising=False)
    monkeypatch.setattr(engine, "_pathA_preflight", lambda d: None)
    fw = tmp_path / "patched_game_real"
    fw.write_bytes(b"\x7fELF" + b"\x00" * 0x2000)
    monkeypatch.setattr(engine, "_build_derive_redirect_cave",
                        lambda *a, **k: (str(fw), 0x2004))
    assets, _w = _edits(tmp_path, 2.0)
    _msgs, log = _capture()
    _writes, _c, plan, _m, _v = _run(monkeypatch, assets, params, 0x40000, log)
    rels = [r for r, _s in plan["jobs"]]
    assert rels.index(IMG_PATH.lstrip("/")) < rels.index(FW_PATH.lstrip("/"))
    assert plan["audio_job"] == rels.index(IMG_PATH.lstrip("/"))


@pytest.mark.parametrize("device,flag,needle", [
    (True, "1", "direct-SD"),
    (False, None, "no machine has booted"),
])
def test_a_closed_gate_trims_and_says_why(monkeypatch, tmp_path, device, flag,
                                          needle):
    """A refused grow is never a build failure: the clip is fitted exactly as
    it is today and the log carries one line naming the reason."""
    if flag is None:
        monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    else:
        monkeypatch.setenv("PAD_STERN_AUDIO_GROW", flag)
    params = _params(4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params)
    assets, _w = _edits(tmp_path, 2.0)
    msgs, log = _capture()
    writes, counts, plan, _m, _v = _run(
        monkeypatch, assets, params, params[0]["body_off"], log,
        dest_is_device=device)
    assert "path" not in staged, "the bank must not have been staged"
    assert plan is None or not [r for r, _s in plan["jobs"]
                                if r == IMG_PATH.lstrip("/")]
    trimmed = _said(msgs, "are trimmed to fit")
    assert len(trimmed) == 1 and needle in trimmed[0]
    # and the sound still landed, in place, exactly as before
    img_lo = _CardReader.IMG_DISK
    assert [d for d, _b in writes if img_lo <= d < img_lo + 0x40000]
    assert counts[0] == 1


def _sidx_size(reader, writes, path):
    blob = reader.sidx_node["_data"]
    base = reader.SIDX_DISK
    buf = bytearray(blob)
    for d, b in writes:
        if base <= d < base + len(blob):
            buf[d - base:d - base + len(b)] = b
    recs, _crc, fmt = sidx.parse_records(bytes(buf))
    po = recs[path.lstrip("/")]
    packfmt, o1, _o2 = sidx._SIZE_FIELDS[fmt]
    return struct.unpack_from(packfmt, buf, po + o1)[0]


# --------------------------------------------------------------------------
# the GUI option
# --------------------------------------------------------------------------
def test_the_gui_option_is_the_only_thing_that_opens_the_gate(monkeypatch):
    """Unset must mean the build every headless caller and every spawned encode
    worker already makes — they inherit os.environ without ever seeing the
    dialog, so whatever "unset" means is what they build."""
    from pinball_decryptor.app import App
    from pinball_decryptor.gui.main_window import MainWindow

    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, "test"))
    app = object.__new__(App)

    App._apply_audio_advanced_env(app, {})                 # defaults
    assert "PAD_STERN_AUDIO_GROW" not in os.environ
    assert engine._audio_grow_gate(False)[0] is False

    App._apply_audio_advanced_env(app, {"audio_grow": True})
    assert os.environ["PAD_STERN_AUDIO_GROW"] == "1"
    assert engine._audio_grow_gate(False)[0] is True

    App._apply_audio_advanced_env(app, {"audio_grow": False})
    assert "PAD_STERN_AUDIO_GROW" not in os.environ

    # Both defaults tables agree, so the dialog and the engine can't drift.
    assert App._AUDIO_ADV_DEFAULTS["audio_grow"] is False
    assert MainWindow._AUDIO_ADV_DEFAULTS["audio_grow"] is False
