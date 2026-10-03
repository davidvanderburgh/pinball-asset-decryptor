"""PAD-343: colour ranges and curves on every profile, not just the Machine
screen.  The individual files bake them (Pillow, and ffmpeg through .cube
tables), and the Spike 2 whole screen overlay carries them as GLSL after the
fixed slots the multi-boot menu rewrites."""

import os
import re
import subprocess

import pytest

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import shader_profile as sp

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL.Image")

TUNED = cp.parse(cp.SCREEN_DEFAULT_TEXT)[0]          # 2 ranges + 4 curves
ES1 = ("precision mediump float;\nvarying vec2 v;\nuniform sampler2D s;\n"
       "void main(){ gl_FragColor = texture2D(s, v); }")
ES3 = ("#version 300 es\nin highp vec2 v;\nuniform highp sampler2D s;\n"
       "out highp vec4 color;\nvoid main(){ color = texture(s, v); }")


def _pixels(n=64, seed=1):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 256, (n, n, 3), dtype=np.uint8)
    a[0, :16] = np.arange(16)[:, None] * 17          # a grey ramp too
    return a


def test_the_stored_profiles_keep_their_ranges_and_curves(tmp_path):
    d = str(tmp_path)
    cp.store(d, TUNED)
    cp.store_asset_profile(d, TUNED)
    for prof in (cp.for_project(d), cp.active(d), cp.asset_profile(d),
                 cp.asset_active(d)):
        assert prof.ranges == TUNED.ranges and prof.curves == TUNED.curves
    assert "|" in cp.signature(d) and str(TUNED.ranges) in cp.signature(d)


def test_a_profile_without_extras_builds_the_shader_it_always_did():
    plain = TUNED.plain()
    assert sp.extras_glsl(plain) == ""
    assert "pad_cx" not in sp.correction_glsl(plain, True)
    assert sp.extras_glsl(cp.Profile(ranges=(cp.clean_range([205]),))) == ""


def test_the_extras_leave_the_tunable_shape_and_the_readback_alone():
    text = sp.patch_source(ES1, TUNED)
    assert text.count("vec4 pad_cp(") == 1 and "c=pad_cx(c);" in text
    m = sp._FUNC_RE.search(text.encode())
    assert m and sp._TUNABLE_RE.search(m.group(1))
    assert text.index("pad_cx(vec3 c)") < text.index("vec4 pad_cp(")
    back = sp.profile_in(text.encode())
    assert back.gamma == pytest.approx(TUNED.folded().gamma, abs=1e-5)


def test_ffmpeg_bakes_the_ranges_and_curves_like_pillow(tmp_path):
    from pinball_decryptor.core.video import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    a = _pixels(128)
    PIL.fromarray(a).save(tmp_path / "in.png")
    vf = TUNED.ffmpeg_filters()
    assert any(f.startswith("lut3d=") for f in vf)
    assert any(f.startswith("lut1d=") for f in vf)
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i",
                        str(tmp_path / "in.png"), "-vf",
                        ",".join(vf + ["format=rgb24"]),
                        str(tmp_path / "out.png")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    b = np.asarray(PIL.open(tmp_path / "out.png").convert("RGB"), int)
    err = np.abs(TUNED.apply_array(a).astype(int) - b)
    assert err.max() <= 6 and np.percentile(err, 99) <= 3


def test_the_cube_tables_are_written_once_per_profile():
    a, b = TUNED.ffmpeg_filters(), TUNED.ffmpeg_filters()
    assert a == b
    path = re.search(r"lut3d=file='([^']+)'", a[-2]).group(1)
    assert os.path.isfile(path.replace("\\:", ":"))


_PAGE = r"""
async ([vs, fs, w, h, data, webgl2]) => {
  const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const gl = cv.getContext(webgl2 ? "webgl2" : "webgl", {premultipliedAlpha: false});
  if (!gl) return {skip: "no webgl"};
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src);
    gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  gl.useProgram(p);
  const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(p, "pos"); gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(data));
  for (const k of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, k, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.viewport(0, 0, w, h); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  const out = new Uint8Array(w * h * 4); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, out);
  return {px: Array.from(out)};
}
"""
_VS1 = ("attribute vec2 pos; varying vec2 v; void main(){ v = pos * 0.5 + 0.5;"
        " gl_Position = vec4(pos, 0.0, 1.0); }")
_VS3 = ("#version 300 es\nin vec2 pos; out highp vec2 v; void main(){ v = pos * 0.5 + 0.5;"
        " gl_Position = vec4(pos, 0.0, 1.0); }")


def _render(page, fs, a, webgl2):
    h, w = a.shape[:2]
    rgba = np.concatenate([a, np.full((h, w, 1), 255, np.uint8)], -1)
    res = page.evaluate(_PAGE, [_VS3 if webgl2 else _VS1, fs, w, h,
                                rgba.reshape(-1).tolist(), webgl2])
    if "skip" in res:
        pytest.skip(res["skip"])
    return np.array(res["px"], np.uint8).reshape(h, w, 4)[..., :3]


def test_the_overlay_shader_draws_what_pillow_bakes():
    """Compiles the patched ES 1.00 and ES 3.00 shaders in a real browser's
    WebGL and compares every pixel with the profile through numpy."""
    sync_api = pytest.importorskip("playwright.sync_api")
    a = _pixels()
    want = TUNED.apply_array(a).astype(int)
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
        page = browser.new_page()
        for src, es3 in ((ES1, False), (ES3, True)):
            fs = sp.patch_source(src, TUNED)
            got = _render(page, fs, a, es3).astype(int)
            err = np.abs(got - want)
            assert err.max() <= 4 and np.percentile(err, 99) <= 2, (
                es3, err.max(), np.percentile(err, 99))
        browser.close()
    finally:
        pw.stop()
