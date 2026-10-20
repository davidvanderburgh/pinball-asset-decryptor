r"""PAD-649 before/after: the playfield window's rig band and chip for rig 5.

    PAD_PWLIB=C:\tmp\pwlib python scripts/shot_pad649.py <checkout> <out.png>

Serves <checkout>'s scripts/playfield_demo.py (field view, page only) as rig 5
for PAD-649 (PAD_SLOT / PAD_LABEL, which padpath.slot() / label() read) and
captures the top of the page: the band across it and the "rig 5 . PAD-649"
chip. Before this ticket the page clamped the rig to 4 and the stylesheet had
no fifth colour, so rig 5 wore rig 4's green; now it is amber (pf.css --rig-5).
"""
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("PAD_PWLIB"):
    sys.path.insert(0, os.environ["PAD_PWLIB"])


def main():
    checkout, out = sys.argv[1], sys.argv[2]
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False).name
    env = dict(os.environ, PAD_SLOT="5", PAD_LABEL="PAD-649")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(checkout, "scripts", "playfield_demo.py"),
         "field", "--window", "none", "--seconds", "60"],
        stdout=open(log, "w"), stderr=subprocess.STDOUT, cwd=checkout, env=env)
    try:
        url = None
        for _ in range(120):
            txt = open(log, encoding="utf8", errors="replace").read()
            urls = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("URL ")]
            if urls:
                url = urls[0]
                break
            time.sleep(0.5)
        if not url:
            sys.exit("the demo never printed its URL:\n" + txt)
        from playwright.sync_api import sync_playwright
        errors = []
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1180, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            pg.wait_for_timeout(3000)
            pg.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1180, "height": 120})
            print("data-rig:", pg.locator("#app").get_attribute("data-rig"),
                  "chip:", pg.locator(".pf-rig").all_inner_texts(),
                  "band:", pg.evaluate("getComputedStyle(document.querySelector('#app')).borderTopColor"))
            b.close()
        if errors:
            sys.exit("page errors: %r" % errors)
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
