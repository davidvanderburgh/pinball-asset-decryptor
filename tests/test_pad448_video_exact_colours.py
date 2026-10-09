"""PAD-448 (DragonRR): "Color profiling by file doesn't appear to affect the appearance
of videos in comparison mode or on the main screen ... ideally the videos should be
affected in exactly the same way as the Scenes images".

- The players drew through an SVG filter, which has no form for a profile's colour
  ranges: a profile made of them changed nothing.  Each player now gets a colour table
  worked out with the picture maths (core/colour_profile.py video_look_exact +
  build_look_lut), drawn on the GPU (static/js/tabs/video_gl.js).
- A game's own clip with its profile attached (Advanced) showed it nowhere on the main
  players, and a Compare player stayed on its Original: the Replacement player now shows
  it "With its color profile", and a Compare player turns to that when it is attached.
- Compare has the Advanced box, and a mark on each clip that is the game's own (locked
  or not)."""

import os
import re
import time

import pytest

from pinball_decryptor.core import colour_profile as cp
from tests.test_webui_video import _mine, _project, _scan
from tests.webui_harness import web_app

np = pytest.importorskip("numpy")

A, B, C = "video/attract.mp4", "video/intro.mp4", "video/sub/boss.mp4"
# a profile made of one colour range alone: blues turned toward violet
VIOLET = cp.Profile(name="Blue to violet",
                    ranges=((215.0, 100.0, 30.0, 75.0, 1.3, 1.0, 0.1),))
WARM = cp.Profile(name="Warm", gain=(1.2, 1.0, 0.85), saturation=1.2)
SCREEN = cp.Profile(name="My screen", gamma=(1.1, 1.0, 0.9),
                    ranges=((30.0, 40.0, 20.0, 0.0, 0.9, 1.0, 0.05),),
                    curves=(("g", ((0.0, 0.0), (128.0, 120.0), (255.0, 255.0))),))

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js", "tabs")


def _src(name):
    with open(os.path.join(_JS, name), encoding="utf-8") as f:
        return f.read()


def _frame():
    """Greys, full colours, skies and seas, every hue at two strengths."""
    rng = np.random.default_rng(448)
    a = rng.integers(0, 256, (40, 64, 3)).astype(np.uint8)
    hue = np.linspace(0, 1, 64, endpoint=False)
    for row, (s, v) in enumerate(((1.0, 1.0), (0.5, 0.8), (0.9, 0.5))):
        k = (np.stack([hue + 1 / 3, hue, hue - 1 / 3], -1) * 6) % 6
        rgb = v * (1 - s * np.clip(np.minimum(np.abs(k - 3) - 1, 1), 0, 1))
        a[row] = np.round((1 - rgb) * 255).astype(np.uint8)
    a[3] = np.repeat(np.arange(0, 256, 4, dtype=np.uint8)[:, None], 3, -1)
    return a


def _project_with(d, overlay=None, screen=None, follow=False, files=None):
    if overlay is not None:
        cp.store(d, overlay)
    if screen is not None or follow:
        cp.store_screen_profile(d, screen, follow=follow)
    if files is not None:
        cp.store_asset_profile(d, files)


# ------------------------------------------------------------- the maths
@pytest.mark.parametrize("follow", [False, True])
def test_the_exact_steps_are_the_scenes_maths(tmp_path, follow):
    """A player's steps, run on a frame, give what the Scenes preview draws: the
    original through machine_view, a clip with its profile on as a picture baked with
    it and then viewed, a switched-off one past the screen (the gear menu's setting)."""
    d = str(tmp_path)
    _project_with(d, overlay=WARM, screen=None if follow else SCREEN, follow=follow,
                  files=cp.Profile(name="Files", gamma=(1.2, 1.1, 1.0)))
    cp.store_own_profile(d, "videos", A, VIOLET)
    a = _frame()
    view = cp.machine_view(d)
    ex = cp.video_look_exact(d, True, False, rel=A)
    assert np.array_equal(cp.run_steps(ex["orig"], a), view(a))
    assert np.array_equal(cp.run_steps(ex["rep"], a), view(VIOLET.apply_array(a)))
    assert ex["rep"][0] == ("apply", VIOLET)
    # the screen as Scenes has it: undoing the files profile when it follows
    assert ex["orig"][-1][0] == ("undo" if follow else "apply")
    off = cp.video_look_exact(d, False, True, rel=A)
    assert np.array_equal(cp.run_steps(off["rep"], a), view.overlay(a))
    # the preview's three switches each leave their own step out
    none = cp.video_look_exact(d, True, False, overlay_on=False, files_on=False,
                               screen_on=False, rel=A)
    assert none == {"orig": [], "rep": []}


