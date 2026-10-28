"""PAD-787 capture: My machines with a JJP and a BoF machine beside Stern.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad787.py --out <dir> --prefix before_
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad787.py --out <dir> --prefix after_

A scratch settings folder (never David's real one).  Three real library
files are added through the page's own call (``shellx.machines_add`` with the
path, as the file picker would hand it): the stock Godzilla LE 1.16 card, the
Sonic 0.926 full-install ISO and the Winchester Mystery House ``.fun``.  The
code-update watcher reads a STUB page served here (``PAD_CODE_WATCH_URL``)
carrying what the three makers' real pages carried on 2026-10-27: Godzilla
LE 1.17.0 (made up, as PAD-783's shot), Sonic 0.951 and the Winchester
2026-10-01 update, so the shot shows each row's "is out" line without
touching anybody's site.

A build without JJP/BoF machines refuses the ISO with its "isn't a Stern
Spike 2 card image" message: <prefix>picker.png shows that dialog then.
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

STOCK = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
SONIC = r"D:\Pinball\images\JJP\Sonic-v00.926.iso"
WMH = r"D:\Pinball\images\BoF\winchester.fun"

STUB_PAGE = """<html><body><script>var data = {"posts":[
{"date":"10/27/26","title":"Godzilla LE 1.17.0 Game Code","download_link":
"https:\\/\\/f002.backblazeb2.com\\/file\\/gamecode\\/godzilla_63_1.17.0_1\\/godzilla_le-1_17_0_spike2.spk.zip"}
]};</script>
<a href="https://marketing.jerseyjackpinball.com/sonic/Sonic-v00.951.iso">Download</a>
<a href="https://downloadseu.jerseyjackpinball.com/sonic/Sonic-v00.951.iso">Download</a>
<a href="https://www.dropbox.com/scl/fi/ql75j6evoue7qjieqwb62/BOF_WMH_20261001.zip?rlkey=x&#038;dl=0">DOWNLOAD THE NEW CODE HERE!</a>
</body></html>"""


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


def _add(url, path, name):
    """machines_add on a thread: a refusal opens the page's modal and the
    call waits for it."""
    out = {}

    def run():
        try:
            out["r"] = ws.api(url, "shellx.machines_add", path, name)
        except Exception as e:                            # noqa: BLE001
            out["r"] = "error: %s" % e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(60)
    print("add", os.path.basename(path), out.get("r", "(waiting on a dialog)"))
    return out.get("r")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--width", type=int, default=1360)
    ap.add_argument("--height", type=int, default=980)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    scratch = tempfile.mkdtemp(prefix="padshot787-")
    settings = os.path.join(scratch, "seed.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True}, f)
    stub = _stub_server()
    env = {"PAD_CODE_WATCH_URL": "http://127.0.0.1:%d/support/"
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
                keys = [m["key"] for m in ws.state(url)["shell"]["mfrs"]]
                if all(k in keys for k in ("stern", "jjp", "bof")):
                    break
                time.sleep(0.5)
            refused = False
            for card, name in ((STOCK, "Basement Godzilla"),
                               (SONIC, "Sonic in the game room"),
                               (WMH, "Winchester")):
                if _add(url, card, name) is None:
                    refused = True
                    break
            if not refused:
                for _ in range(90):
                    rows = (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []
                    if sum(1 for r in rows if r.get("newer")) >= 3:
                        break
                    time.sleep(0.5)
            for r in (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []:
                print(json.dumps(r, indent=1))
            print("watch_text", (ws.state(url)["shellx"].get("machines") or {}).get("watch_text"))
            time.sleep(2)
            page.screenshot(path=os.path.join(a.out, a.prefix + "picker.png"))
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
