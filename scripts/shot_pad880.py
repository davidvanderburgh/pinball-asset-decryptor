"""PAD-880 proof shot: the Write Failed dialog for a card whose longer songs pass what the
machine holds in memory beside image.bin.

    python scripts/shot_pad880.py <repo> <out_png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shot).  The refusal is the real one: the real write pipeline runs, its engine's
write_image stood in by the real sound bank planner over an Iron Maiden shaped card (image.bin
1,311 MB, a dozen of the user's songs in parts, each with a copied part of the game's), and the
app's own _on_done shows what that run handed it.  Nothing is read or staged.
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
import os, sys, tempfile, pathlib
sys.path.insert(0, %r)
from pinball_decryptor.webui import host

MB = 1000000
#: the user's songs (idx: (MB, its file)), longest first, with a part of the game's each
SONGS = {673: (144, "idx0673.wav"), 950: (131, "idx0950.wav"), 281: (124, "idx0281.wav"),
         41: (122, "idx0041.wav"), 307: (118, "idx0307.wav"),
         575: (90, "idx0575 - MUSIC NUMBER.wav"), 150: (79, "idx0150.wav"),
         70: (76, "idx0070 - MUSIC POWERSLAVE.wav"), 891: (68, "idx0891.wav"),
         623: (57, "idx0623.wav")}


def _refuse(*a, **k):
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec
    from tests.test_pad779_songs_in_parts_in_banks import _desc, _key
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="pad880img-"))
    img = _image(tmp, md_off=1311 * MB, count=1000)
    params = [{"idx": i, "chan": 2, "length": 1000 + i, "findkey": _key(i)}
              for i in range(1, 1000)]
    grows = {i: (1000, n * MB // 4) for i, (n, _f) in SONGS.items()}
    edits = {i: "E:/Iron Maiden/audio/" + f for i, (_n, f) in SONGS.items()}
    seqs = [BB.SeqGroup([i], {900 + n: [i, i + 1]}, {900 + n: _desc(i, i + 1)}, [i, i + 1])
            for n, i in enumerate(SONGS)]
    os.environ[BB.BANK_CAP_ENV] = "1000"
    E._read_stock_directory = lambda gr, im: MD.Directory(
        b"".join(_rec(i) for i in range(1000)), 1000, 0x9000, 0)
    E._plan_sound_banks("game", str(img), params, edits, grows, dict(grows), [], _Reader(),
                        None, None, lambda *a: None, game_seqs=seqs)
    raise AssertionError("the planner did not refuse")


_build = host.build


def build(ctx=None, meanwhile=None):
    ctx, server = _build(ctx, meanwhile)

    def fail():
        from pinball_decryptor.plugins.stern import pipeline as pl
        pl.detect_game = lambda p: "iron_maiden_le"
        pl._require_engine = lambda: None
        pl._log_multi_image = lambda p, log: None
        pl.engine.write_image = _refuse
        pl.engine.read_build_manifest = lambda p: {}
        done = []
        pl.SternWritePipeline("a.raw", "assets", "out.raw", lambda *a, **k: None,
                              lambda *a, **k: None, lambda *a, **k: None,
                              lambda ok, summary: done.append(summary)).run()
        app = ctx.app

        def show():
            app._active_mode = "write"
            app._on_done(False, done[0])
        ctx.loop.post(show)
        return done[0]
    ctx.registry.register("shot.fail", fail, on_loop=False)
    return ctx, server


host.build = build
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad880-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch880.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": repo + os.pathsep + site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            print("summary:", webui_shot.api(url, "shot.fail"), flush=True)
            time.sleep(3)
            page.mouse.move(5, 995)
            page.screenshot(path=out)
            print("saved", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
