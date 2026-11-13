r"""PAD-1237 proof: the virtual playfield window's bottom bar with long words.

    python scripts/shot_pad1237_playfield.py <tree> <out png> [--width N]

<tree> is the source tree whose playfield is served (a ``git archive`` of main
for the "before" shot, the ticket branch for "after"): scripts/playfield_demo.py
with no emulator, handed a volume file as the app hands it (PAD_AUDIO_CTL), so
the bar carries Stop emulator, Pause, Restart game, Volume, Mute and the save
states. The page's first /state answer is given the boot step David saw
("98% Guided Setup is waiting for you: ...") and a long status line, so the
words compete with the controls. Prints where each control's right edge falls
against the window's, whether the words are cut, and the tooltip they carry.
Writes <out png> (the whole window) and <out>_bar.png (the bottom bar).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

GUIDED = ("Guided Setup is waiting for you: press Save & Exit (Backspace moves to it, "
          "Enter selects) to finish it and the game reaches attract mode")
STATUS = ("trough 6 of 6 | feeder: trough full, waiting for a game | "
          "switches 70-75 closed | coin door closed")


def main():
    tree, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    width = int(sys.argv[sys.argv.index("--width") + 1]) if "--width" in sys.argv else 1000
    scratch = tempfile.mkdtemp(prefix="pad1237pf-")
    ctl = os.path.join(scratch, "audio_ctl.json")
    with open(ctl, "w", encoding="utf-8") as f:
        f.write('{"gain": 0.2, "muted": false}')
    env = dict(os.environ, PAD_AUDIO_CTL=ctl, PAD_SLOT="1", PAD_LABEL="")
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

        def state(route):
            r = route.fetch()
            S = r.json()
            run = S.get("run") or {}
            run["boot"] = {"pct": 98, "words": GUIDED}
            S["run"] = run
            S["status"] = STATUS
            route.fulfill(response=r, body=json.dumps(S),
                          headers={**r.headers, "content-type": "application/json"})

        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": width, "height": 700})
            pg.route("**/state?*", state)
            pg.goto(url)
            pg.wait_for_timeout(3000)
            # the demo's frames carry their own status line; put ours back
            pg.evaluate("t => { const s = document.querySelector('.pf-status .txt');"
                        " if (s) s.textContent = t; }", STATUS)
            info = pg.evaluate("""() => {
              const W = document.documentElement.clientWidth;
              const r = (sel) => { const e = document.querySelector(sel);
                return e ? Math.round(e.getBoundingClientRect().right) : null; };
              const cut = (sel) => { const e = document.querySelector(sel);
                return e ? e.scrollWidth > e.clientWidth : null; };
              const tip = (sel) => { const e = document.querySelector(sel);
                if (!e) return null;
                e.dispatchEvent(new PointerEvent('pointerenter'));
                return e.getAttribute('title'); };
              return {window: W,
                      mute_right: r('.pf-run .mute'), states_right: r('.pf-states'),
                      load_state_right: r('.pf-states .btn:last-child'),
                      boot_words_cut: cut('.pf-run .boot .w'),
                      boot_tip: tip('.pf-run .boot'),
                      status_cut: cut('.pf-status .txt'),
                      status_tip: tip('.pf-status .txt')};
            }""")
            for k, v in info.items():
                print("%-16s %s" % (k, v))
            pg.screenshot(path=out)
            bar = os.path.splitext(out)[0] + "_bar.png"
            pg.locator(".pf-status").screenshot(path=bar)
            print("shot", out, "and", bar)
            b.close()
    finally:
        demo.kill()


if __name__ == "__main__":
    main()
