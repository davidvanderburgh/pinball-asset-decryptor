"""PAD-1588 capture: My machines with a machine this computer reaches over remote access, and its kept settings
backups.

    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad1588.py --out <dir> --prefix before_
    PYTHONPATH=C:\\tmp\\pwlib python scripts/shot_pad1588.py --out <dir> --prefix after_

A scratch settings folder (never David's real one).  The stock Godzilla LE 1.16 card is added through the page's own
call; the remote-access record of a Godzilla LE machine (as Find my machine leaves it, at an address nothing answers
at) and three settings backups of it are put in the scratch folder first.  A build without PAD-1588 ignores both.

<prefix>machines.png  the picker's My machines
<prefix>menu.png      the row's More menu (with PAD-1588: Restore settings from, open)
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
import webui_shot as ws  # noqa: E402

STOCK = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
HK = ["ssh-ed25519", "AAAAC3NzaC1lZDI1NTE5AAAAIBasementGodzillaHostKeyForTheShot0001"]


def _backup(path, stamp, why, scores):
    files = {"nv/godzilla_le/NVM/00000016": scores, "nv/godzilla_le/NVRAM/00000014": b"adjustments" * 40}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as t:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    man = {"kind": "pad-machine-settings", "version": 1, "game": "godzilla_le", "games": ["godzilla_le"],
           "taken": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp)), "stamp": stamp, "why": why,
           "files": {n: hashlib.sha1(d).hexdigest() for n, d in files.items()},
           "bytes": sum(len(d) for d in files.values())}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pad-machine-settings.json", json.dumps(man))
        z.writestr("nv.tar", out.getvalue())


def _seed(cfg):
    base = os.path.join(cfg, "pinball_decryptor")
    os.makedirs(os.path.join(base, "remote_access"), exist_ok=True)
    with open(os.path.join(base, "remote_access", "machines.json"), "w", encoding="utf-8") as f:
        json.dump({"current": "192.0.2.77", "machines": [
            {"address": "192.0.2.77", "host_key": HK, "game": "godzilla_le"}]}, f)
    folder = os.path.join(base, "machine_backups", "id-" + hashlib.sha1(HK[1].encode()).hexdigest()[:16])
    os.makedirs(folder, exist_ok=True)
    now = time.time()
    for days, why in ((0.2, "auto"), (1.3, "send"), (3.1, "auto")):
        stamp = now - days * 86400
        _backup(os.path.join(folder, "godzilla_le-settings-%s.zip" % time.strftime("%Y%m%d-%H%M%S",
                                                                                  time.localtime(stamp))),
                stamp, why, b"scores %f" % stamp)
    with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as f:
        json.dump({"checked": now - 0.2 * 86400, "address": "192.0.2.77"}, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--width", type=int, default=1360)
    ap.add_argument("--height", type=int, default=760)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("REPO", REPO)
    scratch = tempfile.mkdtemp(prefix="padshot1588-")
    _seed(os.path.join(scratch, "cfg"))
    settings = os.path.join(scratch, "seed.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True}, f)
    env = {}
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
            try:
                ws.api(url, "shellx.getting_started_close")
            except Exception as e:                        # noqa: BLE001
                print("getting started:", e)
            out = {}
            t = threading.Thread(target=lambda: out.update(r=ws.api(url, "shellx.machines_add", STOCK,
                                                                     "Basement Godzilla")), daemon=True)
            t.start()
            t.join(120)
            print("add", out)
            for _ in range(60):
                rows = (ws.state(url)["shellx"].get("machines") or {}).get("rows") or []
                if rows and (rows[0].get("backup_last") or "backup_last" not in rows[0]):
                    break
                time.sleep(0.5)
            print(json.dumps({k: v for k, v in rows[0].items() if k.startswith("backup")}, indent=1))
            time.sleep(1.5)
            page.screenshot(path=os.path.join(a.out, a.prefix + "machines.png"))
            page.locator(".mach-row .mach-acts button").last.click()
            time.sleep(0.6)
            sub = page.locator("button.mi", has_text="Restore settings from")
            if sub.count():
                sub.first.hover()
                time.sleep(0.8)
            page.screenshot(path=os.path.join(a.out, a.prefix + "menu.png"))
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
