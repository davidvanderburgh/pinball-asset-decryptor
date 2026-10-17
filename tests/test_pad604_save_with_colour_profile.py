"""PAD-604 (DragonRR): pictures and clips saved as files of their own with their color
profile baked in ("bake in a file color profile to a video or set of videos and then save
that video, or that set of videos as individual files ... the same also applies to images").

1. core.colour_export: a picture is saved through exactly the profile maths a build uses,
   in its own format, transparency kept; names never clash and never land on a source.
2. A clip is saved through the profile's ffmpeg filters at its own size and frame rate.
3. The Images tab: right-click > Save ... with their color profiles, the More menu's
   "every picture with a profile attached", the project folder refused, a file of the same
   name kept or replaced as asked, nothing in the project changed.
4. The Video tab: the same for clips."""

import os
import subprocess
import time

import pytest

from pinball_decryptor.core import colour_export as ce
from pinball_decryptor.core import colour_profile as cp
from tests.test_webui_images import (_project, _set_folder, _wait, _settled, _by_rel,
                                     BANNER, PLAIN, SPRITE)
from tests.webui_harness import web_app

Image = pytest.importorskip("PIL.Image")

RED = cp.Profile(name="Custom red", gain=(1.0, 0.6, 0.6))
_TABS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                     "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(_TABS, name), encoding="utf-8") as f:
        return f.read()


def _through(prof, rgb):
    import numpy as np
    return tuple(int(v) for v in prof.apply_array(np.array([[rgb]], np.uint8))[0, 0])


def _ffmpeg():
    from pinball_decryptor.core import video
    exe = video.find_ffmpeg()
    if not exe:
        pytest.skip("no ffmpeg")
    return exe


