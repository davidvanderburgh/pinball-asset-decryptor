r"""PAD-739 proof shot: the Emulate tab's Card cache window over a cache like the reporter's.

    python scripts/shot_pad739_cache.py <app tree> <out.png> [--select-unused]

<app tree> is a checkout or a `git archive` export (main for "before", the ticket branch for "after"). The rig's
`cardmount.sh --cache-list` is answered with a stand-in modelled on the reporter's `ls -lah ~/cardcache`: the same 18
card labels, sizes, boot (.boot) and copy (.raw) dates, a 1 TB virtual distro disk; the image states (one rebuilt,
one deleted, one card mounted) are illustrative. Both runs get the same lines - an older app reads only the `entry`
and `disk` ones. Nothing runs in WSL.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

G = 1048576     # KB in a GB
REAL = 150 / 201.1

# label, GB on disk, last boot ("" = none), copied, state, use
CARDS = [
    ("Godzilla 70th Anniversary 1.16 Heisei Custom V1.99A Kaiju Edition", 5.9, "10-13 16:51", "10-13 10:19", "ok", "-"),
    ("Godzilla 70th Anniversary 1.16 Heisei Custom V2 Kaiju Edition", 5.9, "10-19 20:15", "10-19 20:15", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.93 Standard Edition", 7.4, "10-11 16:51", "10-11 16:51", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.93a Standard Edition", 15, "10-06 14:46", "09-27 19:22", "gone", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.95 DRAGON", 15, "10-07 09:39", "10-06 17:49", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.95 SPECIAL SP TEST", 15, "10-06 16:37", "10-06 15:40", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.95 SPECIAL", 15, "10-11 16:47", "10-06 14:27", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.96 Standard Edition", 15, "10-17 15:59", "10-07 09:41", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.96 TEST", 15, "10-14 12:57", "10-14 12:57", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.96A Standard Edition", 15, "10-11 16:45", "10-07 16:06", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.99 Orchestral Edition", 9.0, "10-14 14:35", "10-14 14:35", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.99 Orchestral TEP Expo 2026 Edition", 9.1, "10-12 14:06", "10-11 16:43",
     "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.99A Kaiju Edition-modified", 9.1, "10-14 11:27", "10-14 11:22",
     "changed", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.99A Kaiju Edition", 9.1, "10-14 15:13", "10-11 16:33", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V1.99B Kaiju Edition", 9.1, "10-14 10:56", "10-14 10:35", "ok", "-"),
    ("Godzilla Premium 1.16 Heisei Custom V2 Kaiju Edition", 9.1, "10-26 13:40", "10-19 13:32", "ok", "mounted"),
    ("godzilla_le-1_16_0_spike2", 7.4, "10-14 11:36", "09-19 00:28", "ok", "-"),
    ("king_kong_le-0_97_0", 15, "", "09-27 11:59", "ok", "-"),
]


def _epoch(md):
    return int(time.mktime(time.strptime("2026-" + md, "%Y-%m-%d %H:%M"))) if md else 0


def listing():
    out = []
    for label, gb, boot, copied, st, use in CARDS:
        src = ("/mnt/d/Pinball/images/%s.Release.16G.sdcard.raw" % label if label[0].islower()
               else "/mnt/c/Users/simon/Desktop/Heisei/%s.raw" % label)
        out.append("entry\t%s\t%d\t%d\t%d\t%s" % (label, gb * G * REAL, gb * G, _epoch(boot), src))
        out.append("state\t%s\t%s\t%s\t%d" % (label, st, use, _epoch(copied)))
    used = sum(int(c[1] * G * REAL) for c in CARDS)
    out.append("limit\t64\t%d\t/home/simon/cardcache\tdistro" % used)
    out.append("disk\t%d\t%d" % (1007 * G - used - 60 * G, 1007 * G))
    return "\n".join(out) + "\n"


LAUNCHER = r'''
import subprocess, sys
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import emulate_rig
emulate_rig.rig_available = lambda: True
from pinball_decryptor.webui.tabs import emulate
emulate.EmulateTab._precache_kick = lambda self: None
LISTING = open(%(listing)r, "rb").read()
class _Done:
    def __init__(self, out):
        self.stdout, self.stderr, self.returncode = out, b"", 0
_real = emulate.EmulateTab._run
def _run(self, cmd, **kw):
    if "--cache-list" in " ".join(map(str, cmd)):
        return _Done(LISTING)
    return _Done(b"")
emulate.EmulateTab._run = _run
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pick = "--select-unused" in sys.argv[3:]
    scratch = tempfile.mkdtemp(prefix="pad739-")
    lst = os.path.join(scratch, "listing.txt")
    with open(lst, "w", encoding="utf-8", newline="\n") as f:
        f.write(listing())
    launcher = os.path.join(scratch, "launch739.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % {"tree": tree, "listing": lst})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "PAD_UI_NO_RIG": ""}
    proc, url = webui_shot.start_server(settings, scratch, extra_env=env, app_cmd=[sys.executable, launcher])
    print("tree", tree, "server", url.split("?")[0])
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.select_tab", "emulate")
            time.sleep(2)
            webui_shot.api(url, "emulate.open_cache")
            for _ in range(50):
                c = webui_shot.state(url).get("emulate", {}).get("cache") or {}
                if c and not c.get("busy"):
                    break
                time.sleep(0.2)
            if pick:
                webui_shot.api(url, "emulate.cache_select_unused")
            time.sleep(1.5)
            c = webui_shot.state(url).get("emulate", {}).get("cache") or {}
            print("head:", c.get("head"))
            print("selected:", c.get("sel"), c.get("sel_text"))
            page.locator(".emu-cache").first.screenshot(path=out)
            print("shot", out)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
