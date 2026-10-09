"""PAD-424 proof shot: the virtual playfield while the cabinet's shaker runs.

    python scripts/shot_pad424.py <repo> <out_png> [art.png]

<repo> is the tree whose playfield to serve (the ticket branch, or a ``git archive`` of main
for the "before" shot, with this branch's scripts/playfield_demo.py and coilmap.py copied in).
It runs scripts/playfield_demo.py there with no emulator: the demo's fake padled block
drives the shaker (node 1 coil 0) through a 7 s cycle of a long soft shake and three hard
ones. The shot is taken during the last of them, so the trace holds all four.
"""

import os
import subprocess
import sys
import tempfile
import time


def main():
    repo, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    art = sys.argv[3] if len(sys.argv) > 3 else None
    log = tempfile.mktemp(prefix="pad424-", suffix=".log")
    cmd = [sys.executable, os.path.join(repo, "scripts", "playfield_demo.py"), "field",
           "--window", "none", "--seconds", "90"]
    if art:
        cmd += ["--art", art]
    with open(log, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=repo)
    try:
        url = None
        for _ in range(120):
            txt = open(log, encoding="utf8", errors="replace").read()
            got = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("URL ")]
            if got:
                url = got[0]
                break
            time.sleep(0.5)
        if not url:
            sys.exit("the demo never printed its URL:\n" + txt)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1180, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            pg.wait_for_timeout(9000)           # a whole cycle of history in the trace
            has = pg.evaluate("!!document.querySelector('.pf-shaker')")
            if has:
                # the 334 ms shake: the last of the cycle, all four on the trace
                pg.wait_for_function("() => { const n = document.querySelector('.pf-shaker .now');"
                                     " return n && n.textContent.includes('of 0.3 s'); }",
                                     timeout=15000)
            else:
                pg.wait_for_timeout(500)
            pg.screenshot(path=out)
            print("shot", out, "shaker panel:", has, flush=True)
            b.close()
        if errors:
            sys.exit("page errors: %s" % errors)
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
