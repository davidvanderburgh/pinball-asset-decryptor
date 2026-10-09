"""PAD-485 proof shot: Show in Scenes on a game-program line.

    python scripts/shot_pad485.py <repo> <godzilla project> <out_png>

Copies the project's images/ and text/ to a scratch folder (nothing is written to the real
one), opens the Text tab, finds the game program's "GIGAN JACKPOT!" (the Megalon and Gigan
multiball's jackpot award title), gives it a longer line and presses Show in Scenes.  A
build before PAD-485 answers with a dialog (no scene file to show); a build with it opens
Scenes on the jackpot award screen, whose stand-in text reads "GIGAN JACKPOT", with the line
picked out and drawn with the new words.

Round 3: with PAD485_CARD=<card.raw> the game-program rows come from that card instead, as
an extract before PAD-470 wrote them, and the card is the project's source, so the Text tab
re-reads the modes (and, on a build with round 3, each mode's screens) from it when it opens.
PAD485_LINE=KAIJU AWARD on the Heisei card is DragonRR's case.
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


def _program_rows(repo, card, project):
    """The project's game-program rows replaced by *card*'s, as an extract before PAD-470
    wrote them, and *card* recorded as its source."""
    import json
    sys.path.insert(0, repo)
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import progtext
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        raw = img.preview(part, "/%s/game" % game, cap=256 << 20)
    rows = [r for r in text_manifest.load(project)
            if (r.get("path") or "").lower().endswith(".radium")]
    n = 0
    for e in progtext.enumerate_program_strings(raw):
        row = {"path": "/%s/game" % game, "original": e["text"], "replacement": "",
               "budget": e["budget"]}
        row["grow" if e.get("growable") else "fixed"] = True
        rows.append(row)
        n += 1
    text_manifest.save(project, rows)
    st = os.stat(card)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.abspath(card), "input_name": os.path.basename(card),
                   "size": st.st_size, "mtime": int(st.st_mtime)}, f)
    return n


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
    card = os.environ.get("PAD485_CARD")
    if card:
        print("program rows from", card, ":", _program_rows(repo, card, project), flush=True)
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
                       if r and r.get("o") == LINE and r.get("sc") == "game program"
                       and not r.get("pt"))
            api("text.select", hit)
            if NEW_WORDS != "-":
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
