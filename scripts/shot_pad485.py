"""PAD-485 proof shot: Show in Scenes on a game-program line.

    python scripts/shot_pad485.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens the Text tab, finds the game program's "GIGAN JACKPOT!" (the Megalon and Gigan
multiball's jackpot award title), gives it a longer line and presses Show in Scenes.  A
build before PAD-485 answers with a dialog (no scene file to show); a build with it opens
Scenes on the jackpot award screen, whose stand-in text reads "GIGAN JACKPOT", with the line
picked out and drawn with the new words.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402

LINE = os.environ.get("PAD485_LINE") or "GIGAN JACKPOT!"
NEW_WORDS = os.environ.get("PAD485_WORDS") or "GIGAN UNLEASHES THE KAIJU JACKPOT!"


def main():
    repo, source, out = sys.argv[1:4]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad485-")
    project = os.path.join(scratch, "gz")
    for sub in ("images", "text"):
        if os.path.isdir(os.path.join(source, sub)):
            shutil.copytree(os.path.join(source, sub), os.path.join(project, sub))
    for name in ("scene_edits.json", "scene_edits_built.json", "scene_edits_carried.json"):
        p = os.path.join(project, "images", "scene_textures", name)
        if os.path.isfile(p):
            os.remove(p)
    # an extract leaves its checksums; the tabs that work on one look for them
    open(os.path.join(project, ".checksums.md5"), "w").close()
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    text = lambda: webui_shot.state(url)["text"]              # noqa: E731
    scenes = lambda: webui_shot.state(url)["text_scenes"]     # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Text", exact=True).first.click()
            rig._wait(lambda: text().get("rows"), 120, 0.5)
            rig._wait(lambda: not text().get("scanning"), 300, 0.5)
            box = page.locator(".text-page .search input").first
            box.click()
            box.fill(LINE)
            time.sleep(1.0)
            s = text()
            hit = next(i for i, r in enumerate(s["rows"])
                       if r and r.get("o") == LINE and r.get("sc") == "game program")
            api("text.select", hit)
            api("text.apply", NEW_WORDS)
            api("text.select", hit)
            time.sleep(1.0)
            print("row:", text()["rows"][hit], flush=True)
            page.locator(".text-page").get_by_role("button", name="Show in Scenes…").first.click()
            time.sleep(2.0)
            sc = scenes()
            if sc.get("alive") and sc.get("sel"):
                rig._wait(lambda: not scenes().get("rebuilding"), 600)
                rig._wait(lambda: scenes().get("tree_view") and scenes().get("frames"), 120)
                rig._wait(lambda: not scenes().get("tree_busy"), 60)
                time.sleep(1.5)
                sc = scenes()
                props = (sc.get("tree_view") or {}).get("props") or {}
                print("scenes: sel=%r item=%r search=%r" % (sc.get("sel"), sc.get("item"),
                                                            sc.get("search")), flush=True)
                print("picked:", props.get("name"), "words:", props.get("words"), flush=True)
            else:
                print("no Scenes opened", flush=True)
            page.mouse.move(5, 995)
            time.sleep(2)
            page.screenshot(path=out)
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
