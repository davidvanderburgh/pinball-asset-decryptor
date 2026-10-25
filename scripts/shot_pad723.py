"""PAD-723 proof shots: random clips on a title other than Godzilla.

    python scripts/shot_pad723.py <repo> <out_dir> [--after] [--card CARD] [--clips N1,N2,...]

Serves <repo> on a scratch project made from the stock card (default Aerosmith Pro 1.16 from the
library): a few of its in-game video bank's clips copied out with their manifest rows and the
card's record, as a videos extract has them. Writes, under the same names before and after:

- <before_|after_>video_menu.png   the right-click menu of the first clip, "Random clips" opened

Before (main) the menu says random clips have not been tried on this game; after (the ticket
branch) it offers "Add clips to play at random...".

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
CARD = r"D:\Pinball\images\Stern\spike2\aerosmith-1_16_0.Release.8G.sdcard.raw"
CLIPS = ("OilProjectorLoop", "sosad")


def _arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def _project(repo, scratch, card, names):
    """The bank clips *names* of *card*, as a videos extract has them (read with *repo*'s reader)."""
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import clip_variants as CV, engine as E
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_write as MW, video_bank as VB
    from pinball_decryptor.core import extract_source
    g, v = MP.card_from_name(os.path.basename(card))
    prof = MP.profile_for_card(g, v)
    dst = os.path.join(scratch, g)
    os.makedirs(os.path.join(dst, "video"))
    rows = ["# output\tcard path\tbytes"]
    with open(card, "rb") as f:
        reader, _fw, _img = E._locate(f, E._linux_partitions(card))
        bank = reader.read_file_bytes(MW.lookup(reader, CV.bank_scene(prof)))
        paths = {c.name: c.path for c in VB.parse(bank).library.entries if c.path}
        for name in names:
            cpath = CV.bank_assets(prof) + paths[name]
            node = MW.lookup(reader, cpath)
            reader.extract_file(node, os.path.join(dst, "video", name + ".mp4"))
            rows.append("%s.mp4\t/%s\t%d" % (name, cpath, node["size"]))
    with open(os.path.join(dst, "video", "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    extract_source.write_extract_source(dst, card)
    return dst


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch723.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait_scan(state, limit=180):
    deadline = time.time() + limit
    while time.time() < deadline:
        st = state().get("video") or {}
        if st.get("rows") and not st.get("scanning") and "still checking" not in (st.get("status") or ""):
            return st
        time.sleep(1)
    return state().get("video") or {}


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    card = _arg("--card", CARD)
    names = _arg("--clips", ",".join(CLIPS)).split(",")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad723-")
    project = _project(repo, scratch, card, names)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)   # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = _wait_scan(state)
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            row = page.locator(".vid-tbl .tr:has-text('%s')" % names[0]).first
            row.click()
            time.sleep(3)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            row.click(button="right")
            time.sleep(1)
            item = page.locator(".menu .mi:has-text('Random clips')").first
            if item.count():
                item.hover()
                time.sleep(0.8)
            print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            page.screenshot(path=out("video_menu.png"))
            page.keyboard.press("Escape")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
