"""PAD-1563 proof shots: Direct-SSD on Windows when the app runs without Administrator.

    python scripts/shot_pad1563.py <repo> <out dir> [--prefix after] [--mfr jjp]

Serves <repo> (run from an unelevated shell, as the app now starts) on a scratch settings folder and
shoots, as <prefix>_<screen>.png:

* ``extract_ssd``: the Extract tab with "From SSD" picked - the Administrator panel and the top bar.
* ``write_ssd``: the Write tab with the same source - its Administrator panel.
* ``resumed`` (with ``--resumed``): a server started with ``--direct-ssd write``, as Restart as
  administrator starts the elevated copy - it opens on Write with From SSD picked.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    prefix = _arg("--prefix", "after")
    mfr = _arg("--mfr", "jjp")
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1563-")
    launcher = os.path.join(scratch, "launch1563.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": mfr,
                   "manufacturers": {mfr: {"extract_output": scratch, "write_output": scratch}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    resumed = "--resumed" in sys.argv
    cmd = [sys.executable, launcher] + (["--direct-ssd", "write"] if resumed else [])
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=cmd, extra_env=env)

    def shot(page, name):
        path = os.path.join(out, "%s_%s.png" % (prefix, name))
        page.screenshot(path=path)
        print("saved", path, flush=True)

    try:
        webui_shot.api(url, "ui.pick_manufacturer", mfr)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            if resumed:
                st = webui_shot.state(url)
                print("resumed: tab", (st.get("shell") or {}).get("tab"), "write source",
                      (st.get("write") or {}).get("direct_mode"), flush=True)
                shot(page, "resumed")
                browser.close()
                return
            webui_shot.api(url, "ui.select_tab", "extract")
            webui_shot.api(url, "extract.set_source", "ssd")
            time.sleep(3)
            st = webui_shot.state(url)
            ex = st.get("extract") or {}
            print("extract:", {k: ex.get(k) for k in ("ssd", "admin_panel", "admin_body", "admin_restart",
                                                      "gate")}, flush=True)
            print("shell not_admin:", (st.get("shell") or {}).get("not_admin"), flush=True)  # gone after PAD-1563
            shot(page, "extract_ssd")
            webui_shot.api(url, "ui.select_tab", "write")
            webui_shot.api(url, "write.set_source", "ssd")
            time.sleep(3)
            wr = webui_shot.state(url).get("write") or {}
            print("write:", {k: wr.get(k) for k in ("direct_mode", "show_admin", "admin_body",
                                                    "admin_restart")}, flush=True)
            shot(page, "write_ssd")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
