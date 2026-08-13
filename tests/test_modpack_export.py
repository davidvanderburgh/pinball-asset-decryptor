"""Export Mod Pack must include the user's Replace-tab edits.

A tester assigned ~50 audio replacements on the Replace Audio tab and hit
"Export mod pack" straight away — it failed with "No modified files found"
even though the Write preview listed every one as Pending.  The Replace tabs
record assignments in memory (+ a sidecar) and only *stage them onto disk* at
build time; the export diffed the still-pristine on-disk bytes against the
baseline and saw nothing.  ``App._export_worker`` now stages pending
replacements first, exactly like the build flow, so an export needs no
build-first dance.

Also guards a baseline-flavour regression: ``export_mod_pack`` must read the
md5sum-style ``.checksums.md5`` (JJP), not only the tab form.
"""
import os
import queue
import zipfile

import pytest

from pinball_decryptor import app as appmod
from pinball_decryptor.core import modpack
from pinball_decryptor.core.messages import LogMsg


# --- baseline parsing: export_mod_pack accepts BOTH .checksums.md5 flavours ---

def _assets(zf):
    """The zip's asset entries — everything but the .modpack.json manifest."""
    return [n for n in zf.namelist() if n != modpack.MANIFEST_NAME]


def _write(path, data=b"data"):
    with open(path, "wb") as f:
        f.write(data)


def _md5(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def test_export_reads_tab_flavour_baseline(tmp_path):
    # BOF / Stern style: "<path>\t<md5>".
    _write(tmp_path / "a.wav", b"orig")
    _write(tmp_path / "b.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\nb.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    _write(tmp_path / "a.wav", b"CHANGED")   # modify one file

    n, _ = modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))
    assert n == 1
    with zipfile.ZipFile(tmp_path / "pack.zip") as zf:
        assert _assets(zf) == ["a.wav"]


def test_export_reads_md5sum_flavour_baseline(tmp_path):
    # JJP / md5sum style: "<md5>  <path>".  read_checksums() returned {} for
    # this, so export wrongly raised "no baseline" on a valid JJP extract.
    _write(tmp_path / "a.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"{_md5(b'orig')}  a.wav\n", encoding="utf-8")
    _write(tmp_path / "a.wav", b"CHANGED")

    n, _ = modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))
    assert n == 1


def test_export_no_changes_raises(tmp_path):
    _write(tmp_path / "a.wav", b"orig")
    (tmp_path / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No modified files"):
        modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))


def test_export_missing_baseline_raises(tmp_path):
    _write(tmp_path / "a.wav", b"orig")
    with pytest.raises(FileNotFoundError):
        modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))


def test_export_skips_pipeline_scratch_files(tmp_path):
    """A rebuilt fl_decrypted.dat / .img is baselined and "modified", but it
    is pipeline scratch, not a card asset — packing it turned an audio-only
    mod pack into hundreds of MB (feedback batch 16)."""
    files = {"a.wav": b"orig", "fl_decrypted.dat": b"orig",
             "build/card.img": b"orig"}
    os.makedirs(tmp_path / "build", exist_ok=True)
    for name, data in files.items():
        _write(tmp_path / name, data)
    (tmp_path / ".checksums.md5").write_text(
        "".join(f"{n}\t{_md5(d)}\n" for n, d in files.items()),
        encoding="utf-8")
    for name in files:                       # every one of them changes
        _write(tmp_path / name, b"CHANGED")

    n, _ = modpack.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))
    assert n == 1
    with zipfile.ZipFile(tmp_path / "pack.zip") as zf:
        assert _assets(zf) == ["a.wav"]


