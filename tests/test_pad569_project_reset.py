"""PAD-569 (DragonRR: "we probably need another reset option which RESETS everything"): the
top bar's Reset... puts the kinds of change ticked back the way the project was extracted;
every kind is Revert all changes plus the Scenes edits and the project's own modes, which
Revert all never reached."""
import hashlib
import os
import time

from tests.webui_harness import web_app

CARD = "/g/scene1/scene.radium"
FILES = {
    "audio/a.wav": b"RIFF-a",
    "video/v.mp4": b"MP4-v",
    "images/i.png": b"PNG-i",
    "images/scene_textures/glyphs/F/U+0041.png": b"PNG-glyph",
    "callouts.csv": b"stock,csv",
}


def _md5(data):
    return hashlib.md5(data).hexdigest()


def _project(root):
    """An extracted project (baseline + .orig snapshots of every edited file) with a change
    of every kind the Reset dialog lists."""
    from pinball_decryptor.core import colour_profile as cp
    from pinball_decryptor.core import staged_changes, staged_originals, text_manifest
    from pinball_decryptor.plugins.stern import scene_edit, text_colors
    proj = root / "proj"
    lines = []
    for rel, data in FILES.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        lines.append("%s\t%s" % (rel, _md5(data)))
    base = proj / ".checksums.md5"
    base.write_text("\n".join(lines) + "\n", encoding="utf-8")
    old = time.time() - 60                           # the extract was a minute ago
    for p in [base] + [proj / rel for rel in FILES]:
        os.utime(p, (old, old))
    d = str(proj)
    for rel, data in FILES.items():                  # every file edited, snapshot first
        assert staged_originals.snapshot(d, rel, _md5(data))
        (proj / rel).write_bytes(data + b"-edited")
    staged_changes.save(d, {
        "image": {"images/i.png": "C:/mine/i.png"}, "image_keep_size": ["images/i.png"],
        "video": {"video/v.mp4": "C:/mine/v.mp4"}, "video_variants": {"video/v.mp4": ["x"]},
        "audio": {"audio/a.wav": "C:/mine/a.wav"}, "audio_levels": {"audio/a.wav": 3},
        "replacement_names": {"images/i.png": "i", "audio/a.wav": "a", "video/v.mp4": "v"},
        "score_colors": {"up": "#ff0000"},
        cp.IMAGE_SLOTS_KEY: {"images/i.png": True},
        cp.SCREEN_KEY: {"keep": "me"},
        "image_change_filter": "Changed",
    })
    cp.store(d, cp.Profile(saturation=0.5))
    scene_edit.set_ops(d, CARD, [{"op": "move", "node": 5, "dx": 10.0, "dy": 0.0}])
    text_manifest.save(d, [{"path": "x.radium", "original": "HELLO", "replacement": "HOWDY"}])
    text_colors.set_color(d, CARD, "HELLO", (255, 255, 255), (255, 0, 0))
    mode = proj / "modes" / "my_mode"
    mode.mkdir(parents=True)
    (mode / "mode.json").write_text("{}", encoding="utf-8")
    return proj


def _state(proj):
    from pinball_decryptor.core import staged_changes, text_manifest
    from pinball_decryptor.plugins.stern import scene_edit, text_colors
    d = str(proj)
    data = staged_changes.load(d)
    return {
        "files": {rel: (proj / rel).read_bytes() == FILES[rel] for rel in FILES},
        "keys": sorted(data),
        "names": sorted(data.get("replacement_names") or {}),
        "scenes": scene_edit.count(d),
        "text": text_manifest.count_changed(d),
        "text_colors": text_colors.count(d),
        "modes": os.path.isdir(proj / "modes" / "my_mode"),
    }


def test_each_kind_resets_only_its_own_changes(tmp_path):
    from pinball_decryptor.core import project_reset as PR
    proj = _project(tmp_path)
    d = str(proj)
    counts = PR.counts(d, changed=list(FILES))
    assert all(counts[k] for k in ("scenes", "colours", "images", "videos", "sounds", "text",
                                   "fonts", "modes")), counts
    # Scenes edits and images: nothing else moves
    PR.drop_records(d, ["scenes", "images"])
    PR.restore_snapshots(d, ["scenes", "images"])
    st = _state(proj)
    assert st["scenes"] == 0 and "score_colors" not in st["keys"]
    assert st["files"] == {"audio/a.wav": False, "video/v.mp4": False, "images/i.png": True,
                           "images/scene_textures/glyphs/F/U+0041.png": False,
                           "callouts.csv": False}
    assert "image" not in st["keys"] and "image_keep_size" not in st["keys"]
    assert st["names"] == ["audio/a.wav", "video/v.mp4"]
    assert {"video", "audio", "color_profile", "image_color_slots"} <= set(st["keys"])
    assert st["text"] == 1 and st["text_colors"] == 1 and st["modes"]
    # colour profiles: every switch and profile, never the machine screen
    PR.drop_records(d, ["colours"])
    st = _state(proj)
    assert "color_profile" not in st["keys"] and "image_color_slots" not in st["keys"]
    assert "screen_profile" in st["keys"] and "video" in st["keys"]
    # text, fonts, modes
    PR.drop_records(d, ["text", "fonts", "modes"])
    PR.restore_snapshots(d, ["text", "fonts", "modes"])
    st = _state(proj)
    assert st["text"] == 0 and st["text_colors"] == 0 and not st["modes"]
    assert st["files"]["images/scene_textures/glyphs/F/U+0041.png"]
    assert not st["files"]["audio/a.wav"] and not st["files"]["callouts.csv"]