def test_the_colour_table_is_the_maths_at_every_5th_level(tmp_path):
    d = str(tmp_path)
    _project_with(d, screen=SCREEN)
    steps = cp.video_look_exact(d, True, False, rel=None)["orig"]
    cp.store_own_profile(d, "videos", A, VIOLET)
    rep = cp.video_look_exact(d, True, False, rel=A)["rep"]
    assert cp.look_lut_path([]) is None and cp.build_look_lut([]) is None
    p1, p2 = cp.build_look_lut(steps), cp.build_look_lut(rep)
    assert p1 != p2 and p1 == cp.look_lut_path(steps)
    assert cp.build_look_lut(list(steps)) == p1          # written once, by its numbers
    n = cp.LOOK_LUT_SIZE
    raw = np.fromfile(p2, np.uint8)
    assert raw.size == n ** 3 * 3
    lut = raw.reshape(n, n, n, 3)                        # [blue][green][red]
    for r, g, b in ((0, 0, 0), (255, 255, 255), (40, 90, 230), (200, 35, 10), (125, 125, 125)):
        want = cp.run_steps(rep, np.array([[[r, g, b]]], np.uint8))[0, 0]
        assert list(lut[b // 5, g // 5, r // 5]) == list(want)
    # the colour range is in it: a blue goes violet, which a browser filter never drew
    blue = np.array([[[40, 90, 230]]], np.uint8)
    plain = cp.run_steps([(k, p.plain()) for k, p in rep], blue)[0, 0]
    assert int(lut[230 // 5, 90 // 5, 40 // 5][0]) - int(plain[0]) > 40


def test_only_the_newest_tables_are_kept(tmp_path, monkeypatch):
    """Every slider position dragged writes a table: the temp folder keeps the newest."""
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(cp, "LOOK_LUT_KEEP", 3)
    paths = [cp.build_look_lut([("apply", cp.Profile(gamma=(1 + i / 10, 1.0, 1.0)))])
             for i in range(6)]
    left = sorted(os.listdir(tmp_path / "pad_colour_luts"))
    assert len(left) == 3 and os.path.basename(paths[-1]) in left
    # one gone is written again when it is asked for
    again = cp.build_look_lut([("apply", cp.Profile(gamma=(1.0, 1.0, 1.0), gain=(1.1, 1, 1)))])
    assert os.path.isfile(again)


# ------------------------------------------------------------ in a browser
_PAGE = r"""
async ([vs, fs, w, h, img, n, lut]) => {
  const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const gl = cv.getContext("webgl2", {premultipliedAlpha: false});
  if (!gl) return {skip: "no webgl2"};
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src);
    gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  gl.useProgram(p);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(p, "p"); gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  for (const [unit, target] of [[0, gl.TEXTURE_2D], [1, gl.TEXTURE_3D]]) {
    gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(target, gl.createTexture());
    gl.texParameteri(target, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(target, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    for (const k of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(target, k, gl.CLAMP_TO_EDGE);
  }
  gl.activeTexture(gl.TEXTURE0);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, w, h, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array(img));
  gl.activeTexture(gl.TEXTURE1);
  gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB8, n, n, n, 0, gl.RGB, gl.UNSIGNED_BYTE, new Uint8Array(lut));
  gl.uniform1i(gl.getUniformLocation(p, "src"), 0);
  gl.uniform1i(gl.getUniformLocation(p, "lut"), 1);
  gl.uniform1f(gl.getUniformLocation(p, "n"), n);
  gl.viewport(0, 0, w, h); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  const out = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, out);
  return {px: Array.from(out)};
}
"""


def test_the_player_draws_a_frame_as_scenes_would(tmp_path):
    """video_gl.js's own shaders in a real browser's WebGL 2, given a frame and the table
    Python wrote: every pixel against the picture maths (the one place the two could
    disagree is the table's layout and the blend between its points)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    d = str(tmp_path)
    _project_with(d, screen=cp.SCREEN_PRESETS[0][1])
    cp.store_own_profile(d, "videos", A, VIOLET)
    steps = cp.video_look_exact(d, True, False, rel=A)["rep"]
    n = cp.LOOK_LUT_SIZE
    lut = np.fromfile(cp.build_look_lut(steps), np.uint8)
    src = _src("video_gl.js")
    vs = re.search(r"const VERT = `([^`]*)`", src).group(1)
    fs = re.search(r"const FRAG = `([^`]*)`", src).group(1)
    a = _frame()
    h, w = a.shape[:2]
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:                              # noqa: BLE001
        pytest.skip("no playwright: %s" % e)
    try:
        browser = None
        for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                browser = pw.chromium.launch(**kw)
                break
            except Exception:                           # noqa: BLE001
                continue
        if browser is None:
            pytest.skip("no browser")
        res = browser.new_page().evaluate(_PAGE, [vs, fs, w, h, a.reshape(-1).tolist(), n,
                                                  lut.tolist()])
        browser.close()
    finally:
        pw.stop()
    if "skip" in res:
        pytest.skip(res["skip"])
    # read back bottom row first; the shader puts the frame's top row at the top
    got = np.array(res["px"], np.uint8).reshape(h, w, 4)[::-1, :, :3].astype(int)
    want = cp.run_steps(steps, a).astype(int)
    err = np.abs(got - want)
    assert err.mean() < 1.0 and np.percentile(err, 99) <= 4, (
        err.mean(), np.percentile(err, 99), err.max())
    # and the colour range shows: the browser filter's maths (no ranges) is far off
    plain = cp.run_steps([(k, p.plain()) for k, p in steps], a).astype(int)
    assert np.abs(plain - want).max() > 60


# ------------------------------------------------------------ the tab
def _wait_for(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        st = w.state("video")
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError("timed out: look %r compare %r" % (
        w.state("video").get("look"), w.state("video").get("compare")))


def test_the_players_get_their_exact_colour_tables(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_own_profile(d, "videos", A, VIOLET)
        w.answers.append(str(mine))
        assert w.call("video.choose", A) is True
        assert w.call("video.set_color", A, True)
        assert w.call("video.select", A)
        video = w.window.service("video")
        own = w.run(video._own_colours)
        ex = cp.video_look_exact(d, True, own, rel=A)
        want = {"orig": cp.look_lut_path(ex["orig"]), "rep": cp.look_lut_path(ex["rep"])}
        st = _wait_for(w, lambda s: s["look"].get("lut") == want)
        lut = st["look"]["lut"]
        assert all(os.path.isfile(p) for p in lut.values())
        # the SVG filter's steps stay: the stand-in where WebGL is missing
        assert st["look"]["rep"] and st["look"]["rep"][0] == cp.filter_step(VIOLET)
        # Compare's players get theirs too
        assert w.call("video.compare_open", [A, B]) == 2
        st = _wait_for(w, lambda s: all(t.get("lut") for t in s["compare"]["tiles"]))
        a_tile, b_tile = st["compare"]["tiles"]
        assert a_tile["lut"] == lut["rep"]
        assert b_tile["lut"] == cp.look_lut_path(cp.video_look_exact(d, None, own, rel=B)["orig"])
        # all three Preview colors switches off: nothing to draw through
        assert w.call("video.set_machine_look", False)
        st = _wait_for(w, lambda s: s["look"]["lut"] == {"orig": None, "rep": None})
        assert [t["lut"] for t in st["compare"]["tiles"]] == [None, None]


def test_a_games_own_clip_shows_its_profile_on_its_original_player(tmp_path):
    """PAD-448 showed it on the Replacement player; PAD-462 (DragonRR: "confusing from a UX
    perspective") shows it on its own player, the Original, and leaves the other empty."""
    proj = _project(tmp_path)
    d = str(proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        cp.store_own_profile(d, "videos", C, WARM)
        assert w.call("video.select", C)
        w.drain()
        rep = w.state("video")["preview"]["rep"]
        assert rep["title"] == "Replacement" and not rep.get("path")
        assert w.call("video.set_color_stock", True)
        assert w.call("video.set_color", C, True)
        w.drain()
        pv = w.state("video")["preview"]
        assert pv["rep"]["title"] == "Replacement" and not pv["rep"].get("path")
        assert "Original player" in pv["rep"]["hint"]
        assert os.path.normcase(pv["orig"]["path"]) == os.path.normcase(str(proj / C))
        assert not pv["can_clear"] and not pv["has_pick"]
        own = w.run(w.window.service("video")._own_colours)
        want = cp.look_lut_path(cp.video_look_exact(d, True, own, rel=C)["rep"])
        look = _wait_for(w, lambda s: (s["look"].get("lut") or {}).get("orig") == want)["look"]
        assert look["orig"][0] == cp.filter_step(WARM)
        assert look["views"]["orig"]["view"] == "profile"
        # detached: the Original player is the clip as it is; Advanced unticked: the same
        assert w.call("video.set_color", C, False)
        w.drain()
        assert w.state("video")["look"]["views"]["orig"]["view"] == "plain"
        assert w.call("video.set_color", C, True)
        w.drain()
        assert w.state("video")["look"]["views"]["orig"]["view"] == "profile"
        assert w.call("video.set_color_stock", False)
        w.drain()
        rep = w.state("video")["preview"]["rep"]
        assert rep["title"] == "Replacement" and not rep.get("path")
        assert w.state("video")["look"]["views"]["orig"]["view"] == "plain"


def test_a_compare_player_turns_to_the_profile_attached_to_it(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        assert w.call("video.choose", A) is True
        assert w.call("video.compare_open", [A, B, C]) == 3

        def tiles():
            w.drain()
            return [(t["rel"], t["side"]) for t in w.state("video")["compare"]["tiles"]]

        assert tiles() == [(A, "rep"), (B, "orig"), (C, "orig")]
        rows = {r["rel"]: r for r in w.state("video")["rows"]}
        assert rows[B]["col_lock"] and rows[C]["col_lock"] and not rows[A]["col_lock"]
        assert w.call("video.set_color_stock", True)
        rows = {r["rel"]: r for r in w.state("video")["rows"]}
        assert rows[C]["col_stock"] and not rows[C]["col_lock"]
        assert w.call("video.set_color", C, True)
        assert tiles() == [(A, "rep"), (B, "orig"), (C, "rep")]
        # turned back by hand, it stays there
        cid = w.state("video")["compare"]["tiles"][2]["id"]
        assert w.call("video.compare_side", cid, "orig")
        assert w.call("video.set_color", B, True)
        assert tiles() == [(A, "rep"), (B, "rep"), (C, "orig")]


@pytest.mark.parametrize("needle", [
    'class="vcm-adv"',                                    # Advanced in Compare's head
    "<${CmpBadge} row=${row} cs=${cs} />",               # a mark on each clip
    '<${Icon} name="lock" />Locked',
    "lut=${t.lut || null} onLive=${setGlLive}",          # Compare's players drawn exactly
    "lut=${lut} onLive=${setGlLive}",                    # and the two on the list
    "steps.length && !glLive",                           # the SVG filter only stands in
])
def test_the_page_wires_it(needle):
    assert needle in _src("video.js")


def test_compare_and_the_list_both_have_the_advanced_box():
    assert _src("video.js").count('call("video.set_color_stock", v)') == 2


@pytest.mark.parametrize("needle", [
    "gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB8, n, n, n",
    "requestVideoFrameCallback",                          # every frame as it plays
    'addEventListener(ev, fn)',
    "WEBGL_lose_context",                                  # a player gone gives its context back
])
def test_the_gl_player_wiring(needle):
    assert needle in _src("video_gl.js")
