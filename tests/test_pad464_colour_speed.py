"""PAD-464 (DragonRR): "Color profiling is very slow again ... having to wait for results
is painful".

- One slider move in the Colors bar read and parsed the project's .staged_changes.json some
  90 to 150 times, and every file's own profile again with each read: most of a second with
  the window waiting, on a project whose files carry profiles of their own.  The file is now
  parsed once and kept until it changes on disk (core/staged_changes.py peek / derived), and
  so are the profiles in it.
- A slider move redrew every row of the Images and Video lists, which show the switches
  alone: now only the "every replaced" box moving does.
- The colour maths (Scenes preview, the Images panes, the Video players' tables, a Write)
  runs a whole run of profiles once per distinct colour, finds those colours through a table
  on a big frame, works a colour range out only where it reaches, keeps each profile's
  256-entry tables, and evaluates a curve all at once: the same numbers, bit for bit."""

import json
import os
import time

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes

np = pytest.importorskip("numpy")

SCREEN = cp.SCREEN_PRESETS[0][1]
HARD = cp.Profile(name="Hard", saturation=0.7, brightness=1.1, contrast=1.3,
                  gain=(1.1, 0.95, 1.0), lift=(0.02, 0.0, 0.01),
                  ranges=((0.0, 50.0, 0.0, -30.0, 0.5, 1.7, 0.0),
                          (120.0, 360.0, 0.0, 10.0, 1.4, 0.8, 0.3),
                          (205.0, 60.0, 30.0, 12.0, 0.9, 1.2, 0.15)),
                  curves=(("rgb", ((0.0, 10.0), (100.0, 90.0), (255.0, 240.0))),
                          ("b", ((0.0, 0.0), (128.0, 150.0), (255.0, 255.0)))))