def test_export_writes_manifest_and_import_reads_it(tmp_path):
    """The pack records the extract it came from (the help text has always
    said so) and Import round-trips it without unpacking it as an asset."""
    import json

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.wav", b"orig")
    (src / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    (src / ".extract_source.json").write_text(
        json.dumps({"input_name": "turtles_pro-1_59_0.Release.8G.sdcard.raw"}),
        encoding="utf-8")
    _write(src / "a.wav", b"CHANGED")

    zip_path = str(tmp_path / "pack.zip")
    modpack.export_mod_pack(str(src), zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
    assert man["version_hint"] == "1.59.0 (Release)"
    assert man["files"] == ["a.wav"]
    assert man["file_count"] == 1

    dest = tmp_path / "dest"
    dest.mkdir()
    res = modpack.import_mod_pack(zip_path, str(dest))
    # No baseline in dest, so nothing can be judged foreign — import as before.
    assert res["applied"] == ["a.wav"]              # the manifest isn't an asset
    assert (dest / "a.wav").read_bytes() == b"CHANGED"
    assert not (dest / modpack.MANIFEST_NAME).exists()


def test_import_snapshots_pristine_originals(tmp_path):
    """Import backs up each still-pristine original into .orig/ before
    overwriting (same backup staging takes), so the imported change can be
    previewed against its true original and reverted — but never captures a
    file that already diverged from the baseline (a wrong snapshot would
    'revert' to wrong bytes)."""
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"orig-a")                 # pristine
    _write(dest / "b.wav", b"already-modified")       # diverged before import
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig-a')}\nb.wav\t{_md5(b'orig-b')}\n",
        encoding="utf-8")

    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.wav", b"MODDED-A")
        zf.writestr("b.wav", b"MODDED-B")

    res = modpack.import_mod_pack(str(zip_path), str(dest))
    assert sorted(res["applied"]) == ["a.wav", "b.wav"]
    assert (dest / "a.wav").read_bytes() == b"MODDED-A"
    # pristine original captured; the divergent one is not
    assert (dest / ".orig" / "a.wav").read_bytes() == b"orig-a"
    assert not (dest / ".orig" / "b.wav").exists()


def test_import_skips_files_this_extract_does_not_have(tmp_path):
    """A pack from ANOTHER card (an LE pack on a Pro extract) mostly lands on
    paths this card doesn't have.  Writing them made 201 phantom audio slots
    that previewed the user's own mod as the card's original and that no build
    could ever use (batch 31) — skip them, and say how many."""
    dest = tmp_path / "dest"
    (dest / "audio").mkdir(parents=True)
    _write(dest / "audio" / "pro.wav", b"orig")
    (dest / ".checksums.md5").write_text(
        f"audio/pro.wav\t{_md5(b'orig')}\n", encoding="utf-8")

    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("audio/pro.wav", b"MINE")
        zf.writestr("audio/le-only-1.wav", b"MINE-1")
        zf.writestr("audio/le-only-2.wav", b"MINE-2")

    logs = []
    res = modpack.import_mod_pack(str(zip_path), str(dest),
                                  log_cb=lambda t, l="info": logs.append((l, t)))
    assert res["applied"] == ["audio/pro.wav"]
    assert sorted(res["skipped"]) == ["audio/le-only-1.wav",
                                      "audio/le-only-2.wav"]
    assert (dest / "audio" / "pro.wav").read_bytes() == b"MINE"
    assert not (dest / "audio" / "le-only-1.wav").exists()
    assert any(lvl == "warning" and "not part of this extract" in t
               for lvl, t in logs)


def test_import_removes_strays_a_previous_import_left(tmp_path):
    """The same pack imported twice: the first (old-version) import scattered
    files this card has no slot for, and they are still listed as slots.  The
    second import takes them back out."""
    dest = tmp_path / "dest"
    (dest / "audio").mkdir(parents=True)
    _write(dest / "audio" / "pro.wav", b"orig")
    _write(dest / "audio" / "le-only.wav", b"STRAY")      # left by import #1
    (dest / ".checksums.md5").write_text(
        f"audio/pro.wav\t{_md5(b'orig')}\n", encoding="utf-8")

    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("audio/pro.wav", b"MINE")
        zf.writestr("audio/le-only.wav", b"MINE-STRAY")

    res = modpack.import_mod_pack(str(zip_path), str(dest))
    assert res["removed"] == ["audio/le-only.wav"]
    assert not (dest / "audio" / "le-only.wav").exists()
    assert (dest / "audio" / "pro.wav").read_bytes() == b"MINE"

    # ...and leaving them is still possible for a caller that wants to.
    _write(dest / "audio" / "le-only.wav", b"STRAY")
    res = modpack.import_mod_pack(str(zip_path), str(dest),
                                  remove_leftovers=False)
    assert res["removed"] == []
    assert (dest / "audio" / "le-only.wav").exists()


