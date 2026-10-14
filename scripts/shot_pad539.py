"""PAD-539 proof shots: Scenes on a project extracted from a card PAD had written, whose card
has not been read for the boxes the game program names.

    python scripts/shot_pad539.py <repo> <godzilla LE project> <out_dir> [--after] [--probe]
                                  [--card <the project's stock card>] [--node <text layer>]

Copies the project's images/ and text/ to a scratch folder (its scene edits dropped, no
program reading of node paths) and records it as extracted from its own Rev 2, as DragonRR's
was.  Takes, under the same names before and after:

- filled_panel.png  Layers + Selected with a text box the game writes (*--node*) picked.
                    Before: "Not this one", nothing says it is a guess.  After: the same
                    guess, saying so, with Re-read from card.
- scene_note.png    The bar under the preview with the written-card word hovered (after).
- reset_dialog.png  The project menu's Reset… dialog.

and, after only, filled_reread.png: the same panel once Re-read from card has read the card
(*--card*, recorded as the project's source just before the click).  --probe lists the text
layers' marks before and after a re-read instead, to find a *--node* the guesses miss.
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
import shot_pad251_tab as rig  # noqa: E402
from shot_pad339_scenes import SCENE  # noqa: E402


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def _texts(state):
    return {l["id"]: (l["name"], l["filled"]) for l in state()["tree_view"]["layers"]
            if l["kind"] == "Text"}


def main():
    repo, source, out_dir = sys.argv[1:4]
    after, probe = "--after" in sys.argv, "--probe" in sys.argv
    card, node = _arg("--card"), _arg("--node")
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad539-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for rel in ("images/scene_textures/scene_edits.json",
                "images/scene_textures/scene_edits_built.json", "text/program_modes.json"):
        p = os.path.join(project, *rel.split("/"))
        if os.path.isfile(p):
            os.remove(p)
    with open(os.path.join(project, ".pad-lineage.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "id": "pad539", "stock": {
            "sidx": "godzilla_le", "label": "Godzilla LE 1.16", "print": "stock"},
            "source": {"print": "rev2", "name": "Godzilla LE 1.16 rev2.raw", "status": "modified",
                       "label": "Godzilla LE 1.16", "rev": 2},
            "revs": [{"rev": 1, "print": "rev1", "parent": "stock", "parent_rev": 0,
                      "name": "Godzilla LE 1.16 rev1.raw", "built": "2026-10-01 10:00"},
                     {"rev": 2, "print": "rev2", "parent": "rev1", "parent_rev": 1,
                      "name": "Godzilla LE 1.16 rev2.raw", "built": "2026-10-05 10:00"}]}, f)
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text_scenes"]      # noqa: E731
    from playwright.sync_api import sync_playwright

    def reread(page):
        with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
            json.dump({"input_path": card, "input_name": os.path.basename(card),
                       "size": os.path.getsize(card)}, f)
        btn = page.locator(".tg-guess button")
        if btn.count():
            btn.first.click()
        else:
            api("text_scenes.read_program")
        t0 = time.time()
        rig._wait(lambda: state()["tree_view"].get("fills_proven"), 600, 0.5)
        print("re-read took %.1f s; msg: %r" % (time.time() - t0, state().get("rebuild_msg")),
              flush=True)
        time.sleep(3)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1400})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state().get("alive"), 30)
            assert api("text_scenes.select", SCENE)
            rig._wait(lambda: state().get("tree_view") and state().get("frames"), 120)
            rig._wait(lambda: not state().get("tree_busy"), 60)
            tv = state()["tree_view"]
            print("fills_proven:", tv.get("fills_proven"), "base_note:",
                  (tv.get("base_note") or {}).get("chip"), flush=True)
            if probe:
                was = _texts(state)
                reread(page)
                now = _texts(state)
                for i, (name, f) in now.items():
                    print("%-40s guess=%-5s proven=%s" % (name, bool(was[i][1]), f), flush=True)
                return
            ids = [i for i, (name, _f) in _texts(state).items() if name == node]
            assert ids, node
            assert api("text_scenes.tree_select", ids[0])
            time.sleep(3)
            page.locator('.tree-layers [data-node="%s"]' % ids[0]).evaluate(
                "el => el.scrollIntoView({block: 'center'})")
            page.mouse.move(5, 1395)
            time.sleep(2)

            def side(name):
                boxes = [page.locator(s).first.bounding_box()
                         for s in (".tree-layers", ".tree-side")]
                x0 = min(b["x"] for b in boxes) - 8
                y0 = min(b["y"] for b in boxes) - 8
                x1 = max(b["x"] + b["width"] for b in boxes) + 8
                y1 = max(b["y"] + b["height"] for b in boxes) + 8
                page.screenshot(path=name, clip={"x": x0, "y": y0, "width": x1 - x0,
                                                 "height": y1 - y0})

            side(out("filled_panel.png"))
            # the bar under the preview, the written-card word hovered when there is one
            chip = page.locator(".sc-base-note")
            if chip.count():
                chip.first.hover()
                time.sleep(1.5)
            bar = page.locator(".tree-actions").first.bounding_box()
            x0, y0 = max(0, bar["x"] - 8), max(0, bar["y"] - 60)
            x1, y1 = 1600, bar["y"] + 300
            tipbox = page.locator(".tip").first
            if tipbox.count() and tipbox.is_visible():
                b = tipbox.bounding_box()
                x0, y0 = min(x0, b["x"] - 8), min(y0, b["y"] - 8)
                y1 = max(y1, b["y"] + b["height"] + 8)
            page.screenshot(path=out("scene_note.png"), clip={
                "x": x0, "y": y0, "width": x1 - x0, "height": min(1400, y1) - y0})
            page.mouse.move(5, 1395)
            if after and card:
                reread(page)
                side(out("filled_reread.png"))
            # the project menu's Reset…
            page.locator('[aria-label="Project menu"]').first.click()
            time.sleep(1)
            page.get_by_text("Reset…", exact=True).last.click()
            rig._wait(lambda: not (webui_shot.state(url)["shellx"].get("reset") or {}).get("busy"),
                      60)
            time.sleep(2)
            page.locator(".modal").first.screenshot(path=out("reset_dialog.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