def _frame(h, w, seed=464):
    """Flat areas, gradients and noise: some colours many times over, some once."""
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 256, (h, w, 3)).astype(np.uint8)
    a[: h // 3] = rng.integers(0, 256, (1, 1, 3))
    ramp = np.linspace(0, 255, w).astype(np.uint8)
    a[h // 3: h // 2, :, 0] = ramp
    a[h // 3: h // 2, :, 1] = ramp[::-1]
    a[h // 2: h // 2 + 8] = np.repeat(ramp[:, None], 3, -1)       # greys
    return a


# -- the maths: the same numbers --------------------------------------------------------

@pytest.mark.parametrize("shape", [(3, 5), (90, 60), (700, 500)])
def test_a_run_of_profiles_per_colour_is_the_maths_pixel_by_pixel(shape):
    """run_steps (and apply_array / undo_array) on a frame, the big one through the colour
    table, give exactly what each pixel worked out on its own gives."""
    a = _frame(*shape)
    rec = cp.undo_screen(SCREEN)
    steps = [("apply", rec), ("apply", HARD), ("undo", cp.PRESETS[0][1]), ("apply", SCREEN)]
    want = cp._steps_px(steps, a)
    assert np.array_equal(cp.run_steps(steps, a), want)
    for prof in (rec, HARD, SCREEN):
        assert np.array_equal(prof.apply_array(a), prof._apply_px(a))
        assert np.array_equal(prof.undo_array(a), prof._undo_px(a))
        assert np.array_equal(prof.extras_array(a), prof._extras_px(a))


def test_a_mostly_black_frame_and_a_remembering_view_give_the_same_numbers():
    """The empty part of a Scenes layer is black: black is worked out once.  A view kept
    for a whole render (or a Play) remembers the colours it worked out: again, the same
    numbers, frame after frame."""
    steps = [("apply", HARD), ("apply", SCREEN)]
    big = _frame(700, 500)
    sparse = np.zeros_like(big)
    sparse[100:160, 50:300] = big[100:160, 50:300]
    empty = np.zeros_like(big)
    moved = np.ascontiguousarray(np.roll(big, 37, axis=1))
    memo = cp._Memo(steps)
    for a in (big, sparse, empty, moved, big[:20, :30], sparse):
        want = cp._steps_px(steps, a)
        assert np.array_equal(cp.run_steps(steps, a), want)
        assert np.array_equal(memo(a), want)
    assert memo.known[0].size > 1000
    view = cp.machine_view("")                    # no project: the Recommended screen
    assert isinstance(view, cp._Memo) and view.overlay is None
    assert np.array_equal(view(big), cp._steps_px([("apply", SCREEN)], big))


def _viewed_before(canvas, view):
    """scene_render.viewed as it was before PAD-464."""
    a = canvas[..., 3:4].astype(np.float32)
    cov = np.maximum(a, 1.0)
    straight = np.clip(canvas[..., :3].astype(np.float32) * 255.0 / cov + 0.5,
                       0, 255).astype(np.uint8)
    shown = np.asarray(view(straight), np.float32)
    out = canvas.copy()
    out[..., :3] = np.clip(shown * a / 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def test_a_layer_viewed_where_it_is_drawn_gives_the_same_numbers():
    """viewed works the view out only where a pixel is drawn, and the cover sums only where
    it is partly drawn: solid, partly drawn and empty pixels (an additive glow leaves colour
    in an empty one) come out as before."""
    from pinball_decryptor.plugins.stern.scene_render import viewed
    rng = np.random.default_rng(4641)
    views = [cp._Memo([("apply", HARD), ("apply", SCREEN)]),
             lambda rgb: np.clip(rgb.astype(int) * 2, 0, 255).astype(np.uint8)]
    for k in range(16):
        c = rng.integers(0, 256, (int(rng.integers(1, 120)), int(rng.integers(1, 120)), 4))
        c = c.astype(np.uint8)
        if k % 4 == 0:
            c[..., 3] = 255
        elif k % 4 == 1:
            c[..., 3] = rng.choice([0, 1, 128, 254, 255], c.shape[:2])
        elif k % 4 == 2:
            c[..., 3] = 0
        for view in views:
            assert np.array_equal(viewed(c, view), _viewed_before(c, view))
    layer = np.zeros((300, 400, 4), np.uint8)
    layer[50:90, 20:300] = (120, 60, 30, 255)
    layer[90:95, 20:300] = (60, 30, 15, 128)
    for view in views:
        assert np.array_equal(viewed(layer, view), _viewed_before(layer, view))


def test_the_colour_table_finds_the_same_colours_as_a_sort():
    a = _frame(700, 500)
    cols, inv = cp._unique_colours(a)
    assert a.reshape(-1, 3).shape[0] >= cp._TABLE_FROM
    flat = a.reshape(-1, 3)
    want = np.unique(flat, axis=0)
    assert np.array_equal(cols, want)
    assert np.array_equal(cols[inv], flat)


def _ranges_one_by_one(rgb, ranges):
    """The colour ranges as they were worked out before PAD-464 (every pixel through every
    sum), to hold the faster one to."""
    out = np.asarray(rgb, np.float64)
    for hue, width, soft, shift, sat, bright, protect in ranges:
        if cp.range_neutral((hue, width, soft, shift, sat, bright, protect)):
            continue
        r, g, b = out[..., 0], out[..., 1], out[..., 2]
        mx, mn = out.max(-1), out.min(-1)
        c = mx - mn
        safe = np.where(c > 0, c, 1.0)
        h = np.where(mx == r, ((g - b) / safe) % 6.0,
                     np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0)) * 60.0
        s = np.where(mx > 0, c / np.where(mx > 0, mx, 1.0), 0.0)
        dist = np.abs((h - hue + 180.0) % 360.0 - 180.0)
        half = width / 2.0
        if width >= 360.0:
            hw = np.ones_like(h)
        elif soft > 0:
            hw = cp._smooth(1.0 - (dist - half) / soft)
        else:
            hw = (dist <= half).astype(np.float64)
        gw = cp._smooth(c / 255.0 / protect) if protect > 0 else (c > 0).astype(np.float64)
        w = np.where(c > 0, hw * gw, 0.0)
        h2 = (h + shift * w) % 360.0
        s2 = np.clip(s * (1.0 + (sat - 1.0) * w), 0.0, 1.0)
        v2 = np.clip(mx * (1.0 + (bright - 1.0) * w), 0.0, 255.0)
        chans = []
        for n in (5.0, 3.0, 1.0):
            k = (n + h2 / 60.0) % 6.0
            chans.append(v2 - v2 * s2 * np.clip(np.minimum(k, 4.0 - k), 0, 1))
        out = np.where((w > 0)[..., None], np.stack(chans, -1), out)
    return out


def test_ranges_where_they_reach_give_the_same_numbers_and_leave_the_input_be():
    rng = np.random.default_rng(4640)
    for i in range(60):
        rs = [cp.clean_range([rng.random() * 360, rng.random() * 360,
                              rng.random() * 90 * (i % 4 != 0), rng.random() * 360 - 180,
                              rng.random() * 3, rng.random() * 3,
                              rng.random() * (i % 5 != 0)])
              for _ in range(1 + i % 3)]
        a = rng.integers(0, 256, (400, 3)).astype(np.float64)
        a[:40] = a[:40, :1]                                   # greys
        if i % 2:
            a = a.reshape(20, 20, 3)
        keep = a.copy()
        assert np.array_equal(cp.apply_ranges(a, rs), _ranges_one_by_one(a, rs))
        assert np.array_equal(a, keep)                        # the caller's array untouched


def _curve_one_by_one(points, inputs):
    """curve_values before PAD-464: one input at a time."""
    import bisect
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    n = len(xs)
    d = [(ys[k + 1] - ys[k]) / (xs[k + 1] - xs[k]) for k in range(n - 1)]
    m = [0.0] * n
    m[0], m[n - 1] = d[0], d[n - 2]
    for k in range(1, n - 1):
        m[k] = (d[k - 1] + d[k]) / 2.0 if d[k - 1] * d[k] > 0 else 0.0
    for k in range(n - 1):
        if d[k] == 0.0:
            m[k] = m[k + 1] = 0.0
            continue
        a, b = m[k] / d[k], m[k + 1] / d[k]
        r = a * a + b * b
        if r > 9.0:
            t = 3.0 / r ** 0.5
            m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    out = []
    for v in inputs:
        if v <= xs[0]:
            y = ys[0]
        elif v >= xs[n - 1]:
            y = ys[n - 1]
        else:
            k = bisect.bisect_left(xs, v) - 1
            h = xs[k + 1] - xs[k]
            t = (v - xs[k]) / h
            t2, t3 = t * t, t * t * t
            y = ((2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * h * m[k]
                 + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * h * m[k + 1])
        out.append(y)
    return out


def test_a_curve_all_at_once_is_the_curve_one_input_at_a_time():
    rng = np.random.default_rng(46)
    for i in range(300):
        n = int(rng.integers(2, cp.MAX_POINTS + 1))
        xs = np.sort(rng.choice(np.arange(256), n, replace=False)).astype(float)
        ys = rng.random(n) * 255
        if i % 3 == 0:
            ys = np.sort(ys)
        pts = tuple(zip(xs.tolist(), ys.tolist()))
        for inputs in (range(256), list(rng.random(200) * 300 - 20)):
            assert cp.curve_values(pts, inputs) == _curve_one_by_one(pts, inputs)
    assert cp.curve_values(((0.0, 0.0), (255.0, 255.0)), []) == []


def test_tables_kept_per_profile_and_a_list_made_profile_still_works():
    a = _frame(30, 40)
    listed = cp.Profile(name="Lists", gamma=[1.2, 1.0, 0.9], gain=[1.0, 1.1, 1.0],
                        lift=[0.0, 0.0, 0.0])
    tupled = cp.Profile(name="Tuples", gamma=(1.2, 1.0, 0.9), gain=(1.0, 1.1, 1.0))
    assert np.array_equal(listed.apply_array(a), tupled.apply_array(a))
    luts = cp._shade_luts(tupled.curve())
    assert luts is cp._shade_luts(tupled.curve())
    with pytest.raises(ValueError):
        luts[0, 0] = 1                                        # shared: read-only


# -- the project's file, read once ------------------------------------------------------

def test_the_file_is_parsed_once_and_each_load_is_the_callers_own(tmp_path, monkeypatch):
    d = str(tmp_path)
    staged_changes.save(d, {"image": {"images/a.png": "x"}, "n": 1})
    parsed = []
    real = staged_changes._parsed
    monkeypatch.setattr(staged_changes, "_parsed", lambda raw: parsed.append(1) or real(raw))
    one = staged_changes.load(d)
    one["image"]["images/b.png"] = "y"
    one["n"] = 2
    assert staged_changes.load(d) == {"image": {"images/a.png": "x"}, "n": 1}
    assert staged_changes.peek(d) is staged_changes.peek(d)
    for _ in range(50):
        staged_changes.load(d)
        staged_changes.peek(d)
    assert parsed == []                                       # save() kept what it wrote


def test_a_change_made_behind_its_back_is_seen_even_in_the_same_tick(tmp_path):
    """Another program (or a test) writing the file the same size in the same clock tick
    keeps its time and size: the bytes are compared then."""
    d = str(tmp_path)
    side = os.path.join(d, staged_changes.SIDE_CAR)
    staged_changes.save(d, {"color_all_images": True, "v": "a"})
    assert staged_changes.peek(d)["v"] == "a"
    st = os.stat(side)
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"color_all_images": True, "v": "b"}, f, indent=2)
    os.utime(side, ns=(st.st_atime_ns, st.st_mtime_ns))         # the same stamp
    assert os.stat(side).st_size == st.st_size
    assert staged_changes.peek(d)["v"] == "b"
    assert staged_changes.load(d)["v"] == "b"
    os.remove(side)
    assert staged_changes.load(d) == {} and staged_changes.peek(d) == {}


def test_an_old_file_is_trusted_by_its_stamp(tmp_path, monkeypatch):
    d = str(tmp_path)
    side = os.path.join(d, staged_changes.SIDE_CAR)
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"v": 1}, f)
    old = time.time() - 60
    os.utime(side, (old, old))
    assert staged_changes.peek(d) == {"v": 1}
    reads = []
    real_open = open

    def spy(path, *a, **k):
        if os.path.normcase(str(path)) == os.path.normcase(side):
            reads.append(path)
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", spy)
    for _ in range(20):
        staged_changes.peek(d)
        staged_changes.load(d)
    assert reads == []                                        # not even read again


def test_derived_follows_the_file(tmp_path):
    d = str(tmp_path)
    staged_changes.save(d, {"n": 2})
    built = []

    def build(data):
        built.append(1)
        return data.get("n", 0) * 10
    assert staged_changes.derived(d, "x", build) == 20
    assert staged_changes.derived(d, "x", build) == 20
    assert len(built) == 1
    staged_changes.save(d, {"n": 3})
    assert staged_changes.derived(d, "x", build) == 30
    assert staged_changes.derived("", "x", build) == 0


def test_own_profiles_parsed_once_and_kept_across_a_change_elsewhere(tmp_path, monkeypatch):
    """Hundreds of files with a profile of their own (an Apply to all): a look-up does not
    parse them again, nor does a change to the file that leaves them as they were."""
    d = str(tmp_path)
    mine = cp.Profile(name="Mine", gamma=(1.1, 1.0, 0.9),
                      ranges=((30.0, 40.0, 20.0, 5.0, 0.9, 1.0, 0.05),),
                      curves=(("g", ((0.0, 0.0), (128.0, 120.0), (255.0, 255.0))),))
    rels = ["images/p%03d.png" % i for i in range(200)]
    cp.store_own_profiles(d, "images", rels, mine)
    cp.store_own_profile(d, "images", "images/rec.png", None, follow=True)
    calls = []
    real = cp._from_dict
    monkeypatch.setattr(cp, "_from_dict", lambda x: calls.append(1) or real(x))
    resolve = cp.asset_resolver(d)
    assert resolve("images", rels[7]) == mine
    assert resolve("images", "images/rec.png") == cp.recommended(d, files=True)
    names = cp.own_profile_names(d)
    assert names["images"][rels[0]] == "Mine"
    assert cp.own_profile(d, "images", rels[3]) == mine
    first = len(calls)
    assert first <= len(rels) + 5
    for _ in range(10):
        cp.asset_resolver(d)("images", rels[1])
        cp.own_profile_names(d)
        cp.own_profile(d, "images", rels[2])
    assert len(calls) == first                                # parsed once
    cp.set_asset_all(d, "images", True)                       # the file changes elsewhere
    assert cp.asset_resolver(d)("images", rels[1]) == mine
    assert len(calls) <= first + 5                            # the own ones kept


# -- a slider move ----------------------------------------------------------------------

def test_a_slider_move_parses_the_file_once_and_leaves_the_lists_be(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    d = str(proj)
    mine = cp.Profile(name="Mine", gamma=(1.1, 1.0, 0.9),
                      ranges=((30.0, 40.0, 20.0, 5.0, 0.9, 1.0, 0.05),))
    cp.store_own_profiles(d, "images", ["images/p%03d.png" % i for i in range(150)], mine)
    cp.store_own_profiles(d, "videos", ["video/v%03d.mp4" % i for i in range(50)], mine)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", d)
        w.call("ui.select_tab", "scenes")
        w.drain()
        w.call("color.panel_open")
        w.drain()
        images, video = w.window.service("images"), w.window.service("video")
        redrawn = []
        monkeypatch.setattr(images, "_publish_chunks",
                            lambda *a, **k: redrawn.append("images"))
        monkeypatch.setattr(video, "_refresh_list", lambda *a, **k: redrawn.append("video"))
        parsed, profiles = [], []
        real_parse, real_dict = staged_changes._parsed, cp._from_dict
        monkeypatch.setattr(staged_changes, "_parsed",
                            lambda raw: parsed.append(1) or real_parse(raw))
        monkeypatch.setattr(cp, "_from_dict", lambda x: profiles.append(1) or real_dict(x))
        for mode in ("assets", "display", "screen"):
            assert w.call("color.set_mode", mode) == mode
            for g in (0.9, 0.95):
                parsed.clear()
                profiles.clear()
                w.call("color.set_params", {"gain": [g, 1.0, 1.0]})
                w.drain()
                assert len(parsed) <= 2, (mode, len(parsed))         # was ~100 reads
                assert len(profiles) <= 10, (mode, len(profiles))    # not the 200 own ones
        assert redrawn == []
        assert cp.screen_profile(d).gain == (0.95, 1.0, 1.0)
        # the "every replaced picture" box moving does redraw the rows
        assert w.call("color.set_all", "images", True)
        w.drain()
        assert "images" in redrawn
