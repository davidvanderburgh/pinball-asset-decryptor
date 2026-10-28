"""PAD-783 capture: the picker's home with My machines.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad783.py --out <dir> --prefix before_
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad783.py --out <dir> --prefix after_

A scratch settings folder (never David's real one) with one Stern project in
the registry: a scratch folder whose lineage the real ``lineage.note_extract``
wrote from the stock Godzilla LE 1.16 card, plus one revision built over it.
Where the app has My machines, two real library cards are added through the
page's own call (``shellx.machines_add`` with the path, as the file picker
would hand it): the stock Godzilla LE 1.16 card and the Heisei custom built
on that release.  The code-update watcher reads a STUB of Stern's game-code
page served here (``PAD_CODE_WATCH_URL``) that lists Godzilla LE 1.17.0, so
the shot shows the "is out" line without touching Stern's site.

<prefix>picker.png is the picker page.
"""
import argparse
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot as ws  # noqa: E402

LIB = r"D:\Pinball\images\Stern\spike2"
STOCK = os.path.join(LIB, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
CUSTOM = os.path.join(LIB, "Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition.raw")

STUB_PAGE = """<html><body><script>var data = {"posts":[
{"date":"10/27/26","title":"Godzilla LE 1.17.0 Game Code","download_link":
"https:\\/\\/f002.backblazeb2.com\\/file\\/gamecode\\/godzilla_63_1.17.0_1\\/godzilla_le-1_17_0_spike2.spk.zip"},
{"date":"10/27/26","title":"Godzilla Pro 1.17.0 Game Code","download_link":
"https:\\/\\/f002.backblazeb2.com\\/file\\/gamecode\\/godzilla_63_1.17.0_1\\/godzilla_pro-1_17_0_spike2.spk.zip"},
{"date":"10/27/26","title":"Fallout Pro 0.81.0 Game Code","download_link":
"https:\\/\\/f002.backblazeb2.com\\/file\\/gamecode\\/x\\/fallout_pro-0_81_0_spike3.spk.zip"}
]};</script></body></html>"""


def _stub_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                  # noqa: N802
            body = STUB_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print("[stub] GET", self.path, "UA:", self.headers.get("User-Agent"))

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _project(scratch):
    """A scratch Stern project extracted from the stock card (the real
    note_extract), with one revision built over it."""
    from pinball_decryptor.core import lineage, project_file
    from pinball_decryptor.plugins.stern.stock_prints import card_print
    folder = os.path.join(scratch, "Godzilla LE mods")
    os.makedirs(folder, exist_ok=True)
    project_file.save(project_file.anchor_path(folder),
                      manufacturer_key="stern", paths={"extract_input": STOCK},
                      extract_options={}, stock_image=STOCK)
    info = card_print(STOCK)
    lineage.note_extract(folder, os.path.basename(STOCK), info, "official")
    lineage.note_build(folder, "Godzilla LE mods.raw",
                       {"print": "0" * 32, "sidx": info["sidx"],
                        "label": info["label"], "official": False},
                       info, "rig")
    # an extract's baseline marker, so the Mod Pack tab is not greyed out as
    # "nothing extracted" (the scratch project holds no assets)
    open(os.path.join(folder, ".checksums.md5"), "w").close()
    return folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--width", type=int, default=1360)
    ap.add_argument("--height", type=int, default=980)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    scratch = tempfile.mkdtemp(prefix="padshot783-")
    proj = _project(scratch)
    settings = os.path.join(scratch, "seed.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True,
                   "projects": [{"folder": proj, "manufacturer": "stern",
                                 "last_opened": "2026-10-27T10:00:00"}]}, f)
    stub = _stub_server()
    env = {"PAD_CODE_WATCH_URL": "http://127.0.0.1:%d/support/game-code/"
           % stub.server_address[1]}
    if os.environ.get("APPDATA"):
        env["PYTHONUSERBASE"] = os.path.join(os.environ["APPDATA"], "Python")
    proc, url = ws.start_server(settings, scratch, extra_env=env)
    from playwright.sync_api import sync_playwright
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": a.width, "height": a.height})
            page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            for _ in range(240):
                if "stern" in [m["key"] for m in ws.state(url)["shell"]["mfrs"]]:
                    break
                time.sleep(0.5)
            sx = ws.state(url).get("shellx") or {}
            if "machines" in sx:
                for card, name in ((STOCK, "Basement Godzilla"),
                                   (CUSTOM, "Godzilla at Dave's")):
                    print("add", ws.api(url, "shellx.machines_add", card, name))
                for _ in range(60):
                    rows = (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []
                    if any(r.get("newer") for r in rows):
                        break
                    time.sleep(0.5)
                for r in (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []:
                    print(json.dumps(r, indent=1))
            else:
                print("no My machines in this build")
            time.sleep(2)
            page.screenshot(path=os.path.join(a.out, a.prefix + "picker.png"))
            # where Transfer Mods lands: this build's button, or (before) what
            # the owner did by hand - Stern, open the project, Mod Pack
            rows = ((ws.state(url).get("shellx") or {}).get("machines") or {}).get("rows") or []
            if rows:
                print("transfer", ws.api(url, "shellx.machines_transfer", rows[0]["id"]))
            else:
                ws.api(url, "ui.pick_manufacturer", "stern")
                ws.api(url, "shellx.manager_refresh")
                print("open", ws.api(url, "shellx.manager_open", proj))
                ws.api(url, "ui.select_tab", "modpack")
            time.sleep(4)
            st = ws.state(url)
            print("view", st["shell"].get("view"), "tab", st["shell"].get("tab"),
                  "modpack", {k: (st.get("modpack") or {}).get(k)
                              for k in ("src", "dst", "project")})
            page.screenshot(path=os.path.join(a.out, a.prefix + "transfer.png"))
            browser.close()
    finally:
        proc.kill()
        stub.shutdown()
        shutil.rmtree(scratch, ignore_errors=True)
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
