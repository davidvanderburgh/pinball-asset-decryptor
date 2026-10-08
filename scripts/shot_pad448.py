"""PAD-448 proof shots: Compare's Advanced box and lock marks, and a clip's own color
profile drawn on the players the way Scenes draws a picture's.

    python scripts/shot_pad448.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch Godzilla project with four video slots made from
mode clips: two replaced (King Ghidorah with "Blue to violet", a profile made of a color
range alone; Mothra with "Warm grade", sliders alone; both attached) and two left as the
game's own clips (atomic breath in pad312_clip.mp4 with "Sepia" waiting as its own
profile, Shin Godzilla).  Photographs, under the same names before and after:

- compare.png           the four in Compare, King Ghidorah clicked (the Colors bar on it)
- compare_attached.png  Advanced ticked and the atomic breath clip's profile attached
                        in Compare
- video_main.png        back on the list, the atomic breath clip selected, the two players

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
import shot_pad312 as base  # noqa: E402
import shot_pad360 as saved  # noqa: E402

# (slot, mode clip it is a copy of, replaced?, own profile)
VIOLET = {"name": "Blue to violet", "gamma": [1.0, 1.0, 1.0], "gain": [1.0, 1.0, 1.0],
          "lift": [0.0, 0.0, 0.0], "saturation": 1.0,
          "ranges": [[215.0, 100.0, 30.0, 75.0, 1.3, 1.0, 0.1]]}
WARM = {"name": "Warm grade", "gamma": [1.0, 1.05, 1.2], "gain": [1.15, 1.0, 0.8],
        "lift": [0.02, 0.02, 0.02], "saturation": 1.35, "brightness": 1.0,
        "contrast": 1.05}
SEPIA = {"name": "Sepia", "gamma": [0.95, 1.0, 1.15], "gain": [1.3, 1.05, 0.75],
         "lift": [0.03, 0.02, 0.0], "saturation": 0.6}
STOCK = base.VIDEO
CLIPS = (
    ("video/pad448_ghidorah.mp4", "king_ghidorah", True, VIOLET),
    ("video/pad448_mothra.mp4", "mothra_s_song", True, WARM),
    (STOCK, "atomic_breath", False, SEPIA),
    ("video/pad448_shin.mp4", "shin_godzilla", False, None),
)


def _clips(scratch, project):
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    picks = data.setdefault("video", {})
    owns = {}
    for rel, mode, replaced, own in CLIPS:
        src = os.path.join(base.SOURCE, "modes", mode, "clip.mp4")
        dst = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if replaced:
            mine = os.path.join(scratch, "my_%s.mp4" % mode)
            shutil.copy2(src, mine)
            picks[rel] = mine
        else:
            picks.pop(rel, None)
        if own:
            owns[rel] = own
    data["video_color_slots"] = {rel: True for rel, _m, rep, _o in CLIPS if rep}
    data["video_color_profiles"] = owns
    data.pop("video_color_stock", None)
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # the clips are the card's own as far as the tab can tell: in the extract's
    # baseline, so none reads "not on this card" or "already modified"
    import hashlib
    with open(os.path.join(project, ".checksums.md5"), "a", encoding="utf-8",
              newline="\r\n") as f:
        for rel, _m, _r, _o in CLIPS:
            with open(os.path.join(project, *rel.split("/")), "rb") as clip:
                f.write("%s\t%s\n" % (rel, hashlib.md5(clip.read()).hexdigest()))


def _seek_all(page, selector, t=2.5):
    """Every player on show at the same moment, so the frames compare."""
    page.evaluate("""([sel, t]) => Promise.all([...document.querySelectorAll(sel)].map((v) =>
        new Promise((ok) => { const done = () => ok(); v.addEventListener('seeked', done, { once: true });
          v.addEventListener('error', done, { once: true }); v.currentTime = t; setTimeout(done, 4000); })))""",
                  [selector, t])


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad448-")
    project = base._project(scratch)
    _clips(scratch, project)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    tag = "after_" if after else "before_"
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731

    def settle(page):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                                   # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 990)
        time.sleep(1.5)

    def report(name, page):
        v = state().get("video") or {}
        print(name, "tiles:", [(t.get("rel"), t.get("side"), len(t.get("look") or []),
                               bool(t.get("lut")))
                              for t in ((v.get("compare") or {}).get("tiles") or [])],
              "look:", {k: (v.get("look") or {}).get(k) for k in ("on", "lut")},
              "stock:", v.get("color_stock"), flush=True)
        print(name, "gl canvases shown:", page.evaluate(
            "[...document.querySelectorAll('canvas.vid-gl')].map((c) => c.style.visibility)"),
            flush=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            print("webgl2:", page.evaluate(
                "!!document.createElement('canvas').getContext('webgl2')"), flush=True)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            api("ui.set", "video", "search", "video/pad")
            time.sleep(2)
            names = [rel.split("/")[-1] for rel, _m, _r, _o in CLIPS]
            row = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            row(names[0]).click()
            time.sleep(1.5)
            for n in names[1:]:
                row(n).click(modifiers=["Control"])
                time.sleep(0.4)
            page.click(".vid-cmp-open")
            time.sleep(3)
            tile = lambda n: page.locator(".vcm-tile", has_text=n)  # noqa: E731
            tile(names[0]).locator(".vcm-screen").click()
            time.sleep(2)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            _seek_all(page, ".vcm-tile video")
            settle(page)
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
            report("compare", page)
            page.screenshot(path=out("compare.png"))

            # Advanced, then the atomic breath clip's own profile attached, from Compare
            if after:
                page.locator(".vcm-adv input").click()
                time.sleep(1.5)
                tile(names[2]).locator(".vid-color").click()
            else:
                # no box in Compare before: the same state through the tab's calls
                api("video.set_color_stock", True)
                time.sleep(1)
                api("video.set_color", STOCK, True)
            time.sleep(2)
            tile(names[2]).locator(".vcm-screen").click()
            time.sleep(2)
            _seek_all(page, ".vcm-tile video")
            settle(page)
            report("compare_attached", page)
            page.screenshot(path=out("compare_attached.png"))

            # back on the list, the atomic breath clip's row: the two players
            page.keyboard.press("Escape")
            time.sleep(2)
            if page.locator(".vcm").count():
                api("video.compare_close")
                time.sleep(2)
            row(names[2]).click()
            time.sleep(4)
            _seek_all(page, ".vid-screen video")
            settle(page)
            report("video_main", page)
            pv = (state().get("video") or {}).get("preview") or {}
            print("panes:", {k: (pv.get(k) or {}).get("title") for k in ("orig", "rep")},
                  flush=True)
            page.screenshot(path=out("video_main.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
