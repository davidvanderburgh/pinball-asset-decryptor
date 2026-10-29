"""PAD-840 proof shots: the Visual Pinball tab on a PC without the PAD runtime.

    python scripts/shot_pad840.py <out_dir> [--after]
    python scripts/shot_pad840.py <out_dir> --install

--install is the end-to-end proof: the server's runtime is renamed
PAD-Runtime-840 (on C:/tmp/PAD-840/rt, so this PC's own PAD-Runtime is
not touched), the page's Install button is clicked, and the row must turn
Ready from the real import of the cached image.  Writes before_install.png
and after_install.png, then unregisters PAD-Runtime-840.

Serves THIS checkout (run a copy from an export of main for the before shot)
on a scratch settings.json holding one preview code, PAD840_CODE from the
environment (``tools/preview_code.py issue --feature vpx``), and Stern Spike 2.
The server runs with ``core.runtime.registered`` (and ``_listed``)
answering False, which is what a PC that never installed the runtime says
(this PC has one).  Writes <before_|after_>visual_pinball.png.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

#: The server, with no runtime registered (or, for --install, a runtime of
#: another name).  Written into the scratch folder, never into the repo.
_SHIM = """import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import runtime
if %r:
    runtime.DISTRO = "PAD-Runtime-840"
else:
    runtime.registered = lambda runner=None: False
    runtime._listed = lambda runner=None: False
from pinball_decryptor.webui import host
sys.exit(host.main(sys.argv[1:]))
"""


def main():
    out_dir = os.path.abspath(sys.argv[1])
    pre = "after_" if "--after" in sys.argv else "before_"
    install = "--install" in sys.argv
    extra = {"PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")}
    if install:
        extra["PAD_RUNTIME_DIR"] = "C:/tmp/PAD-840/rt"
    code = os.environ.get("PAD840_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad840-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    shim = os.path.join(scratch, "serve_no_runtime.py")
    with open(shim, "w", encoding="utf-8") as f:
        f.write(_SHIM % (os.path.dirname(HERE), install))
    print("serving", os.path.dirname(HERE), flush=True)
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env=extra,
                                        app_cmd=[sys.executable, shim])
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
            deadline = time.time() + 120
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                if st.get("loaded") and not st.get("busy"):
                    break
                time.sleep(1)
            st = webui_shot.state(url).get("vpx") or {}
            print("vpx:", json.dumps({k: st.get(k) for k in (
                "runtime_state", "runtime_text", "message")}), flush=True)
            time.sleep(1.5)
            if install:
                _install(page, url, out_dir)
            else:
                page.screenshot(path=os.path.join(out_dir, pre + "visual_pinball.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
        if install:
            r = subprocess.run(["wsl.exe", "--unregister", "PAD-Runtime-840"],
                               capture_output=True, timeout=300)
            print("unregistered PAD-Runtime-840: rc", r.returncode, flush=True)


def _install(page, url, out_dir):
    st = webui_shot.state(url).get("vpx") or {}
    assert st.get("runtime_state") == "absent", st.get("runtime_state")
    page.screenshot(path=os.path.join(out_dir, "before_install.png"))
    t0 = time.time()
    page.get_by_role("button", name="Install").click()
    seen = set()
    deadline = time.time() + 900
    while time.time() < deadline:
        st = webui_shot.state(url).get("vpx") or {}
        if st.get("message") and st["message"] not in seen:
            seen.add(st["message"])
            print("  %5.0fs %s" % (time.time() - t0, st["message"]), flush=True)
        if st.get("loaded") and not st.get("busy") and time.time() - t0 > 3:
            break
        time.sleep(1)
    print("after Install: %s / %s (%.0fs)" % (st.get("runtime_state"), st.get("runtime_text"),
                                              time.time() - t0), flush=True)
    time.sleep(1.5)
    page.screenshot(path=os.path.join(out_dir, "after_install.png"))


if __name__ == "__main__":
    main()
