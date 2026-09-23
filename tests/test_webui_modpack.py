"""Mod Pack tab (webui/tabs/modpack.py): gating per manufacturer / era, the
transfer form's variables, chips and auto-fill, the destination pre-fill the
run logic's scan fan-out reaches, the Browse pickers, and the flows app.py
drives from the tab's buttons (export / import end to end, the transfer /
port guards).  Apply Delta is the Write tab's (test_webui_write.py)."""

import json
import os
import time
import zipfile

import pytest

from tests.webui_harness import web_app

MODPACK_MFRS = ("stern", "jjp", "spooky", "pb", "cgc", "dp", "bof")
NO_MODPACK_MFRS = ("ap", "williams")


def _visible(w):
    tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
    return bool(tabs.get("modpack", {}).get("visible"))


def _wait_for(w, title, timeout=30.0):
    """Wait until a modal with *title* has been asked; return its spec."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        w.drain()
        for spec in list(w.asked):
            if spec.get("title") == title:
                return spec
        time.sleep(0.05)
    raise AssertionError("no %r dialog; asked: %s" % (
        title, [s.get("title") for s in w.asked]))


def _titles(w):
    return [s.get("title") for s in w.asked]


def _set_project(w, folder):
    w.run(lambda: w.window.write_assets_var.set(folder))
    w.drain()


def _stub_other_tabs(w, monkeypatch):
    """The export worker stages the Replace tabs' pending picks first; stub
    those window methods while the Replace tabs are not ported yet."""
    for name, value in (("pending_audio_assignments", lambda d: None),
                        ("pending_video_assignments", lambda d: None),
                        ("pending_image_assignments", lambda d: None),
                        ("_audio_grow_active", lambda: False)):
        try:
            getattr(w.window, name)
        except AttributeError:
            monkeypatch.setattr(w.window, name, value, raising=False)


# ------------------------------------------------------------------ gating
@pytest.mark.parametrize("mfr", MODPACK_MFRS + NO_MODPACK_MFRS)
def test_state_after_manufacturer(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        caps = w.window.current_mfr.capabilities
        s = w.state("modpack")
        assert _visible(w) == (mfr in MODPACK_MFRS)
        assert s["modpack_cap"] == bool(caps.modpack)
        assert s["transfer_cap"] == bool(getattr(caps, "mod_transfer", False))
        # Tk builds the Apply Delta box on the Write tab only
        assert "delta_cap" not in s
        assert not hasattr(w.window.service("modpack"), "apply_delta")
        if mfr == "stern":
            assert s["transfer_cap"] is True
        if mfr in ("jjp", "spooky", "cgc", "bof", "dp", "pb"):
            assert not s["transfer_cap"]


@pytest.mark.parametrize("era,visible,transfer", [
    ("spike2", True, True), ("spike1", True, False),
    ("whitestar", False, False)])
def test_stern_eras(tmp_path, era, visible, transfer):
    with web_app(tmp_path, mfr="stern", era=era) as w:
        assert _visible(w) is visible
        assert w.state("modpack")["transfer_cap"] is transfer


# ------------------------------------------------------------------ exports
def test_every_export_is_this_tabs(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("modpack")
        for name in svc.exports:
            assert getattr(w.window, name) == getattr(svc, name), name
        missing = getattr(w.window, "missing_exports", None) or {}
        for name in ("transfer_src_var", "transfer_dst_var",
                     "transfer_oldstock_var", "transfer_next_var",
                     "transfer_newimg_var"):
            assert name not in missing
            assert getattr(w.window, name).get() == ""


def test_next_step_line_follows_the_run_logic(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.transfer_next_var.set("✓ Next: open the "
                                                    "Write tab"))
        assert w.state("modpack")["next"] == "✓ Next: open the Write tab"


# ------------------------------------------------------------------ form
def _extract(tmp_path, name, image_name, card_version=None, make_image=False):
    d = tmp_path / name
    d.mkdir()
    img = tmp_path / image_name
    if make_image:
        img.write_bytes(b"\0" * 64)
    rec = {"input_path": str(img), "input_name": image_name, "size": 64,
           "mtime": 0}
    if card_version:
        rec["card_version"] = card_version
    (d / ".extract_source.json").write_text(json.dumps(rec),
                                            encoding="utf-8")
    return str(d), str(img)


def test_chips_autofill_and_output_preview(tmp_path, monkeypatch):
    old, _ = _extract(tmp_path, "old", "godzilla_le-1_15_0.Release.8G.sdcard.raw",
                      card_version="1.15.0")
    new, img = _extract(tmp_path, "new",
                        "godzilla_le-1_16_0.Release.8G.sdcard.raw",
                        make_image=True)
    stock, _ = _extract(tmp_path, "stock",
                        "godzilla_le-1_15_0.Release.8G.sdcard.raw")
    with web_app(tmp_path, mfr="stern") as w:
        mfr = w.window.current_mfr
        probed = []

        def _card_version(path):
            probed.append(path)
            return "1.16.0", True
        monkeypatch.setattr(mfr, "card_version", _card_version)
        w.call("ui.set", "modpack", "src", old)
        w.call("ui.set", "modpack", "oldstock", stock)
        w.call("ui.set", "modpack", "dst", new)
        w.drain()
        s = w.state("modpack")
        assert w.window.transfer_src_var.get() == old
        assert s["src_ver"] == "version 1.15.0"
        assert s["oldstock_ver"].startswith("version ~ 1.15.0")
        assert s["dst_ver"].startswith("version ~ 1.16.0")
        # field 4 auto-fills from field 2's recorded source image
        assert w.window.transfer_newimg_var.get() == os.path.normpath(img)
        assert s["img_ver"].startswith("version ~ 1.16.0")
        assert s["output"] == ("After transfer, the Write tab builds: "
                               "godzilla_le-1_16_0.Release.8G.sdcard"
                               "-modified.raw")
        # the card probe upgrades the chip off the loop, debounced
        deadline = time.time() + 10
        while time.time() < deadline and \
                w.state("modpack")["img_ver"] != "version 1.16.0":
            time.sleep(0.1)
        assert w.state("modpack")["img_ver"] == "version 1.16.0"
        assert probed == [os.path.normpath(img)]
        # a typed image is never overwritten by the auto-fill
        w.call("ui.set", "modpack", "newimg", "")
        w.call("ui.set", "modpack", "newimg", str(tmp_path / "mine.raw"))
        w.call("ui.set", "modpack", "dst", new)
        assert w.window.transfer_newimg_var.get() == str(tmp_path /
                                                         "mine.raw")
        # clearing field 4 with field 2 set re-fills it from field 2
        w.call("ui.set", "modpack", "newimg", "")
        assert w.window.transfer_newimg_var.get() == os.path.normpath(img)
        # both empty -> no preview
        w.call("ui.set", "modpack", "dst", "")
        w.call("ui.set", "modpack", "newimg", "")
        w.drain()
        assert w.state("modpack")["output"] == ""
        assert w.state("modpack")["img_ver"] == ""
        assert w.state("modpack")["dst_ver"] == ""


def test_project_mirror_and_dst_prefill(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _set_project(w, str(proj))
        assert w.state("modpack")["project"] == str(proj)
        w.call("ui.select_tab", "modpack")
        assert w.window.transfer_dst_var.get() == str(proj)
        # never overwrites what the user picked
        w.call("ui.set", "modpack", "dst", str(tmp_path))
        w.call("ui.select_tab", "modpack")
        assert w.window.transfer_dst_var.get() == str(tmp_path)


def test_project_change_prefills_dst_on_the_visible_tab(tmp_path):
    """Tk: invalidate_asset_scans() (Open project, close, extract end)
    re-scans the VISIBLE tab, and reload_assets_tabs() (import, transfer)
    every tab; for Mod Pack that scan is _prefill_transfer_dst."""
    one = tmp_path / "one"
    one.mkdir()
    two = tmp_path / "two"
    two.mkdir()
    three = tmp_path / "three"
    three.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.select_tab", "modpack")
        assert w.window.transfer_dst_var.get() == ""

        def _open(folder):
            w.window.write_assets_var.set(folder)
            w.window.invalidate_asset_scans()
        w.run(_open, str(one))
        w.drain()
        assert w.window.transfer_dst_var.get() == str(one)
        assert w.state("modpack")["dst"] == str(one)
        # a picked destination is never overwritten
        w.run(_open, str(two))
        w.drain()
        assert w.window.transfer_dst_var.get() == str(one)
        # reload_assets_tabs fills an emptied field
        w.call("ui.set", "modpack", "dst", "")
        w.run(w.window.reload_assets_tabs)
        w.drain()
        assert w.window.transfer_dst_var.get() == str(two)
        # another tab on screen: invalidate leaves Mod Pack for its next
        # visit, reload_assets_tabs still reaches it (Tk scans every tab)
        other = next(t["ns"] for t in w.state("shell")["tabs"]
                     if t["visible"] and t["ns"] != "modpack")
        w.call("ui.select_tab", other)
        w.call("ui.set", "modpack", "dst", "")
        w.run(_open, str(three))
        w.drain()
        assert w.window.transfer_dst_var.get() == ""
        w.run(w.window.reload_assets_tabs)
        w.drain()
        assert w.window.transfer_dst_var.get() == str(three)


def test_browse_each_field(tmp_path):
    folder = tmp_path / "pick"
    folder.mkdir()
    image = tmp_path / "card.raw"
    image.write_bytes(b"x")
    with web_app(tmp_path, mfr="stern") as w:
        for field, title_part, mode in (
                ("src", "OLD extract folder", "folder"),
                ("dst", "NEW version's extract folder", "folder"),
                ("oldstock", "STOCK (unmodified) extract", "folder")):
            w.answers.append(str(folder))
            assert w.call("modpack.browse", field) == os.path.normpath(
                str(folder))
            spec = w.asked[-1]
            assert spec["kind"] == "file" and spec["mode"] == mode
            assert title_part in spec["title"]
            assert w.state("modpack")[field] == os.path.normpath(str(folder))
        w.answers.append(str(image))
        w.call("modpack.browse", "newimg")
        spec = w.asked[-1]
        assert spec["mode"] == "open"
        assert ["Card image", "*.raw *.img *.bin"] in spec["filetypes"]
        assert w.window.transfer_newimg_var.get() == os.path.normpath(
            str(image))
        # a cancelled picker changes nothing
        w.answers.append("")
        assert w.call("modpack.browse", "src") == ""
        assert w.window.transfer_src_var.get() == os.path.normpath(
            str(folder))


def test_open_project_without_a_folder_says_why(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        assert w.call("modpack.open_project") is False
        assert w.asked[-1]["title"] == "Open folder"
        assert "set it on the Extract tab" in w.asked[-1]["message"]
        _set_project(w, str(tmp_path / "gone"))
        assert w.call("modpack.open_project") is False
        assert "doesn't exist yet" in w.asked[-1]["message"]


def test_open_project_reveals_the_folder(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modpack
    seen = []
    monkeypatch.setattr(modpack.ModPackTab, "_reveal_folder",
                        staticmethod(lambda p: seen.append(p) or True))
    with web_app(tmp_path, mfr="jjp") as w:
        _set_project(w, str(tmp_path))
        assert w.call("modpack.open_project") is True
        assert seen == [str(tmp_path)]


# ------------------------------------------------------------------ buttons
@pytest.mark.parametrize("method,cb", [
    ("export_pack", "on_export"), ("import_pack", "on_import"),
    ("port", "on_port_mods"), ("transfer", "on_transfer_mods")])
def test_buttons_start_the_run_logic(tmp_path, monkeypatch, method, cb):
    with web_app(tmp_path, mfr="stern") as w:
        hits = []
        monkeypatch.setitem(w.window.cb, cb, lambda: hits.append(cb))
        assert w.call("modpack." + method) is True
        assert hits == [cb]


def test_export_and_import_guards(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("modpack.export_pack")
        assert _titles(w)[-1] == "Missing Input"
        w.call("modpack.import_pack")
        assert _titles(w)[-1] == "Missing Input"
        _set_project(w, str(bare))
        w.call("modpack.export_pack")
        assert _titles(w)[-1] == "No Baseline Checksums"


def test_export_then_import_end_to_end(tmp_path, monkeypatch):
    from pinball_decryptor.core.checksums import generate_checksums
    src = tmp_path / "src"
    (src / "sound").mkdir(parents=True)
    (src / "sound" / "a.wav").write_bytes(b"stock-a")
    (src / "sound" / "b.wav").write_bytes(b"stock-b")
    generate_checksums(str(src))
    dst = tmp_path / "dst"
    (dst / "sound").mkdir(parents=True)
    (dst / "sound" / "a.wav").write_bytes(b"stock-a")
    (dst / "sound" / "b.wav").write_bytes(b"stock-b")
    generate_checksums(str(dst))
    (src / "sound" / "a.wav").write_bytes(b"MODDED-a")
    zip_path = str(tmp_path / "out" / "pack.zip")
    os.makedirs(os.path.dirname(zip_path))
    with web_app(tmp_path, mfr="stern") as w:
        _stub_other_tabs(w, monkeypatch)
        _set_project(w, str(src))
        w.answers.append(zip_path)                    # Save Mod Pack As
        w.call("modpack.export_pack")
        save = [s for s in w.asked if s.get("kind") == "file"][-1]
        assert save["title"] == "Save Mod Pack As"
        assert save["mode"] == "save"
        done = _wait_for(w, "Export Complete")
        assert "Contains 1 modified file(s)" in done["message"]
        with zipfile.ZipFile(zip_path) as zf:
            assert "sound/a.wav" in zf.namelist()

        _set_project(w, str(dst))
        w.answers.extend([zip_path, "yes"])       # picker, then the confirm
        w.call("modpack.import_pack")
        confirm = _wait_for(w, "Import Mod Pack")
        assert confirm["kind"] == "details"
        assert "1 file(s) will be imported" in confirm["message"]
        _wait_for(w, "Import Complete")
        assert (dst / "sound" / "a.wav").read_bytes() == b"MODDED-a"


def test_transfer_guards(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Pick the old extract"
        w.call("ui.set", "modpack", "src", str(a))
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Pick the new extract"
        w.call("ui.set", "modpack", "dst", str(a))
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Same folder"
        w.call("ui.set", "modpack", "dst", str(b))
        w.call("ui.set", "modpack", "oldstock", str(a))
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Wrong folder"
        w.call("ui.set", "modpack", "oldstock", str(tmp_path / "nope"))
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Old stock extract not found"
        w.call("ui.set", "modpack", "oldstock", "")
        w.call("ui.set", "modpack", "newimg", str(tmp_path / "nope.raw"))
        w.call("modpack.transfer")
        assert _titles(w)[-1] == "Base image not found"


def test_port_guards(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("modpack.port")
        assert _titles(w)[-1] == "No project folder"
        _set_project(w, str(proj))
        w.answers.append("no")
        w.call("modpack.port")
        assert _titles(w)[-1] == "No staged mods found"
        # yes -> the multi-image picker; cancelling it starts nothing
        w.answers.extend(["yes", []])
        w.call("modpack.port")
        pick = w.asked[-1]
        assert pick["kind"] == "file" and pick["multiple"] is True
        assert pick["title"].startswith("Stock card image(s) to port onto")
        assert w.state("shell")["running"] is False


def test_transfer_and_port_do_nothing_without_the_capability(tmp_path):
    with web_app(tmp_path, mfr="jjp") as w:
        n = len(w.asked)
        w.call("modpack.transfer")
        w.call("modpack.port")
        assert len(w.asked) == n

