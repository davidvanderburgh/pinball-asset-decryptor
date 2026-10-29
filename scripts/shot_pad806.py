"""PAD-806 proof shots: Play on the Visual Pinball tab on a PC with no WSL.

    python scripts/shot_pad806.py <out_dir> [--after]

Serves THIS checkout (run a copy from an export of main for the before shot)
with PAD802_CODE's preview code, as a PC with no WSL: a sitecustomize on
PYTHONPATH (the server and the kit's own Python both load it) makes every
wsl.exe call fail the way it does there and hides the registry's Lxss key.
The kit gets a scratch home: a stand-in Visual Pinball folder holding one
patched Foo Fighters table, and the stand-in never opens a window (its
VPinballX64.exe launch is swallowed). Clicks Play and writes
<before_|after_>play_no_wsl.png.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "spike2_emu", "vpx"))
sys.path.insert(0, os.path.join(REPO, "tools", "spike2_emu"))
import webui_shot  # noqa: E402

SITE = r'''
import os, subprocess, sys
if os.environ.get("PAD806_NO_WSL") == "1":
    try:
        import winreg
        _open = winreg.OpenKey
        def _no_lxss(key, sub, *a, **k):
            if "lxss" in str(sub).lower():
                raise FileNotFoundError(2, "no Lxss key")
            return _open(key, sub, *a, **k)
        winreg.OpenKey = _no_lxss
    except ImportError:
        pass
    _SAY = ("Windows Subsystem for Linux is not installed. You can install by "
            "running 'wsl.exe --install'.\r\n").encode("utf-16-le")
    def _is(args, name):
        a = args[0] if isinstance(args, (list, tuple)) and args else args
        return os.path.basename(str(a)).lower() == name
    _run = subprocess.run
    def run(args, *a, **k):
        if _is(args, "wsl.exe") or _is(args, "wsl"):
            return subprocess.CompletedProcess(args, 1, _SAY if not k.get("text") else
                                               _SAY.decode("utf-16-le"), b"" if not k.get("text") else "")
        return _run(args, *a, **k)
    subprocess.run = run
    _Popen = subprocess.Popen
    class _Gone:
        returncode = 0
        pid = 0
        def poll(self): return 0
        def wait(self, *a, **k): return 0
    def Popen(args, *a, **k):
        if _is(args, "vpinballx64.exe"):
            sys.stderr.write("PAD806: Visual Pinball would open %s\n" % (args,))
            return _Gone()
        return _Popen(args, *a, **k)
    subprocess.Popen = Popen
'''


def main():
    out_dir = os.path.abspath(sys.argv[1])
    after = "--after" in sys.argv
    pre = "after_" if after else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad806-")
    site = os.path.join(scratch, "site")
    os.makedirs(site)
    with open(os.path.join(site, "sitecustomize.py"), "w", encoding="utf-8") as f:
        f.write(SITE)
    import padvpx
    table = padvpx.maps()["foo_fighters_le"]["output"]
    home = os.path.join(scratch, "home")
    vp = os.path.join(scratch, "Visual Pinball")
    os.makedirs(os.path.join(vp, "tables"))
    os.makedirs(home)
    open(os.path.join(vp, "VPinballX64.exe"), "wb").close()
    open(os.path.join(vp, "tables", table), "wb").close()
    with open(os.path.join(home, ".pad-vpx.json"), "w", encoding="utf-8") as f:
        json.dump({"vpx": vp, "library": r"D:\Pinball\images\Stern\spike2"}, f)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    print("serving", REPO, "table", table, flush=True)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"), extra_env={
        "PYTHONUSERBASE": userbase, "PYTHONPATH": site, "PAD806_NO_WSL": "1",
        "USERPROFILE": home, "HOME": home})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 960})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            if webui_shot.state(url)["shell"]["mfr"].get("era") != "spike2":
                webui_shot.api(url, "ui.set_era", "spike2")
                time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "vpx")

            def settle():
                deadline = time.time() + 120
                while time.time() < deadline:
                    st = webui_shot.state(url).get("vpx") or {}
                    if st.get("loaded") and not st.get("busy"):
                        return st
                    time.sleep(1)
                return webui_shot.state(url).get("vpx") or {}
            st = settle()
            print("vpx:", json.dumps({k: st.get(k) for k in (
                "vpx", "runtime_state", "runtime_text", "patched", "message")}), flush=True)
            webui_shot.api(url, "vpx.play", table)
            time.sleep(1)
            st = settle()
            print("after Play:", json.dumps({k: st.get(k) for k in ("runtime_state", "message")}),
                  flush=True)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, pre + "play_no_wsl.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        log = os.path.join(scratch, "srv", "server.log")
        if os.path.isfile(log):
            print("server log tail:", open(log, encoding="utf-8", errors="replace").read()[-1500:])
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
