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
import re
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
    """Growing changes the build (an image build), so it is opt-in: a build
    must never produce a grown bank unless the user asked for it by name."""
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    ok, why = engine._audio_grow_gate(False)
    assert not ok
    assert "longer replacements are off" in why


def test_the_off_reason_names_the_option_the_dialog_really_has(monkeypatch):
    """Off is the default, so this is the reason nearly every trim gives, and
    it is the only place a Write tells the user the option exists (PAD-174:
    a whole song cut to its slot's 38 s loop, found by extracting the card).
    It quotes the checkbox, so the quote has to be the checkbox's text."""
    import inspect

    from pinball_decryptor.gui.main_window import MainWindow
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    _ok, why = engine._audio_grow_gate(False)
    label = "Allow replacements longer than the original"
    assert '"%s"' % label in why and "Advanced" in why
    src = inspect.getsource(MainWindow._open_audio_advanced)
    assert 'text="%s' % label in src


def test_the_trim_notice_names_every_clip_biggest_cut_first():
    """A count alone told nobody WHICH replacement lost its tail."""
    grows = {7: (44100, 44100 + 4410),               # a callout 0.1 s long
             1145: (1692642, 5078244),               # a song on a 38 s loop
             13: (69300, 138600)}
    msg, level = engine._trimmed_notice(grows, "because")
    assert msg.startswith("3 replacement(s) run past their original sound's "
                          "length and are trimmed to fit: because.")
    assert "idx 1145 (115.15 s cut to 38.38 s)" in msg
    assert (msg.index("idx 1145") < msg.index("idx 13 ")
            < msg.index("idx 7 "))
    assert level == "warning"


def test_a_callout_that_runs_a_little_long_stays_a_note():
    """The trim exists for this case; a warning on every build would teach
    users to ignore the one that matters."""
    msg, level = engine._trimmed_notice({7: (44100, 44100 + 4410)}, "off")
    assert "idx 7 (1.10 s cut to 1.00 s)" in msg
    assert level == "info"


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

    def repoint(gr, staged, prm, st, log, templates=None):
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
        return ({encode_off: b"\xaa" * 64} if ed else {}), []

    # item 150 follow-up: a grown (appended) sound is encoded along the firmware's chain
    def _fake_chain(gr, img, prm, ed, np, lg, **k):
        return ({encode_off: b"\xaa" * 64} if ed else {}), prm
    monkeypatch.setattr(engine, "_encode_cat0_sounds", _fake_encode)
    monkeypatch.setattr(engine, "_chain_encode_appended", _fake_chain)
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
    (False, None, "longer replacements are off"),
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
    # it names the clip, and a second lost is worth a warning
    assert "idx 0 (2.00 s cut to 1.00 s)" in trimmed[0]
    assert [lvl for lvl, m in msgs if m == trimmed[0]] == ["warning"]
    # and the sound still landed, in place, exactly as before
    img_lo = _CardReader.IMG_DISK
    assert [d for d, _b in writes if img_lo <= d < img_lo + 0x40000]
    assert counts[0] == 1