def _clip(path, colour="0x40a0c0", size="64x48", rate=24, secs=1):
    subprocess.run([_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=%s:s=%s:r=%d:d=%d" % (colour, size, rate, secs),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path)], check=True)
    return str(path)


def _frame(path):
    from pinball_decryptor.core import video
    info = video.detect_video_info(path)
    png = video.extract_frame_png(path, 0.5, info.width, info.height)
    import io
    with Image.open(io.BytesIO(png)) as im:
        return info, im.convert("RGB").getpixel((im.width // 2, im.height // 2))


# ---------------------------------------------------------------- 1. core, pictures
def test_a_picture_is_saved_through_the_build_maths(tmp_path):
    src = tmp_path / "pic.png"
    Image.new("RGBA", (6, 4), (200, 150, 100, 77)).save(src)
    dst = tmp_path / "out" / "pic.png"
    dst.parent.mkdir()
    ce.save_image(str(src), str(dst), RED)
    with Image.open(dst) as im:
        assert im.mode == "RGBA" and im.size == (6, 4)
        assert im.getpixel((1, 1)) == _through(RED, (200, 150, 100)) + (77,)
    with Image.open(src) as im:                       # the source is left as it was
        assert im.getpixel((1, 1)) == (200, 150, 100, 77)
    assert os.listdir(dst.parent) == ["pic.png"]      # no part file left behind


def test_formats_kept_where_they_can_be(tmp_path):
    assert ce.image_ext("a/b.JPG") == ".jpg"
    assert ce.image_ext("a/b.dds") == ".png"
    assert ce.video_ext("a/b.webm") == ".webm"
    assert ce.video_ext("a/b.mp4") == ".mp4"
    jpg = tmp_path / "x.jpg"
    Image.new("RGB", (8, 8), (10, 200, 30)).save(jpg)
    out = tmp_path / "y.jpg"
    ce.save_image(str(jpg), str(out), RED)
    with Image.open(out) as im:
        assert im.format == "JPEG"


def test_names_are_numbered_never_a_source(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"x")
    srcs = [str(tmp_path / "one" / "a.png"), str(tmp_path / "two" / "a.png"),
            str(out / "b.png")]
    assert ce.existing("images", srcs, str(out)) == 1          # b.png is a source
    keep = ce.plan_names("images", srcs, str(out))
    assert [os.path.basename(p) for p in keep] == ["a (2).png", "a (3).png", "b (2).png"]
    over = ce.plan_names("images", srcs, str(out), replace=True)
    assert [os.path.basename(p) for p in over] == ["a.png", "a (2).png", "b (2).png"]


def test_save_all_reports_failures_and_stops_on_cancel(tmp_path):
    good = tmp_path / "g.png"
    Image.new("RGB", (4, 4), (90, 90, 90)).save(good)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a picture")
    out = tmp_path / "out"
    out.mkdir()
    items = [("images/g.png", str(good), str(out / "g.png"), RED),
             ("images/bad.png", str(bad), str(out / "bad.png"), RED)]
    seen = []
    res = ce.save_all("images", items, progress_cb=lambda d, t, r: seen.append((d, t)))
    assert [r for r, _d in res["saved"]] == ["images/g.png"]
    assert [r for r, _w in res["failed"]] == ["images/bad.png"]
    assert seen == [(0, 2), (1, 2), (2, 2)] and not res["cancelled"]
    assert sorted(os.listdir(out)) == ["g.png"]
    res = ce.save_all("images", items, cancel_cb=lambda: True)
    assert res["cancelled"] and not res["saved"]


# ---------------------------------------------------------------- 2. core, clips
def test_a_clip_is_saved_through_the_profile_at_its_own_shape(tmp_path):
    src = _clip(tmp_path / "c.mp4")
    dst = str(tmp_path / "out.mp4")
    ok, why = ce.save_video(src, dst, RED)
    assert ok, why
    info0, px0 = _frame(src)
    info, px = _frame(dst)
    assert (info.width, info.height) == (info0.width, info0.height) == (64, 48)
    assert abs(info.fps - 24) < 0.01
    want = _through(RED, px0)
    assert all(abs(a - b) <= 4 for a, b in zip(px, want)), (px0, px, want)
    assert px[1] < px0[1] - 30                       # green really went down
    assert sorted(os.listdir(tmp_path)) == ["c.mp4", "out.mp4"]


# ---------------------------------------------------------------- 3. the Images tab
@pytest.fixture
def scanned(tmp_path):
    assets, reps = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _set_folder(w, assets)
        w.call("images.scan")
        _wait(w, _settled)
        yield w, assets, reps


def _done(w, ns, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if not w.state(ns).get("csave"):
            return
        time.sleep(0.05)
    raise AssertionError("still saving: %r" % w.state(ns).get("csave"))


def test_images_right_click_saves_the_selection(scanned, tmp_path):
    w, assets, reps = scanned
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    assert w.call("images.choose", BANNER) == BANNER
    w.drain()
    cp.store_own_profile(assets, "images", BANNER, RED)
    cp.store_asset_profile(assets, cp.Profile(name="Blue down", gain=(1.0, 1.0, 0.5)))
    sel = [BANNER, PLAIN]
    labels = [i.get("label") for i in w.call("images.menu", BANNER, sel)]
    assert "Save 2 pictures with their color profiles…" in labels
    labels = [i.get("label") for i in w.call("images.menu", PLAIN, [PLAIN])]
    assert "Save this picture with its color profile…" in labels

    # a folder inside the project is refused
    w.answers = [os.path.join(assets, "images")]
    assert w.call("images.act", "csave", BANNER, sel) is False
    assert "outside the project folder" in w.asked[-1]["message"]

    out = tmp_path / "saved"
    out.mkdir()
    before = {p: os.path.getmtime(os.path.join(assets, *p.split("/"))) for p in sel}
    w.answers = [str(out)]
    assert w.call("images.act", "csave", BANNER, sel) is True
    _done(w, "images")
    assert sorted(os.listdir(out)) == ["SpaceGodzilla.png", "backglass.png"]
    # the replacement through its own profile; the game's own through the files profile
    with Image.open(out / "SpaceGodzilla.png") as im:
        assert im.getpixel((3, 3))[:3] == _through(RED, (255, 255, 255))
    with Image.open(out / "backglass.png") as im:
        assert im.getpixel((3, 3)) == _through(cp.asset_profile(assets), (0, 0, 255))
    msg = w.asked[-1]
    assert "Saved 2 pictures with their color profiles into" in msg["message"]
    assert after_same(assets, before)
    assert w.state("images").get("csave") is None

    # again: the same names are there; "No" keeps them and numbers the new ones
    w.answers = [str(out), "no"]
    assert w.call("images.colour_save", sel) is True
    _done(w, "images")
    assert sorted(os.listdir(out)) == ["SpaceGodzilla (2).png", "SpaceGodzilla.png",
                                       "backglass (2).png", "backglass.png"]
    # "Yes" replaces them
    w.answers = [str(out), "yes"]
    assert w.call("images.colour_save", sel) is True
    _done(w, "images")
    assert len(os.listdir(out)) == 4


def after_same(assets, before):
    return all(os.path.getmtime(os.path.join(assets, *p.split("/"))) == t
               for p, t in before.items())


def test_images_more_menu_saves_every_attached_picture(scanned, tmp_path):
    w, assets, reps = scanned
    out = tmp_path / "saved"
    out.mkdir()
    # none attached yet: says so
    assert w.call("images.colour_save") is False
    assert "No picture has a color profile attached" in w.asked[-1]["message"]
    w.answers = [os.path.join(reps, "SpaceGodzilla.png")]
    assert w.call("images.choose", BANNER) == BANNER
    w.answers = [os.path.join(reps, "backglass.jpg")]
    assert w.call("images.choose", PLAIN) == PLAIN
    w.drain()
    cp.store_asset_profile(assets, RED)
    assert w.call("images.set_color", BANNER, True)
    assert w.call("images.set_color", PLAIN, False)
    w.drain()
    assert _by_rel(w.state("images"))[BANNER]["c"] is True
    w.answers = [str(out)]
    assert w.call("images.colour_save", folder=None) is True
    _done(w, "images")
    assert os.listdir(out) == ["SpaceGodzilla.png"]


def test_a_profile_that_changes_nothing_is_not_saved(scanned, tmp_path):
    w, assets, _reps = scanned
    cp.store_asset_profile(assets, cp.Profile(name="No change"))
    assert w.call("images.colour_save", [SPRITE], str(tmp_path)) is False
    assert "changes nothing" in w.asked[-1]["message"]


def test_the_pages_offer_it():
    js = _src("images.js")
    assert 'call("images.colour_save")' in js and 'call("images.colour_save_cancel")' in js
    assert "Save pictures with their color profiles…" in js
    js = _src("video.js")
    assert 'call("video.colour_save", rels)' in js and 'call("video.colour_save", [rel])' in js
    assert 'call("video.colour_save")' in js and 'call("video.colour_save_cancel")' in js
    assert "Save clips with their color profiles…" in js


# ---------------------------------------------------------------- 4. the Video tab
def test_video_saves_clips_with_their_profiles(tmp_path):
    from tests.test_webui_video import _scan
    import hashlib
    proj = tmp_path / "proj"
    (proj / "video").mkdir(parents=True)
    a = _clip(proj / "video" / "attract.mp4", "0x40a0c0")
    b = _clip(proj / "video" / "intro.mp4", "0xc0a040")
    lines = ["%s\t%s\n" % (rel, hashlib.md5(open(p, "rb").read()).hexdigest())
             for rel, p in (("video/attract.mp4", a), ("video/intro.mp4", b))]
    (proj / ".checksums.md5").write_text("".join(lines), encoding="utf-8")
    mine = _clip(tmp_path / "my_boss.mp4", "0x808080")
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers.append(mine)
        assert w.call("video.choose", "video/intro.mp4") is True
        w.drain()
        assert w.call("video.set_color", "video/intro.mp4", True)
        cp.store_own_profile(d, "videos", "video/intro.mp4", RED)
        info = w.call("video.row_menu", ["video/attract.mp4", "video/intro.mp4"])
        assert info["csave"] == "Save 2 clips with their color profiles…"
        assert w.call("video.row_menu", ["video/attract.mp4"])["csave"] == \
            "Save this clip with its color profile…"
        out = tmp_path / "saved"
        out.mkdir()
        # More > every clip with a profile attached: the replaced one only
        w.answers = [str(out)]
        assert w.call("video.colour_save") is True
        _done(w, "video", timeout=120)
        assert os.listdir(out) == ["my_boss.mp4"]
        _i, px = _frame(str(out / "my_boss.mp4"))
        _i, px0 = _frame(mine)
        want = _through(RED, px0)
        assert all(abs(x - y) <= 4 for x, y in zip(px, want)), (px0, px, want)
        # the game's own clip, selected: the individual files profile is still its default,
        # Recommended (the machine screen undone): that is not a file color profile, so
        # nothing is saved (DragonRR: "only file color profiles should ever be saved")
        assert not cp.asset_stored(d) and cp.asset_active(d) is not None
        assert w.call("video.colour_save", ["video/attract.mp4"], str(out)) is False
        assert "no color profile is set for it" in w.asked[-1]["message"]
        # one set, with a whole screen overlay and a machine screen as well: the file
        # color profile alone is baked in
        files = cp.Profile(name="Blue down", gain=(1.0, 1.0, 0.5))
        cp.store_asset_profile(d, files)
        cp.store(d, cp.Profile(name="Overlay", gain=(0.5, 1.0, 1.0)))
        cp.store_screen_profile(d, cp.Profile(name="Screen", gain=(1.0, 0.5, 1.0)))
        assert w.call("video.colour_save", ["video/attract.mp4"], str(out)) is True
        _done(w, "video", timeout=120)
        assert sorted(os.listdir(out)) == ["attract.mp4", "my_boss.mp4"]
        _i, px = _frame(str(out / "attract.mp4"))
        _i, px0 = _frame(a)
        want = _through(files, px0)
        assert all(abs(x - y) <= 4 for x, y in zip(px, want)), (px0, px, want)
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("Saved 1 clip with its color profile into" in t for t in log)
        # one whose profile changes nothing is left out
        cp.store_asset_profile(d, cp.Profile(name="No change"))
        assert w.call("video.colour_save", ["video/attract.mp4"], str(out)) is False
        assert "changes nothing" in w.asked[-1]["message"]


def test_only_the_file_profile_is_saved_never_overlay_or_screen(scanned, tmp_path):
    """DragonRR: the whole screen overlay and the machine screen are the whole screen's,
    never a file's: a saved picture carries its file color profile alone."""
    w, assets, _reps = scanned
    cp.store(assets, cp.Profile(name="Overlay", gain=(0.5, 1.0, 1.0)))
    cp.store_screen_profile(assets, cp.Profile(name="Screen", gain=(1.0, 0.5, 1.0)))
    cp.store_own_profile(assets, "images", PLAIN, RED)
    out = tmp_path / "saved"
    out.mkdir()
    assert w.call("images.colour_save", [PLAIN, SPRITE], str(out)) is True
    _done(w, "images")
    assert os.listdir(out) == ["backglass.png"]
    with Image.open(out / "backglass.png") as im:
        assert im.getpixel((3, 3)) == _through(RED, (0, 0, 255))
    # SPRITE has no profile set: the default individual files profile is Recommended,
    # the machine screen undone, and is not saved
    assert "no color profile is set for it" in w.asked[-1]["message"]
    # a file's own profile that is Recommended, following the screen: not saved either
    cp.store_own_profile(assets, "images", SPRITE, None, follow=True)
    assert w.call("images.colour_save", [SPRITE], str(tmp_path)) is False
    assert "no color profile is set for it" in w.asked[-1]["message"]