def test_everything_is_revert_all_plus_scenes_and_modes(tmp_path):
    from pinball_decryptor.core import project_reset as PR
    proj = _project(tmp_path)
    d = str(proj)
    PR.drop_records(d, PR.KEYS)
    PR.restore_snapshots(d, PR.KEYS)
    st = _state(proj)
    assert all(st["files"].values())                 # callouts.csv too: no kind of its own
    assert st["keys"] == ["screen_profile"]           # what Revert all keeps
    assert st["scenes"] == 0 and st["text"] == 0 and st["text_colors"] == 0
    assert not st["modes"]
    assert not (proj / ".orig").exists()


def _wait(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def test_the_top_bar_reset_runs_the_ticked_kinds(tmp_path):
    """The dialog counts each kind, asks once more, and the run puts back the files and
    records of the kinds ticked; a tab holding a pick of a kind reset forgets it, so its next
    save cannot write it back."""
    from pinball_decryptor.core import staged_changes
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(d))
        assert w.call("shellx.reset_open") is True
        assert _wait(w, lambda: not (w.state("shellx").get("reset") or {}).get("busy"))
        rows = {r["key"]: r["n"] for r in w.state("shellx")["reset"]["rows"]}
        assert rows["images"] >= 2 and rows["scenes"] == 2 and rows["modes"] == 1
        images = w.window.service("images")
        images._assignments = {"images/i.png": "C:/mine/i.png"}   # what the tab holds
        w.answers.append("no")                                     # the last question
        assert w.call("shellx.reset_run", ["images", "scenes"]) is False
        assert _state(proj)["scenes"] == 1
        w.answers.extend(["yes", "ok"])
        assert w.call("shellx.reset_run", ["images", "scenes"]) is True
        assert w.state("shellx")["reset"] is None                # the dialog closes
        assert _wait(w, lambda: not w.window._running and _state(proj)["files"]["images/i.png"])
        assert images._assignments == {}
        w.run(images._save_staged_changes)
        assert not staged_changes.load(d).get("image")
        st = _state(proj)
        assert st["scenes"] == 0 and st["modes"] and not st["files"]["audio/a.wav"]
        hist = (proj / ".history.log").read_text(encoding="utf-8")
        assert "reset  Scenes edits, Replaced images back as extracted" in hist


def test_revert_all_changes_is_reset_with_everything_ticked(tmp_path):
    """The Write tab's Revert all changes opens Reset... with every kind ticked; run that
    way it also drops the Scenes edits, the text colors and the project's own modes."""
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.write_assets_var.set(d))
        assert w.call("shellx.reset_open") is True
        keys = [r["key"] for r in w.state("shellx")["reset"]["rows"]]
        w.answers.extend(["yes", "ok"])
        assert w.call("shellx.reset_run", keys) is True
        assert _wait(w, lambda: not w.window._running and all(_state(proj)["files"].values()))
        st = _state(proj)
        assert st["keys"] == ["screen_profile"]
        assert st["scenes"] == 0 and st["text"] == 0 and st["text_colors"] == 0
        assert not st["modes"]
    js = open(os.path.join(os.path.dirname(__file__), "..", "pinball_decryptor", "webui", "static",
                           "js", "tabs", "write.js"), encoding="utf-8").read()
    assert 'openDialog("reset", { all: true })}>Revert all changes…' in js


def test_the_text_list_file_counts_by_its_edits_not_its_bytes(tmp_path):
    """The app rewrites text/strings.tsv itself (a project opened on Text or Scenes), so the
    file differs from the extract's with no edit in it: Text edits counts its edits only."""
    from pinball_decryptor.core import project_reset as PR
    from pinball_decryptor.core import text_manifest
    proj = tmp_path / "proj"
    text_manifest.save(str(proj), [{"path": "x.radium", "original": "HELLO", "replacement": ""}])
    assert PR.counts(str(proj), changed=["text/strings.tsv"])["text"] == 0
    text_manifest.save(str(proj), [{"path": "x.radium", "original": "HELLO", "replacement": "HI"}])
    assert PR.counts(str(proj), changed=["text/strings.tsv"])["text"] == 1
