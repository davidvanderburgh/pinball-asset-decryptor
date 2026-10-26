r"""PAD-735 proof: the virtual playfield window's status bar, with Restart game.

    python scripts/shot_pad735_playfield.py <tree> <out png> [--click]

<tree> is the source tree whose playfield is served (a ``git archive`` of main
for the "before" shot, the ticket branch for "after"): scripts/playfield_demo.py
with no emulator, handed a volume file as the app hands it (PAD_AUDIO_CTL), so
the bar is the one an app-launched run shows. --click presses Restart game and
says whether the request the app's poll reads was written.
"""
import os
import subprocess
import sys
import tempfile
import time


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    click = "--click" in sys.argv[3:]
    scratch = tempfile.mkdtemp(prefix="pad735pf-")
    ctl = os.path.join(scratch, "audio_ctl.json")
    with open(ctl, "w", encoding="utf-8") as f:
        f.write('{"gain": 0.0, "muted": true}')
    env = dict(os.environ, PAD_AUDIO_CTL=ctl, PAD_SLOT="2", PAD_LABEL="PAD-735")
    log = os.path.join(scratch, "pf.log")
    demo = subprocess.Popen(
        [sys.executable, os.path.join(tree, "scripts", "playfield_demo.py"), "field",
         "--window", "none", "--seconds", "120"],
        stdout=open(log, "w", encoding="utf-8"), stderr=subprocess.STDOUT, env=env)
    try:
        url = None
        for _ in range(120):
            txt = open(log, encoding="utf-8", errors="replace").read()
            urls = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("URL ")]
            if urls:
                url = urls[0]
                break
            time.sleep(0.5)
        if not url:
            sys.exit("the demo never printed its URL:\n" + txt)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1180, "height": 900})
            pg.goto(url)
            pg.wait_for_timeout(3000)
            print("status bar buttons:",
                  pg.evaluate("Array.from(document.querySelectorAll('.pf-run .btn'))"
                              ".map(b => b.textContent)"))
            pg.screenshot(path=out)
            print("shot", out)
            if click:
                pg.get_by_role("button", name="Restart game").click()
                pg.wait_for_timeout(1000)
                req = os.path.join(scratch, "restart_game_2.req")
                print("after the click:",
                      pg.evaluate("Array.from(document.querySelectorAll('.pf-run .btn'))"
                                  ".map(b => b.textContent + (b.disabled ? ' (greyed)' : ''))"),
                      "| request for the app:", req if os.path.isfile(req) else "NOT WRITTEN")
            b.close()
    finally:
        demo.kill()


if __name__ == "__main__":
    main()
