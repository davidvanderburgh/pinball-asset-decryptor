"""Capture and check the web UI: start the app's server against a SCRATCH
settings folder, drive it with Playwright, screenshot tabs, and fail on any
JavaScript error.

    python scripts/webui_shot.py --out shots/ --mfr stern --tab audio
    python scripts/webui_shot.py --out shots/ --all           # every mfr x tab
    python scripts/webui_shot.py --out shots/ --settings "%APPDATA%/pinball_decryptor/settings.json" --mfr stern --all-tabs

The real settings file is only ever COPIED (never written).  The browser is
the installed Edge on Windows (Playwright's channel="msedge"), Playwright's
Chromium or WebKit elsewhere (``--engine webkit`` = what macOS's window uses).

Exit status is non-zero when a page threw, a call failed, or a capture was
blank; the report lists each.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def start_server(settings_src, scratch, extra_env=None, app_cmd=None):
    cfg = os.path.join(scratch, "cfg")
    os.makedirs(os.path.join(cfg, "pinball_decryptor"), exist_ok=True)
    if settings_src and os.path.isfile(settings_src):
        shutil.copy2(settings_src, os.path.join(cfg, "pinball_decryptor",
                                                "settings.json"))
    else:
        with open(os.path.join(cfg, "pinball_decryptor", "settings.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"disclaimer_accepted": True}, f)
    env = dict(os.environ)
    env["APPDATA"] = cfg
    env["XDG_CONFIG_HOME"] = cfg
    if sys.platform == "darwin":
        home = os.path.join(scratch, "home")
        os.makedirs(os.path.join(home, "Library", "Application Support",
                                 "pinball_decryptor"), exist_ok=True)
        dst = os.path.join(home, "Library", "Application Support",
                           "pinball_decryptor", "settings.json")
        shutil.copy2(os.path.join(cfg, "pinball_decryptor", "settings.json"),
                     dst)
        env["HOME"] = home
    env["PINBALL_SKIP_DISCLAIMER"] = "1"
    env["PAD_UI_NO_UPDATE_CHECK"] = "1"
    env["PAD_UI_NO_PREREQS"] = "1"
    env["PAD_UI_NO_RIG"] = "1"
    # never write back into the real projects the settings copy names
    env["PAD_UI_CAPTURE"] = "1"
    env.update(extra_env or {})
    cmd = (list(app_cmd) + ["--serve"]) if app_cmd else         [sys.executable, "-m", "pinball_decryptor.webui.host", "--serve"]
    proc = subprocess.Popen(
        cmd,
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    url = None
    deadline = time.time() + 90
    lines = []
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        lines.append(line)
        if line.startswith("http://127.0.0.1:"):
            url = line.strip()
            break
    if not url:
        proc.kill()
        raise SystemExit("the server did not start:\n" + "".join(lines[-40:]))
    # keep draining output so the pipe never fills
    import threading
    log_path = os.path.join(scratch, "server.log")

    def _drain():
        with open(log_path, "a", encoding="utf-8") as f:
            for ln in proc.stdout:
                f.write(ln)

    threading.Thread(target=_drain, daemon=True).start()
    return proc, url


def api(url, method, *args):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(
        base + "/api", data=json.dumps({"m": method, "a": list(args)}).encode(),
        headers={"Content-Type": "application/json", "X-PAD-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read().decode())
    if not j.get("ok"):
        raise RuntimeError("%s failed: %s\n%s" % (method, j.get("error"),
                                                  j.get("trace", "")))
    return j.get("r")


def state(url):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    with urllib.request.urlopen(base + "/api/state?t=" + token,
                                timeout=60) as r:
        return json.loads(r.read().decode())["state"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--settings", default="")
    ap.add_argument("--mfr", action="append", default=[])
    ap.add_argument("--era", default="")
    ap.add_argument("--tab", action="append", default=[])
    ap.add_argument("--all", action="store_true",
                    help="every manufacturer (and era) x every visible tab")
    ap.add_argument("--all-tabs", action="store_true")
    ap.add_argument("--picker", action="store_true")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--zoom", type=float, default=0)
    ap.add_argument("--theme", default="")
    ap.add_argument("--engine", default="",
                    help="chromium | msedge | webkit (default: msedge on "
                         "Windows, chromium elsewhere)")
    ap.add_argument("--project", default="",
                    help="set the project folder (Extract output) first")
    ap.add_argument("--input", default="", help="set the Extract input")
    ap.add_argument("--wait", type=float, default=1.5,
                    help="seconds to let a tab settle before the capture")
    ap.add_argument("--app", default="",
                    help="a frozen app to serve from instead of the source "
                         "tree (its path; --serve is added)")
    ap.add_argument("--hide-log", action="store_true",
                    help="capture with the log pane collapsed (the README "
                         "shots: a developer's log names their own files)")
    ap.add_argument("--keep", action="store_true",
                    help="leave the server running and print its URL")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="padshot-")
    proc, url = start_server(args.settings, scratch,
                             app_cmd=[args.app] if args.app else None)
    report = {"url": url, "shots": [], "errors": []}
    from playwright.sync_api import sync_playwright
    engine = args.engine or ("msedge" if sys.platform == "win32"
                             else "chromium")
    try:
        with sync_playwright() as p:
            if engine == "webkit":
                browser = p.webkit.launch()
            elif engine == "msedge":
                browser = p.chromium.launch(channel="msedge")
            else:
                browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": args.width,
                                              "height": args.height})
            page.on("pageerror", lambda e: report["errors"].append(
                "pageerror: %s" % e))
            page.on("console", lambda m: report["errors"].append(
                "console.%s: %s" % (m.type, m.text))
                if m.type == "error" else None)
            if args.hide_log:
                page.add_init_script(
                    "try { localStorage.setItem('pad.log.open', '0'); }"
                    " catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true",
                                   timeout=60000)
            if args.theme:
                api(url, "ui.set_theme", args.theme)
            if args.zoom:
                api(url, "shell.zoom", args.zoom)

            def shoot(name):
                time.sleep(args.wait)
                path = os.path.join(args.out, name + ".png")
                page.screenshot(path=path)
                report["shots"].append(path)
                print("shot", path, flush=True)

            if args.picker or args.all:
                api(url, "ui.back_to_picker")
                shoot("picker")
            st = state(url)
            mfrs = args.mfr or ([m["key"] for m in st["shell"]["mfrs"]]
                                if args.all else
                                [st["shell"]["mfr"]["key"]]
                                if st["shell"].get("mfr") else [])
            for mkey in mfrs:
                api(url, "ui.pick_manufacturer", mkey)
                st = state(url)
                eras = [e["key"] for e in (st["shell"]["mfr"] or {})
                        .get("eras", [])] or [""]
                if args.era:
                    eras = [args.era]
                elif not args.all:
                    eras = [st["shell"]["mfr"].get("era") or ""]
                for era in eras:
                    if era and era != (state(url)["shell"]["mfr"]
                                       .get("era")):
                        api(url, "ui.set_era", era)
                    if args.project:
                        api(url, "ui.set", "extract", "output", args.project)
                    if args.input:
                        api(url, "ui.set", "extract", "input", args.input)
                    st = state(url)
                    tabs = [t["ns"] for t in st["shell"]["tabs"]
                            if t["visible"]]
                    want = tabs if (args.all or args.all_tabs) else \
                        (args.tab or [st["shell"].get("tab")])
                    for ns in want:
                        if ns not in tabs:
                            report["errors"].append(
                                "tab %s not visible for %s/%s" % (ns, mkey,
                                                                   era))
                            continue
                        api(url, "ui.select_tab", ns)
                        shoot("%s%s-%s" % (mkey, ("-" + era) if era else "",
                                           ns))
            if args.keep:
                print("KEEP", url, flush=True)
                input("press Enter to stop")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(args.out, "report.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    for e in report["errors"]:
        print("ERROR", e)
    print("%d shots, %d errors; server log %s" % (
        len(report["shots"]), len(report["errors"]),
        os.path.join(scratch, "server.log")))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
