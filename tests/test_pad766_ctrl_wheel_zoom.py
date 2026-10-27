"""PAD-766: Ctrl (or Cmd) + the mouse wheel zooms the whole app, a step per
wheel notch, like Ctrl +/- (the zoom Python keeps in settings).  A touchpad's
small pinch deltas add up to a step; a plain wheel still scrolls; a view with
a wheel zoom of its own (the Scenes picture calls preventDefault) keeps it;
and quick notches each take a step even before Python's answer is back."""

import json
import os
import re
import shutil
import subprocess

import pytest

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js")

_GLOBALS = r"""
const noop = () => {};
const el = () => ({ style: {}, classList: { toggle: noop }, appendChild: noop });
globalThis.window = { addEventListener: noop, innerWidth: 1360, innerHeight: 900,
                      matchMedia: () => ({ matches: false }) };
globalThis.document = { documentElement: el(), head: el(), createElement: el };
globalThis.__calls = [];
"""

_RUN = r"""
await import("./globals.js");
const { onZoomWheel, stepZoom } = await import("./shell.js");
const { state } = await import("./core/store.js");
const out = {};
const wheel = (deltaY, mods = { ctrlKey: true }, extra = {}) => {
  const e = { deltaY, deltaMode: 0, defaultPrevented: false, prevented: false,
              ctrlKey: false, metaKey: false, ...mods, ...extra };
  e.preventDefault = () => { e.prevented = true; };
  onZoomWheel(e);
  return e.prevented;
};
const take = () => { const c = __calls.splice(0); return c; };
// a plain wheel scrolls: not taken, nothing asked
out.plain = [wheel(-100, {}), take()];
// one notch up from 100 %, then another before Python answered: 110, 125
out.up = [wheel(-100), take()];
out.up2 = [wheel(-100), take()];
// Python's answer arrives; a notch down steps from there
state.shell.zoom = 1.25;
await new Promise((r) => setTimeout(r, 1600));
out.down = [wheel(100), take()];
// a touchpad pinch: small deltas add up to one step
await new Promise((r) => setTimeout(r, 500));
out.pinch = [[wheel(-10), wheel(-15), wheel(-20)], take(), [wheel(-10)], take()];
// Cmd on a Mac
await new Promise((r) => setTimeout(r, 500));
out.cmd = [wheel(-100, { metaKey: true }), take()];
// the Scenes picture took it already: the page leaves it alone
out.taken = [wheel(-100, { ctrlKey: true }, { defaultPrevented: true }), take()];
// Ctrl 0 is always "Actual size"
stepZoom(0);
out.reset = take();
console.log(JSON.stringify(out));
"""


def _imports(src):
    mods = {}
    for m in re.finditer(r"import \{([^}]*)\}\s*from \"\./([\w/.-]+)\"", src):
        mods.setdefault(m.group(2), set()).update(
            n.strip() for n in m.group(1).split(",") if n.strip())
    return mods


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_ctrl_wheel_steps_the_app_zoom(tmp_path):
    with open(os.path.join(_JS, "shell.js"), encoding="utf-8") as f:
        src = f.read()
    (tmp_path / "shell.js").write_text(src, encoding="utf-8")
    for mod, names in _imports(src).items():
        body = ""
        for n in sorted(names):
            if n == "state":
                body += "export const state = { shell: { zoom: 1 } };\n"
            elif n == "call":
                body += ("export const call = (...a) => "
                         "{ globalThis.__calls.push(a); return Promise.resolve(); };\n")
            else:
                body += "export const %s = function () {};\n" % n
        path = tmp_path / mod
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    (tmp_path / "globals.js").write_text(_GLOBALS, encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    r = subprocess.run(["node", "run.js"], cwd=str(tmp_path), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["plain"] == [False, []]
    assert out["up"] == [True, [["shell.zoom", 1.1]]]
    assert out["up2"] == [True, [["shell.zoom", 1.25]]]
    assert out["down"] == [True, [["shell.zoom", 1.1]]]
    # 10 + 15 + 20 = 45 is not a step yet; 10 more is
    assert out["pinch"] == [[True, True, True], [], [True], [["shell.zoom", 1.25]]]
    assert out["cmd"] == [True, [["shell.zoom", 1.5]]]
    assert out["taken"] == [False, []]
    assert out["reset"] == [["shell.zoom", 1]]


def test_the_wheel_is_wired_and_named_in_the_zoom_menu():
    with open(os.path.join(_JS, "shell.js"), encoding="utf-8") as f:
        src = f.read()
    assert 'window.addEventListener("wheel", onZoomWheel, { passive: false })' in src
    assert 'window.removeEventListener("wheel", onZoomWheel)' in src
    assert 'MOD + " wheel up"' in src and 'MOD + " wheel down"' in src