def test_a_bank_that_would_pass_the_game_s_file_limit_is_not_staged(
        monkeypatch, tmp_path, _grow_on):
    """The game can't open a sound bank of 2 GiB or more.  A build whose
    longer sounds would take it there used to stage the bank anyway and fail
    in the derive with "most likely a newer game update" (PAD-176); the clip
    is now fitted to its slot instead, and the log says why."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    params = _params(4)
    _reader, staged = _grow_card(monkeypatch, tmp_path, params)
    # A 2 s mono clip's appended body is ~181 KB; the fake bank is empty.
    monkeypatch.setattr(EM, "MAX_IMAGE_BYTES", 100000)
    assets, _w = _edits(tmp_path, 2.0)
    msgs, log = _capture()
    writes, counts, plan, _m, _v = _run(
        monkeypatch, assets, params, params[0]["body_off"], log)
    assert "path" not in staged, "the bank must not have been staged"
    trimmed = _said(msgs, "are trimmed to fit")
    assert len(trimmed) == 1
    assert "can't open a sound bank bigger than 0 MB" in trimmed[0]
    assert "idx 0 (2.00 s cut to 1.00 s)" in trimmed[0]
    img_lo = _CardReader.IMG_DISK
    assert [d for d, _b in writes if img_lo <= d < img_lo + 0x40000]
    assert counts[0] == 1


@pytest.mark.parametrize("grown_before", [0, 2])
def test_a_card_an_earlier_build_grew_is_not_grown_again(
        monkeypatch, tmp_path, _grow_on, grown_before):
    """Growing assumes a stock bank.  On a card an earlier build had grown it
    re-pointed from a key the play tables no longer carry and failed with
    "idx 7: no descriptor in the game's play tables names this sound's
    record" (PAD-176).  Row 0 is that case, the same sound lengthened again;
    row 2 is a different sound, whose record would have landed on the
    earlier appended body.  Either way the clip is fitted and the log says
    why."""
    params = _params(4)
    params[grown_before]["shadows"] = 4        # its live record is appended
    _reader, staged = _grow_card(monkeypatch, tmp_path, params)
    assets, _w = _edits(tmp_path, 2.0)
    msgs, log = _capture()
    writes, counts, plan, _m, _v = _run(
        monkeypatch, assets, params, params[0]["body_off"], log)
    assert "path" not in staged, "the bank must not have been staged"
    assert "path" not in staged["repointed"]
    trimmed = _said(msgs, "are trimmed to fit")
    assert len(trimmed) == 1
    assert "already grown by an earlier build (1 longer sound(s)" in trimmed[0]
    assert "stock card" in trimmed[0]
    assert "idx 0 (2.00 s cut to 1.00 s)" in trimmed[0]
    img_lo = _CardReader.IMG_DISK
    assert [d for d, _b in writes if img_lo <= d < img_lo + 0x40000]
    assert counts[0] == 1


def test_a_sound_an_earlier_build_grew_keeps_its_longer_slot(tmp_path):
    """The source's params carry the grown sound's LIVE length, so a
    replacement up to it still fits whole: refusing a second grow loses
    nothing the card already has."""
    grown = dict(_params(1)[0], length=3 * 44100, shadows=4)
    wav = _wav(tmp_path / "idx0000.wav", 2.5)
    fits, grows = engine._classify_audio_edits({0: grown}, {0: wav}, "")
    assert fits == {0: wav} and grows == {}
    assert engine._grown_source_gate(_params(4)) == (True, "")
    ok, why = engine._grown_source_gate([grown] + _params(3)[1:])
    assert not ok and "(1 longer sound(s), which keep their length)" in why


def _bank_header(tmp_path, md_off, count):
    p = tmp_path / "image.bin"
    h = bytearray(0x100)
    struct.pack_into("<I", h, 0x40, md_off)
    struct.pack_into("<I", h, 0x60, count)
    p.write_bytes(bytes(h))
    return str(p)


# Stock Godzilla LE/Premium 1.16: image.bin is 1,649,655,138 bytes.
GZ116_MD_OFF, GZ116_COUNT = 1649594314, 2534


def test_longer_sounds_past_the_limit_are_trimmed_in_slot_order(tmp_path):
    """Slot order is the order they are appended in.  A song that doesn't fit
    is skipped, not the end of the pass: a shorter one after it still gets
    the room that is left."""
    img = _bank_header(tmp_path, GZ116_MD_OFF, GZ116_COUNT)
    byidx = {i: {"idx": i, "chan": 2, "length": 1692642} for i in (5, 9, 12)}
    minute = 60 * 44100
    grows = {5: (1692442, 50 * minute),        # 50 min: ~529 MB, too big
             9: (1692442, 5078244),            # 115 s:   ~20 MB
             12: (1692442, 40 * minute)}       # 40 min: ~423 MB, fits after 9
    msgs, log = _capture()
    kept = engine._grows_within_bank_limit(grows, byidx, img, log)
    assert set(kept) == {9, 12}
    # A budget readout is always logged; the trim reason is the warning.
    [msg] = _said(msgs, "trimmed to fit")
    assert msgs[-1][0] == "warning"
    assert "can't open a sound bank bigger than 2147 MB" in msg
    assert "idx 5 (3000.00 s cut to 38.38 s)" in msg
    assert "with the 2 other longer sound(s) kept whole" in msg
    assert "idx 9" not in msg and "idx 12" not in msg
    # The always-on readout names how much room the two kept songs leave.
    [readout] = _said(msgs, "2 kept whole")
    assert "of the 2147 MB the game can open" in readout


def test_longer_sounds_that_fit_are_all_kept_with_a_budget_readout(tmp_path):
    """Item PAD-181: even when nothing is trimmed, one info line reports how
    much of the bank is used and how many minutes are left."""
    img = _bank_header(tmp_path, GZ116_MD_OFF, GZ116_COUNT)
    byidx = {i: {"idx": i, "chan": 2, "length": 1692642} for i in (5, 9)}
    grows = {5: (1692442, 5078244), 9: (1692442, 5078244)}
    msgs, log = _capture()
    assert engine._grows_within_bank_limit(grows, byidx, img, log) == grows
    [(lvl, msg)] = msgs
    assert lvl == "info"
    assert "2 kept whole" in msg
    assert "more minute(s) of stereo sound" in msg


def test_grow_priority_keeps_user_chosen_songs_first(tmp_path):
    """Item PAD-181: when the bank can't hold everything, the songs the user
    marked win the room, in the order marked, over lower slot numbers."""
    img = _bank_header(tmp_path, GZ116_MD_OFF, GZ116_COUNT)
    byidx = {i: {"idx": i, "chan": 2, "length": 1692642} for i in (5, 9, 12)}
    minute = 60 * 44100
    # Each song is ~30 min (~317 MB); only one fits in the ~498 MB spare.
    grows = {i: (1692442, 30 * minute) for i in (5, 9, 12)}
    # Slot order would keep idx 5; the user asked for idx 12.
    msgs, log = _capture()
    kept = engine._grows_within_bank_limit(grows, byidx, img, log,
                                           priority=[12, 9])
    assert set(kept) == {12}
    assert {5, 9} == set(_grows_cut(msgs))


def _grows_cut(msgs):
    """idx numbers named in the trim line of a budget run."""
    line = "".join(_said(msgs, "trimmed to fit"))
    return [int(n) for n in re.findall(r"idx (\d+) \(", line)]


def test_grow_priority_read_from_the_sidecar_in_order(tmp_path):
    """The write reads the user's "keep whole" order out of
    ``.staged_changes.json`` (matched by the idx#### stem, like the Level
    column), not through the write call.  A folder that never used it reads []
    so the pick stays slot order."""
    from pinball_decryptor.core import staged_changes as sc
    assert engine._grow_priority_idxs(str(tmp_path)) == []
    sc.save(str(tmp_path), {"grow_keep_whole": [
        "audio/idx1145 SONG.wav", "audio/idx0220.wav",
        "video/clip.mov", "audio/idx1145 SONG.wav"]})
    # idx order preserved, non-audio and duplicate dropped.
    assert engine._grow_priority_idxs(str(tmp_path)) == [1145, 220]


def test_the_limit_is_the_largest_file_the_game_can_open():
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    assert EM.MAX_IMAGE_BYTES == 2 ** 31 - 1


@pytest.mark.parametrize("count", [2534, 2535])
def test_the_bank_size_is_where_staging_ends_the_file(count):
    """The budget is only right if it is the size the staged file really
    comes to, for both parities of the record count (align16 pads an odd
    array by 8 and an even one by nothing)."""
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = MD.Directory(b"\x00" * MD.RECORD_SIZE * count, count, GZ116_MD_OFF, 0)
    sizes = [engine._grown_body_bytes({"chan": 2}, 5078244),
             engine._grown_body_bytes({"chan": 1}, 99999)]
    _grown, places = MD.plan_grow_records(
        d, [MD.GrowEdit(3, 100, 5078444, sizes[0]),
            MD.GrowEdit(7, 100, 100199, sizes[1])])
    end = places[-1].body_off + places[-1].body_bytes
    assert engine._grown_bank_bytes(GZ116_MD_OFF, count, sizes) == end
    # and with nothing appended it is the stock file: the directory is its tail
    assert (engine._grown_bank_bytes(GZ116_MD_OFF, count, [])
            == GZ116_MD_OFF + MD.tail_len(count))


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


@pytest.mark.parametrize("grow,seconds", [(True, 3.0), (False, 1.0)])
def test_the_replace_tab_hands_a_longer_clip_to_the_build_whole(
        tmp_path, grow, seconds):
    """PAD-174: a whole song assigned to a 38 s music loop went on the card
    at 38 s with the option ticked.  Stern forces the Replace tab's trim/pad
    on, and staging cut the clip to its slot before the build could grow the
    bank for it.  With the option on, the build gets the clip whole (and
    fits it itself if this write can't grow); with it off, nothing changes."""
    import queue
    from types import SimpleNamespace

    from pinball_decryptor.app import App
    from pinball_decryptor.core.audio_slots import scan_audio_slots

    assets = tmp_path / "project"
    (assets / "audio").mkdir(parents=True)
    _wav(assets / "audio" / "idx1145.wav", 1.0, chan=2)
    song = _wav(tmp_path / "song.wav", 3.0, chan=2)
    slots = {s.rel_path: s for s in scan_audio_slots(str(assets))}
    app = object.__new__(App)
    app.msg_queue = queue.Queue()
    app.window = SimpleNamespace(
        # Stern's forced trim, exactly as the tab reports it.
        pending_audio_assignments=lambda d: (
            slots, {"audio/idx1145.wav": song}, True, frozenset()),
        _audio_grow_active=lambda: grow)

    pending, staged, failures = App._stage_pending_audio(app, str(assets))

    assert (pending, staged, failures) == (1, 1, [])
    with wave.open(str(assets / "audio" / "idx1145.wav"), "rb") as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(seconds,
                                                                  abs=0.02)