def test_import_refuses_a_pack_that_fits_nothing(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "pro.wav", b"orig")
    (dest / ".checksums.md5").write_text(
        f"pro.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("le.wav", b"MINE")

    with pytest.raises(ValueError, match="nothing to import"):
        modpack.import_mod_pack(str(zip_path), str(dest))
    assert not (dest / "le.wav").exists()


def test_import_warns_when_the_pack_is_from_another_card(tmp_path):
    """Same firmware version, different card: the version check can't see it,
    and it is exactly the case that scatters files."""
    import json

    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"orig")
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    (dest / ".extract_source.json").write_text(
        json.dumps({"input_name": "led_zeppelin_pro-1_22_0.Release.8G.sdcard.raw"}),
        encoding="utf-8")

    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(modpack.MANIFEST_NAME, json.dumps({
            "format": 2, "version_hint": "1.22.0 (Release)",
            "source_name": "led_zeppelin_le-1_22_0.Release.8G.sdcard.raw"}))
        zf.writestr("a.wav", b"MINE")

    logs = []
    modpack.import_mod_pack(str(zip_path), str(dest),
                            log_cb=lambda t, l="info": logs.append((l, t)))
    assert any(lvl == "warning" and "different card" in t
               and "led_zeppelin_le" in t and "Transfer Mods" in t
               for lvl, t in logs)


