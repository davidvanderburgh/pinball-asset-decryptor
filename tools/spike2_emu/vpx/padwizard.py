#!/usr/bin/env python3
"""padwizard.py - the Visual Pinball setup wizard (`padvpx wizard`).

One window that takes a fresh machine from the installer to a playing
table, in order:

  1. Checks     WSL 2 (installed here if missing), the PAD runtime distro
                (downloaded and imported here), the controller's registration
  2. Visual Pinball   found, chosen, or downloaded (the 10.8.0 release zip
                unpacked where the user says)
  3. Cards      the folder of SD card images, and which titles it covers
  4. Tables     the tables this build shipped (or the user's own .vpx to
                patch), copied into Visual Pinball's tables folder
  5. Windows    where Visual Pinball's playfield window and the game's LCD
                window go: a preset for the screens found, or numbers
  6. Finish     open a table

Everything it writes is what the padvpx commands write (~/.pad-vpx.json and
Visual Pinball's ini), so the commands remain the long way round. The page
is pywebview (the app's own window kind) with this file's API behind it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = os.path.dirname(HERE)
APP = os.path.dirname(os.path.dirname(RIG))            # the install dir / the checkout
for p in (HERE, RIG, APP):
    if p not in sys.path:
        sys.path.insert(0, p)

import padlaunch   # noqa: E402
import padvpx      # noqa: E402

VPX_URL = ("https://github.com/vpinball/vpinball/releases/download/v10.8.0-2051-28dd6c3/"
           "Developer.VPinballX-10.8.0-2051-28dd6c3-Release-win-x64.zip")
VPX_DEFAULT_DIR = r"C:\Visual Pinball"
#: where the installer puts the tables a build ships (none in a release)
TABLES_DIRS = [os.environ.get("PAD_VPX_TABLES") or "", os.path.join(APP, "vpx", "tables"),
               os.path.join(APP, "installer", "vpx_tables")]
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _run(args, timeout=60):
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW)


def _text(b):
    if not b:
        return ""
    return b.decode("utf-16-le", "replace") if b"\x00" in b else b.decode("utf-8", "replace")


def wsl_ok():
    try:
        r = _run(["wsl.exe", "--status"], timeout=30)
        return r.returncode == 0
    except Exception:                                       # noqa: BLE001
        return False


def runtime_state():
    try:
        from pinball_decryptor.core import runtime
        return runtime.status(refresh=True)
    except Exception as exc:                                # noqa: BLE001
        return ("unknown", "the app's runtime module is not beside this kit: %s" % exc)


def controller_registered():
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PAD.Controller\\CLSID")
        return True
    except Exception:                                       # noqa: BLE001
        return False


def find_vpx():
    kit = padlaunch.kit_load().get("vpx")
    for d in [kit, VPX_DEFAULT_DIR, os.path.join(os.environ.get("ProgramFiles", ""), "Visual Pinball"),
              os.path.join(os.path.expanduser("~"), "Visual Pinball")]:
        if d and os.path.isfile(os.path.join(d, "VPinballX64.exe")):
            return d
    return ""


def shipped_tables():
    out, seen = [], set()
    for d in TABLES_DIRS:
        if d and os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                p = os.path.normcase(os.path.realpath(os.path.join(d, f)))
                if f.lower().endswith(".vpx") and p not in seen:
                    seen.add(p)
                    out.append(os.path.join(d, f))
    return out


def table_title(path):
    """Which title a shipped (PAD) table is for, from its name."""
    n = os.path.basename(path).lower()
    for title, words in (("rush_le", ("rush",)), ("foo_fighters_le", ("foo",)), ("godzilla_le", ("godzilla",))):
        if all(w in n for w in words):
            return title
    return ""


def cards_in(folder):
    out = {}
    if folder and os.path.isdir(folder):
        for f in os.listdir(folder):
            m = re.match(r"^([a-z0-9_]+)-\d+_\d+_\d+.*\.sdcard\.raw$", f, re.I)
            if m:
                t = m.group(1).lower()
                out.setdefault(t, []).append(f)
    return out


def layout_presets(mons):
    """Window layouts for the monitors found: (key, words, player rect, lcd rect)."""
    out = []
    if not mons:
        mons = [(0, 0, 1920, 1080)]
    l, t, r, b = mons[0]
    w, h = r - l, b - t
    pw = int(h * 2 / 3)                                  # a playfield is 2:3
    lw = w - pw
    out.append(("side", "Playfield on the main screen, full height on the left; the LCD on the right",
                (l, t, pw, h), (l + pw, t, lw, int(lw * 9 / 16))))
    if len(mons) > 1:
        l2, t2, r2, b2 = mons[1]
        out.append(("two", "Playfield fills the main screen; the LCD fills the second screen",
                    (l, t, int(h * 2 / 3), h), (l2, t2, r2 - l2, b2 - t2)))
    out.append(("centre", "Playfield in the middle at Visual Pinball's own size; the LCD on top, upper middle",
                None, None))
    return out


class Api:
    def __init__(self):
        self._window = None   # underscored: pywebview walks every public attribute into the JS api
        self.log_lines = []

    # -- helpers
    def _say(self, msg):
        self.log_lines.append(msg)
        if self._window:
            try:
                self._window.evaluate_js("wizLog(%s)" % json.dumps(msg))
            except Exception:                               # noqa: BLE001
                pass

    def _progress(self, frac):
        if self._window:
            try:
                self._window.evaluate_js("wizProgress(%s)" % json.dumps(frac))
            except Exception:                               # noqa: BLE001
                pass

    # -- state
    def state(self):
        import padcontroller
        padcontroller.dpi_aware()
        kit = padlaunch.kit_load()
        lib = os.environ.get("PAD_VPX_LIBRARY") or kit.get("library") or ""
        mons = padcontroller.monitors()
        rt_state, rt_text = runtime_state()
        return {
            "wsl": wsl_ok(),
            "runtime": {"state": rt_state, "text": rt_text},
            "registered": controller_registered(),
            "vpx": find_vpx(),
            "library": lib,
            "cards": cards_in(lib),
            "card_for": {t: padlaunch.card_for(t) for t in ("rush_le", "foo_fighters_le", "godzilla_le")},
            "shipped": [{"path": p, "name": os.path.basename(p), "title": table_title(p)} for p in shipped_tables()],
            "in_vpx": [f for f in (os.listdir(os.path.join(find_vpx(), "tables")) if find_vpx() and
                       os.path.isdir(os.path.join(find_vpx(), "tables")) else []) if "(PAD)" in f],
            "monitors": mons,
            "presets": [{"key": k, "words": w, "player": p, "lcd": q} for k, w, p, q in layout_presets(mons)],
            "lcd": kit.get("lcd"), "player": kit.get("player"),
            "python": sys.executable,
        }

    # -- step 1
    def install_wsl(self):
        """`wsl --install --no-distribution`, elevated; Windows may want a
        reboot before WSL works, and says so."""
        try:
            subprocess.Popen(["powershell.exe", "-NoProfile", "-Command",
                              "Start-Process wsl.exe -ArgumentList '--install','--no-distribution' -Verb RunAs -Wait"],
                             creationflags=_CREATE_NO_WINDOW).wait(timeout=1800)
            return "WSL 2 install finished. If Windows asks for a reboot, reboot and run this wizard again (Start menu: Visual Pinball kit, then `padvpx wizard`)."
        except Exception as exc:                            # noqa: BLE001
            return "WSL install did not finish: %s" % exc

    def install_runtime(self, replace=False):
        """`replace` only after the page said what a replaced runtime loses
        (its extracted games, card caches and save states)."""
        def prog(done, total):
            if total:
                self._progress(min(1.0, done / float(total)))

        def work():
            try:
                from pinball_decryptor.core import runtime
                state = runtime.install(log=self._say, progress=prog, replace=bool(replace))
                self._say("runtime: %s" % state)
            except Exception as exc:                        # noqa: BLE001
                self._say("runtime install failed: %s" % exc)
            self._done("runtime")
        threading.Thread(target=work, daemon=True).start()
        return "started"

    def register(self):
        """PAD.Controller under HKLM: elevated, with this Python."""
        try:
            cmd = ("Start-Process '%s' -ArgumentList '\"%s\" register' -Verb RunAs -Wait"
                   % (sys.executable.replace("pythonw.exe", "python.exe"), os.path.join(HERE, "padvpx.py")))
            subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", cmd],
                             creationflags=_CREATE_NO_WINDOW).wait(timeout=300)
        except Exception as exc:                            # noqa: BLE001
            return "registration failed: %s" % exc
        return "registered" if controller_registered() else "not registered (the elevation was declined?)"

    def _done(self, what):
        if self._window:
            try:
                self._window.evaluate_js("wizDone(%s)" % json.dumps(what))
            except Exception:                               # noqa: BLE001
                pass

    # -- step 2
    def pick_folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not r:
            return ""
        return r if isinstance(r, str) else list(r)[0]

    def pick_vpx_file(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("Visual Pinball table (*.vpx)",))
        if not r:
            return ""
        return r if isinstance(r, str) else list(r)[0]

    def set_vpx(self, folder):
        if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
            return "no VPinballX64.exe in %s" % folder
        d = padlaunch.kit_load()
        d["vpx"] = folder
        padlaunch.kit_save(d)
        return "ok"

    def download_vpx(self, folder):
        folder = folder or VPX_DEFAULT_DIR

        def work():
            try:
                os.makedirs(folder, exist_ok=True)
                tmp = os.path.join(folder, "vpx-release.zip")
                self._say("downloading Visual Pinball 10.8.0 (37 MB)...")

                def hook(n, bs, total):
                    if total > 0:
                        self._progress(min(1.0, n * bs / total))
                urllib.request.urlretrieve(VPX_URL, tmp, hook)
                self._say("unpacking into %s" % folder)
                with zipfile.ZipFile(tmp) as z:
                    z.extractall(folder)
                os.remove(tmp)
                # the release zip may wrap everything in one folder
                if not os.path.isfile(os.path.join(folder, "VPinballX64.exe")):
                    for sub in os.listdir(folder):
                        if os.path.isfile(os.path.join(folder, sub, "VPinballX64.exe")):
                            for f in os.listdir(os.path.join(folder, sub)):
                                shutil.move(os.path.join(folder, sub, f), folder)
                            os.rmdir(os.path.join(folder, sub))
                            break
                os.makedirs(os.path.join(folder, "tables"), exist_ok=True)
                self.set_vpx(folder)
                self._say("Visual Pinball is in %s" % folder)
            except Exception as exc:                        # noqa: BLE001
                self._say("download failed: %s" % exc)
            self._done("vpx")
        threading.Thread(target=work, daemon=True).start()
        return "started"

    # -- step 3
    def set_library(self, folder):
        d = padlaunch.kit_load()
        d["library"] = folder
        padlaunch.kit_save(d)
        return cards_in(folder)

    # -- step 4
    def copy_tables(self, paths):
        vpx = find_vpx()
        if not vpx:
            return "Visual Pinball is not set up yet (step 2)"
        dest = os.path.join(vpx, "tables")
        os.makedirs(dest, exist_ok=True)
        done = []
        for p in paths:
            shutil.copyfile(p, os.path.join(dest, os.path.basename(p)))
            done.append(os.path.basename(p))
        return "copied into %s: %s" % (dest, ", ".join(done))

    def patch_table(self, path):
        """The user's own download of a tribute: recognised and patched
        beside itself, then copied if Visual Pinball's folder is known."""
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = padvpx.patch(path, os.path.dirname(path), None)
        return ("ok" if rc == 0 else "failed") + "\n" + buf.getvalue()[-800:]

    # -- step 5
    def apply_layout(self, key, player, lcd):
        """player / lcd: [x, y, w, h] or null (Visual Pinball's own place,
        the LCD's default). Visual Pinball's ini gets the player size."""
        d = padlaunch.kit_load()
        if player:
            x, y, w, h = [int(v) for v in player]
            d["player"] = {"x": x, "y": y, "w": w, "h": h}
            padvpx.vpx_ini_set({"FullScreen": "0", "Width": str(w), "Height": str(h)})
        else:
            d.pop("player", None)
            padvpx.vpx_ini_set({"FullScreen": "0"})
        if lcd:
            x, y, w, h = [int(v) for v in lcd]
            d["lcd"] = {"x": x, "y": y, "w": w, "h": h, "topmost": True}
        else:
            d["lcd"] = {"topmost": True}
        padlaunch.kit_save(d)
        return "layout %s saved" % key

    # -- step 6
    def open_table(self, name):
        vpx = find_vpx()
        if not vpx:
            return "Visual Pinball is not set up"
        path = os.path.join(vpx, "tables", name)
        if not os.path.isfile(path):
            return "no %s in %s" % (name, os.path.join(vpx, "tables"))
        subprocess.Popen([os.path.join(vpx, "VPinballX64.exe"), "-play", path], cwd=vpx)
        return "opening %s; the game starts by itself, give it a minute" % name


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Visual Pinball setup</title>
<style>
 body { margin:0; font: 15px/1.45 "Segoe UI", sans-serif; background:#15171A; color:#E8E8E8; }
 header { padding:18px 28px 10px; border-bottom:1px solid #2A2D33; }
 header h1 { margin:0; font-size:20px; font-weight:600; }
 nav { display:flex; gap:6px; padding:10px 28px; flex-wrap:wrap; }
 nav span { padding:4px 10px; border-radius:12px; background:#23262C; color:#999; font-size:13px; }
 nav span.on { background:#3A6EA5; color:#fff; } nav span.ok { background:#2E6B3A; color:#fff; }
 main { padding:14px 28px 90px; }
 .step { display:none; } .step.on { display:block; }
 h2 { font-size:17px; margin:8px 0 10px; }
 p, li { color:#C8C8C8; } .muted { color:#8A8F99; font-size:13px; }
 .ok { color:#7CCB8A; } .bad { color:#E5887A; }
 button { background:#3A6EA5; color:#fff; border:0; border-radius:6px; padding:8px 14px; font-size:14px; cursor:pointer; margin:4px 6px 4px 0; }
 button.alt { background:#2F333A; } button:disabled { opacity:.5; cursor:default; }
 input[type=text] { width:70%; padding:7px 9px; background:#1E2126; border:1px solid #3A3E46; color:#eee; border-radius:5px; }
 input.n { width:80px; margin-right:6px; }
 .lab { display:inline-block; width:80px; color:#8A8F99; }
 .row { margin:8px 0; }
 .card { background:#1C1F24; border:1px solid #2A2D33; border-radius:8px; padding:12px 14px; margin:10px 0; }
 pre { background:#0F1114; color:#B8C0CC; padding:10px; border-radius:6px; max-height:160px; overflow:auto; font-size:12px; white-space:pre-wrap; }
 progress { width:100%; height:10px; }
 footer { position:fixed; left:0; right:0; bottom:0; padding:12px 28px; background:#1C1F24; border-top:1px solid #2A2D33; display:flex; justify-content:space-between; }
 label.pre { display:block; margin:6px 0; cursor:pointer; }
 .mons { position:relative; height:120px; background:#0F1114; border-radius:6px; margin:8px 0; }
 .mon { position:absolute; border:1px solid #556; background:#1E2126; font-size:11px; color:#889; }
 .pf { position:absolute; background:#3A6EA5aa; } .lc { position:absolute; background:#2E6B3Aaa; }
</style></head><body>
<header><h1>Visual Pinball on the emulator: setup</h1>
<div class="muted">The real Stern game, from your own SD card image, plays a Visual Pinball table.</div></header>
<nav id="nav"></nav>
<main>
<div class="step" id="s1"><h2>1. The machine</h2>
 <div class="card" id="c-wsl"></div><div class="card" id="c-rt"></div><div class="card" id="c-reg"></div>
 <progress id="pg1" value="0" max="1" style="display:none"></progress><pre id="log1" style="display:none"></pre>
</div>
<div class="step" id="s2"><h2>2. Visual Pinball</h2>
 <div class="card"><div id="vpx-found"></div>
  <div class="row"><input type="text" id="vpx-dir" placeholder="C:\Visual Pinball">
   <button class="alt" onclick="pickVpx()">Choose folder...</button></div>
  <div class="row"><button onclick="useVpx()">Use this folder</button>
   <button id="dl" onclick="dlVpx()">Download Visual Pinball 10.8.0 into it (37 MB)</button></div>
  <progress id="pg2" value="0" max="1" style="display:none"></progress><pre id="log2" style="display:none"></pre>
 </div></div>
<div class="step" id="s3"><h2>3. Your SD card images</h2>
 <div class="card"><p>The folder with your Stern card images (<span class="muted">rush_le-1_19_0.Release.16G.sdcard.raw and the like</span>). The newest build of each title is the one the game boots.</p>
  <div class="row"><input type="text" id="lib" placeholder="D:\Pinball\images"><button class="alt" onclick="pickLib()">Choose folder...</button></div>
  <div class="row"><button onclick="useLib()">Use this folder</button></div>
  <div id="cards"></div></div></div>
<div class="step" id="s4"><h2>4. Tables</h2>
 <div class="card"><div id="shipped"></div>
  <div class="row"><button onclick="copyShipped()">Put them in Visual Pinball's tables folder</button></div>
  <div id="copied" class="muted"></div></div>
 <div class="card"><p>A tribute you downloaded yourself (Rush LE Tribute, JP's Foo Fighters, marty02's Godzilla)? Patch it:</p>
  <div class="row"><button class="alt" onclick="patchOwn()">Choose a .vpx and patch it</button></div><pre id="log4" style="display:none"></pre></div></div>
<div class="step" id="s5"><h2>5. Where the windows go</h2>
 <div class="card"><p>Visual Pinball's playfield window has no frame and cannot be dragged; the game's LCD window sits on top of it. Pick a layout for the screens found:</p>
  <div class="mons" id="mons"></div><div id="presets"></div>
  <div class="row muted" style="margin-top:14px">Or your own numbers (x, y, width, height in pixels; leave a row empty for the default):</div>
  <div class="row"><span class="lab">Playfield</span><input class="n" id="px" placeholder="x"><input class="n" id="py" placeholder="y"><input class="n" id="pw" placeholder="width"><input class="n" id="ph" placeholder="height"></div>
  <div class="row"><span class="lab">LCD</span><input class="n" id="lx" placeholder="x"><input class="n" id="ly" placeholder="y"><input class="n" id="lw" placeholder="width"><input class="n" id="lh" placeholder="height">
   <button class="alt" onclick="applyCustom()">Use these</button></div>
  <div id="layout-said" class="muted"></div></div></div>
<div class="step" id="s6"><h2>6. Play</h2>
 <div class="card" id="finish"></div>
 <div class="card muted">Keys: 1 Start, 5 coin (insert until the LCD shows a credit), Shift keys flip, Left Alt launches, Esc leaves and stops the game. The LCD window may take the focus the first time: click the playfield and play on; drag the LCD anywhere.</div></div>
</main>
<footer><button class="alt" onclick="go(-1)" id="back">Back</button><span id="where" class="muted"></span><button onclick="go(1)" id="next">Next</button></footer>
<script>
const steps = ["Machine","Visual Pinball","Cards","Tables","Windows","Play"];
let cur = 0, st = null, chosen = null;
function nav(){ document.getElementById('nav').innerHTML = steps.map((s,i)=>'<span class="'+(i===cur?'on':(i<cur?'ok':''))+'">'+(i+1)+'. '+s+'</span>').join(''); }
function show(){ document.querySelectorAll('.step').forEach((e,i)=>e.classList.toggle('on', i===cur)); nav();
  document.getElementById('back').disabled = cur===0; document.getElementById('next').textContent = cur===5 ? 'Close' : 'Next';
  document.getElementById('where').textContent = 'Step '+(cur+1)+' of 6'; }
function go(d){ if (cur===5 && d>0) { window.close(); return; } cur = Math.max(0, Math.min(5, cur+d)); refresh(); }
function esc(s){ return String(s).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function refresh(){ st = await pywebview.api.state(); render(); show(); }
function render(){
  const ok = (b, y, n) => b ? '<span class="ok">&#10004; '+y+'</span>' : '<span class="bad">&#10008; '+n+'</span>';
  document.getElementById('c-wsl').innerHTML = ok(st.wsl, 'WSL 2 is installed', 'WSL 2 is not installed') +
    (st.wsl ? '' : ' <button onclick="doWsl()">Install WSL 2 (asks for admin)</button><div class="muted">Windows may ask to reboot; then run this wizard again.</div>');
  const rt = st.runtime.state === 'ready', stale = st.runtime.state === 'stale' || st.runtime.state === 'foreign';
  document.getElementById('c-rt').innerHTML = ok(rt, 'The PAD runtime is installed ('+esc(st.runtime.text)+')', 'The PAD runtime is not ready: '+esc(st.runtime.text)) +
    (rt ? '' : (stale ? ' <button onclick="doRuntime(true)" '+(st.wsl?'':'disabled')+'>Replace the runtime</button><div class="muted">Replacing deletes what the old one holds: extracted games, card caches and save states.</div>'
                      : ' <button onclick="doRuntime(false)" '+(st.wsl?'':'disabled')+'>Install the runtime (downloads a few hundred MB)</button>'));
  document.getElementById('c-reg').innerHTML = ok(st.registered, 'The Visual Pinball controller is registered', 'The controller is not registered') +
    (st.registered ? '' : ' <button onclick="doReg()">Register (asks for admin)</button>');
  document.getElementById('vpx-found').innerHTML = st.vpx ? ok(true, 'Visual Pinball found in '+esc(st.vpx)) : ok(false, '', 'Visual Pinball was not found. Choose its folder, or download it.');
  if (!document.getElementById('vpx-dir').value) document.getElementById('vpx-dir').value = st.vpx || 'C:\\Visual Pinball';
  document.getElementById('dl').className = st.vpx ? 'alt' : '';
  if (!document.getElementById('lib').value) document.getElementById('lib').value = st.library || '';
  renderCards(st.cards);
  const ship = st.shipped.length ? '<p>This build ships these tables, already patched for the emulator:</p><ul>' +
     st.shipped.map(t=>'<li>'+esc(t.name)+' <span class="muted">('+esc(t.title||'?')+')</span></li>').join('') + '</ul>' :
     '<p class="muted">This build ships no tables: patch your own below.</p>';
  document.getElementById('shipped').innerHTML = ship + (st.in_vpx.length ? '<div class="ok">In Visual Pinball\'s tables folder: '+esc(st.in_vpx.join(', '))+'</div>' : '');
  renderMons(); renderPresets();
  const have = st.in_vpx.length ? st.in_vpx : st.shipped.map(t=>t.name);
  document.getElementById('finish').innerHTML = (have.length ? '<p>Open a table; the game starts by itself and boots in its LCD window within a minute.</p>' +
     have.map(n=>'<button onclick="openT('+JSON.stringify(n)+')">Open '+esc(n)+'</button>').join('') : '<p class="muted">No table to open yet (step 4).</p>') + '<div id="opened" class="muted"></div>';
}
function renderCards(c){ const t = Object.keys(c||{}); document.getElementById('cards').innerHTML = t.length ?
  '<div class="ok">Titles found: '+t.map(k=>esc(k)+' ('+c[k].length+')').join(', ')+'</div>' : '<div class="muted">No card images found in that folder yet.</div>'; }
function renderMons(){ const m = st.monitors.length ? st.monitors : [[0,0,1920,1080]]; const box = document.getElementById('mons');
  const minx = Math.min(...m.map(r=>r[0])), maxx = Math.max(...m.map(r=>r[2])), maxy = Math.max(...m.map(r=>r[3])), miny = Math.min(...m.map(r=>r[1]));
  const sc = Math.min(560/(maxx-minx), 110/(maxy-miny)); box.innerHTML = m.map((r,i)=>'<div class="mon" style="left:'+((r[0]-minx)*sc+6)+'px;top:'+((r[1]-miny)*sc+5)+'px;width:'+((r[2]-r[0])*sc)+'px;height:'+((r[3]-r[1])*sc)+'px">&nbsp;'+(i+1)+': '+(r[2]-r[0])+'x'+(r[3]-r[1])+'</div>').join('');
  const draw = (rect, cls) => { if (!rect) return; const d = document.createElement('div'); d.className = cls; d.style.left=((rect[0]-minx)*sc+6)+'px'; d.style.top=((rect[1]-miny)*sc+5)+'px'; d.style.width=(rect[2]*sc)+'px'; d.style.height=(rect[3]*sc)+'px'; box.appendChild(d); };
  if (chosen) { draw(chosen.player, 'pf'); draw(chosen.lcd, 'lc'); }
}
function renderPresets(){ document.getElementById('presets').innerHTML = st.presets.map(p=>'<label class="pre"><input type="radio" name="pre" value="'+p.key+'" onchange="pickPreset(\''+p.key+'\')"> '+esc(p.words)+'</label>').join(''); }
async function pickPreset(k){ const p = st.presets.find(x=>x.key===k); chosen = p; renderMons();
  const r = await pywebview.api.apply_layout(k, p.player, p.lcd); document.getElementById('layout-said').textContent = r + (p.player ? ' (playfield '+p.player.join(' ')+', LCD '+p.lcd.join(' ')+')' : ''); }
async function applyCustom(){ const v = id => parseInt(document.getElementById(id).value); const p=[v('px'),v('py'),v('pw'),v('ph')], l=[v('lx'),v('ly'),v('lw'),v('lh')];
  chosen = {player: p.every(Number.isFinite)?p:null, lcd: l.every(Number.isFinite)?l:null}; renderMons();
  document.getElementById('layout-said').textContent = await pywebview.api.apply_layout('custom', chosen.player, chosen.lcd); }
function wizLog(m){ const e = document.getElementById(cur===0?'log1':(cur===1?'log2':'log4')); e.style.display='block'; e.textContent += m + '\n'; e.scrollTop = e.scrollHeight; }
function wizProgress(f){ const e = document.getElementById(cur===0?'pg1':'pg2'); e.style.display='block'; e.value = f; }
function wizDone(w){ refresh(); }
async function doWsl(){ wizLog('installing WSL 2...'); wizLog(await pywebview.api.install_wsl()); refresh(); }
async function doRuntime(replace){ if (replace && !confirm('Replace the runtime? Its extracted games, card caches and save states are deleted.')) return;
  wizLog(replace ? 'replacing the runtime...' : 'installing the runtime...'); await pywebview.api.install_runtime(!!replace); }
async function doReg(){ wizLog(await pywebview.api.register()); refresh(); }
async function pickVpx(){ const f = await pywebview.api.pick_folder(); if (f) document.getElementById('vpx-dir').value = f; }
async function useVpx(){ const r = await pywebview.api.set_vpx(document.getElementById('vpx-dir').value); if (r !== 'ok') alert(r); refresh(); }
async function dlVpx(){ await pywebview.api.download_vpx(document.getElementById('vpx-dir').value); }
async function pickLib(){ const f = await pywebview.api.pick_folder(); if (f) document.getElementById('lib').value = f; }
async function useLib(){ renderCards(await pywebview.api.set_library(document.getElementById('lib').value)); st.library = document.getElementById('lib').value; }
async function copyShipped(){ document.getElementById('copied').textContent = await pywebview.api.copy_tables(st.shipped.map(t=>t.path)); refresh(); }
async function patchOwn(){ const f = await pywebview.api.pick_vpx_file(); if (!f) return; wizLog('patching '+f+' ...'); wizLog(await pywebview.api.patch_table(f)); }
async function openT(n){ document.getElementById('opened').textContent = await pywebview.api.open_table(n); }
window.addEventListener('pywebviewready', refresh);
</script></body></html>
"""


def main():
    import webview
    api = Api()
    win = webview.create_window("Visual Pinball setup", html=PAGE, js_api=api, width=820, height=720,
                                background_color="#15171A", text_select=True)
    api._window = win
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
