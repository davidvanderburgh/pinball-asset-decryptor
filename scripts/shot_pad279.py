"""PAD-279 proof shots: picking several layers at once in the Scenes tab (Ctrl / Shift click).

    python scripts/shot_pad279.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects,
never edits), opens Scenes on Godzilla's KAIJU BATTLE SELECT, clicks one line of text in the Layers
list and Ctrl-clicks the other lines of text on the screen, and writes:

- <prefix>_multiselect.png  the page after the clicks
- <prefix>_notes.txt        what the page reports as selected
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad279-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = []

    def describe(tag):
        tv = state()["text_scenes"]["tree_view"]
        notes.append("%s: sel %s, sels %s, props %s" % (
            tag, tv["sel"], tv.get("sels"), (tv.get("props") or {}).get("name")))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", rig.BATTLE)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 90)
            time.sleep(1.5)
            tv = state()["text_scenes"]["tree_view"]
            texts = []
            for h in tv["hits"]:
                if h["kind"] == "text" and h["id"] not in texts:
                    texts.append(h["id"])
            picks = texts[:4]
            notes.append("text rows clicked (the first plain, the rest with Ctrl): %s" % picks)

            def row(n):
                r = page.locator('.tree-layers [data-node="%d"] .sc-t' % n)
                r.scroll_into_view_if_needed()
                return r
            row(picks[0]).click()
            rig._wait(lambda: state()["text_scenes"]["tree_view"]["sel"] == picks[0], 20)
            time.sleep(0.8)
            for n in picks[1:]:
                row(n).click(modifiers=["Control"])
                time.sleep(1.2)
            rig._wait(lambda: not state()["text_scenes"].get("tree_busy"), 30)
            time.sleep(1.5)
            page.mouse.move(5, 995)                     # no tooltip over the list
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out, "%s_multiselect.png" % prefix))
            describe("after the clicks")
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_notes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