def test_pack_carries_defaults_and_scene_names(tmp_path):
    """The Defaults tab's staged edits and the image/scene names live in the
    folder sidecar, not in any baselined file, so the file diff never saw
    them: a tester's imported project came up on stock volume with unnamed
    scenes every time."""
    import json

    from pinball_decryptor.core import staged_changes

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.wav", b"orig")
    (src / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    _write(src / "a.wav", b"CHANGED")
    staged_changes.save(str(src), {
        "audio": {"a.wav": "W:/mine/a.wav"},        # a path — must NOT travel
        "settings": {"AD_MASTER_VOLUME": 24},
        "high_scores": {"Grand Champion": {"initials": "CFB", "name": "C"}},
        "image_group_tags": {"rad::abc": "Jukebox"},
        "menu_expose_through": "AD_SOMETHING",
    })

    zip_path = str(tmp_path / "pack.zip")
    modpack.export_mod_pack(str(src), zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
    assert man["extras"]["settings"] == {"AD_MASTER_VOLUME": 24}
    assert "audio" not in man["extras"]

    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"orig")
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    staged_changes.save(str(dest), {"settings": {"AD_FREE_PLAY": 1}})

    res = modpack.import_mod_pack(zip_path, str(dest))
    assert res["extras"]["settings"] == 1
    got = staged_changes.load(str(dest))
    # merged, not replaced: this folder's own staged setting survives
    assert got["settings"] == {"AD_FREE_PLAY": 1, "AD_MASTER_VOLUME": 24}
    assert got["image_group_tags"] == {"rad::abc": "Jukebox"}
    assert got["menu_expose_through"] == "AD_SOMETHING"


def test_pack_names_the_partition_replaces_it_cannot_carry(tmp_path,
                                                           monkeypatch):
    """SternLogo.png is replaced on the card IMAGE, so no pack can hold it.
    Say so at export and again at import instead of letting it turn up stock
    on a finished build (a tester, twice)."""
    import json

    from pinball_decryptor.core import card_edits

    monkeypatch.setattr(card_edits, "CARD_EDITS_FILE",
                        str(tmp_path / "card_edits.json"))
    card = tmp_path / "card.raw"
    _write(card, b"card-bytes")
    card_edits.record_replace(str(card), 1, "/usr/local/spike/SternLogo.png",
                              162000, 188000, source_path="W:/mine/logo.png")

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.wav", b"orig")
    (src / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    (src / ".extract_source.json").write_text(
        json.dumps({"input_name": "card.raw", "input_path": str(card)}),
        encoding="utf-8")
    _write(src / "a.wav", b"CHANGED")

    logs = []
    zip_path = str(tmp_path / "pack.zip")
    modpack.export_mod_pack(str(src), zip_path,
                            log_cb=lambda t, l="info": logs.append((l, t)))
    assert any(lvl == "warning" and "SternLogo.png" in t for lvl, t in logs)

    dest = tmp_path / "dest"
    dest.mkdir()
    logs = []
    res = modpack.import_mod_pack(zip_path, str(dest),
                                  log_cb=lambda t, l="info": logs.append((l, t)))
    assert res["card_files"][0]["path"] == "/usr/local/spike/SternLogo.png"
    assert any("SternLogo.png" in t and "Partitions tab" in t
               for _lvl, t in logs)


def test_import_never_clobbers_existing_snapshot(tmp_path):
    """A second import must keep the FIRST snapshot — it is the true
    original; the now-modified file must not replace it."""
    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"orig-a")
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig-a')}\n", encoding="utf-8")

    for payload in (b"MOD-ONE", b"MOD-TWO"):
        zip_path = tmp_path / "pack.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("a.wav", payload)
        modpack.import_mod_pack(str(zip_path), str(dest))

    assert (dest / "a.wav").read_bytes() == b"MOD-TWO"
    assert (dest / ".orig" / "a.wav").read_bytes() == b"orig-a"


def test_import_warns_on_version_mismatch(tmp_path):
    import json

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.wav", b"orig")
    (src / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    (src / ".extract_source.json").write_text(
        json.dumps({"input_name": "turtles_pro-1_59_0.Release.8G.sdcard.raw"}),
        encoding="utf-8")
    _write(src / "a.wav", b"CHANGED")
    zip_path = str(tmp_path / "pack.zip")
    modpack.export_mod_pack(str(src), zip_path)

    dest = tmp_path / "dest"                       # a DIFFERENT firmware
    dest.mkdir()
    (dest / ".extract_source.json").write_text(
        json.dumps({"input_name": "turtles_pro-1_58_1.Release.8G.sdcard.raw"}),
        encoding="utf-8")
    logs = []
    modpack.import_mod_pack(zip_path, str(dest),
                            log_cb=lambda t, lvl: logs.append((lvl, t)))
    assert any(lvl == "warning" and "1.58.1" in t and "1.59.0" in t
               for lvl, t in logs)


# --- the fix: App._export_worker stages pending replacements before diffing ---

class _FakeRoot:
    def after(self, _delay, fn=None, *a):
        # Run the scheduled dialog callback inline so exceptions surface; the
        # messagebox is patched to a no-op in the app module for these tests.
        if fn is not None:
            fn(*a)


def _make_app(monkeypatch):
    a = appmod.App.__new__(appmod.App)      # skip Tk/window construction
    a.msg_queue = queue.Queue()
    a.root = _FakeRoot()
    monkeypatch.setattr(appmod, "messagebox",
                        type("M", (), {"showinfo": staticmethod(lambda *a, **k: None),
                                       "showerror": staticmethod(lambda *a, **k: None)}))
    return a


def _baseline(tmp_path, files):
    for name, data in files.items():
        _write(tmp_path / name, data)
    lines = "".join(f"{name}\t{_md5(data)}\n" for name, data in files.items())
    (tmp_path / ".checksums.md5").write_text(lines, encoding="utf-8")


def test_export_worker_stages_pending_then_packs(tmp_path, monkeypatch):
    a = _make_app(monkeypatch)
    _baseline(tmp_path, {"a.wav": b"orig", "b.wav": b"orig"})

    # Simulate the Replace-Audio stager: it writes the converted replacement
    # over a.wav (as the real one does), and reports (pending, staged, fails).
    def _stage_audio(assets_dir):
        _write(os.path.join(assets_dir, "a.wav"), b"REPLACED")
        return (1, 1, [])

    monkeypatch.setattr(a, "_stage_pending_audio", _stage_audio)
    monkeypatch.setattr(a, "_stage_pending_video", lambda d: (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_image", lambda d: (0, 0, []))

    zip_path = str(tmp_path / "pack.zip")
    a._export_worker(str(tmp_path), zip_path)

    assert os.path.isfile(zip_path), "export should have produced a zip"
    with zipfile.ZipFile(zip_path) as zf:
        assert _assets(zf) == ["a.wav"]
    logs = [m.text for m in _drain(a.msg_queue) if isinstance(m, LogMsg)]
    assert any("Mod pack: 1 file" in t for t in logs)


def test_export_worker_all_staging_failed_raises(tmp_path, monkeypatch):
    a = _make_app(monkeypatch)
    _baseline(tmp_path, {"a.wav": b"orig"})

    # Every convert failed (e.g. no ffmpeg): nothing lands on disk, so the pack
    # would be empty — surface that loudly instead of writing a useless zip.
    monkeypatch.setattr(a, "_stage_pending_audio",
                        lambda d: (2, 0, [("audio: a.wav", "need ffmpeg")]))
    monkeypatch.setattr(a, "_stage_pending_video", lambda d: (0, 0, []))
    monkeypatch.setattr(a, "_stage_pending_image", lambda d: (0, 0, []))

    a._export_worker(str(tmp_path), str(tmp_path / "pack.zip"))

    assert not os.path.isfile(tmp_path / "pack.zip")
    logs = [m.text for m in _drain(a.msg_queue) if isinstance(m, LogMsg)]
    assert any("Export failed" in t and "ffmpeg" in t for t in logs)


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_pack_carries_the_partition_replace_it_can_reach(tmp_path, monkeypatch):
    """Naming SternLogo.png was half the answer: the journal records the file
    each swap came from, so the pack can carry the bytes too and land them
    where a Partitions-tab Replace can reach them.  It still does not APPLY
    them — that is a resize inside the card's ext4 partition, needing WSL2 and
    with no undo, against an image the import was never pointed at."""
    import json

    from pinball_decryptor.core import card_edits

    monkeypatch.setattr(card_edits, "CARD_EDITS_FILE",
                        str(tmp_path / "card_edits.json"))
    card = tmp_path / "card.raw"
    _write(card, b"card-bytes")
    logo = tmp_path / "MyLogo.png"
    _write(logo, b"PNGDATA")
    card_edits.record_replace(str(card), 1, "/usr/local/spike/SternLogo.png",
                              162000, 188000, source_path=str(logo))

    src = tmp_path / "src"
    src.mkdir()
    _write(src / "a.wav", b"orig")
    (src / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")
    (src / ".extract_source.json").write_text(
        json.dumps({"input_name": "card.raw", "input_path": str(card)}),
        encoding="utf-8")
    _write(src / "a.wav", b"CHANGED")

    zip_path = str(tmp_path / "pack.zip")
    modpack.export_mod_pack(str(src), zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
        member = man["card_files"][0]["member"]
        assert zf.read(member) == b"PNGDATA"

    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"orig")
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'orig')}\n", encoding="utf-8")

    logs = []
    res = modpack.import_mod_pack(zip_path, str(dest),
                                  log_cb=lambda t, l="info": logs.append((l, t)))
    landed = (dest / modpack.IMPORTED_CARD_DIR / "usr" / "local" / "spike"
              / "SternLogo.png")
    assert landed.read_bytes() == b"PNGDATA"
    assert [p for p, _ in res["card_saved"]] == ["/usr/local/spike/SternLogo.png"]
    assert any("Partitions tab" in t and modpack.IMPORTED_CARD_DIR in t
               for _lvl, t in logs)
    # The card file is not an asset of this extract and must never be judged
    # against its baseline — otherwise it reports as a file "this card
    # doesn't have" and inflates the skipped count.
    assert res["skipped"] == []
    assert res["applied"] == ["a.wav"]


def test_import_card_file_cannot_escape_the_project(tmp_path):
    """The on-card path arrives inside a zip, so an absolute or ``..`` path
    must not write outside the folder it is unpacked into."""
    import json

    dest = tmp_path / "dest"
    dest.mkdir()
    _write(dest / "a.wav", b"x")
    (dest / ".checksums.md5").write_text(
        f"a.wav\t{_md5(b'x')}\n", encoding="utf-8")
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.wav", b"MOD")
        zf.writestr(modpack.MANIFEST_NAME, json.dumps({
            "card_files": [{"path": "../../escaped.png", "partition": 1,
                            "member": modpack.CARD_DIR + "/0/escaped.png"}]}))
        zf.writestr(modpack.CARD_DIR + "/0/escaped.png", b"NOPE")

    res = modpack.import_mod_pack(str(zip_path), str(dest))
    assert res["card_saved"] == []
    assert not (tmp_path / "escaped.png").exists()
    assert not (tmp_path.parent / "escaped.png").exists()


def test_unpacked_card_files_never_list_as_slots(tmp_path):
    """The copies Import drops are files off someone's card IMAGE, not assets
    of this extract — so if a Replace tab walked them they would be exactly
    the phantom slots this whole batch removed, and a re-extract would
    baseline them as if the card had them."""
    from pinball_decryptor.core import (audio_slots, checksums, image_slots,
                                        video_slots)

    assert modpack.IMPORTED_CARD_DIR in checksums.NON_ASSET_DIRS

    proj = tmp_path / "proj"
    (proj / "images").mkdir(parents=True)
    _write(proj / "images" / "real.png", b"art")
    carried = proj / modpack.IMPORTED_CARD_DIR / "usr" / "local" / "spike"
    carried.mkdir(parents=True)
    _write(carried / "SternLogo.png", b"logo")
    _write(carried / "boot.wav", b"snd")
    _write(carried / "splash.mov", b"vid")

    assert [s.rel_path for s in
            image_slots.scan_image_slots(str(proj), probe=False)] == \
        ["images/real.png"]
    assert audio_slots.scan_audio_slots(str(proj), probe=False) == []
    assert video_slots.scan_video_slots(str(proj), probe=False) == []

    checksums.generate_checksums(str(proj))
    assert sorted(checksums.read_baseline_any(str(proj))) == ["images/real.png"]
