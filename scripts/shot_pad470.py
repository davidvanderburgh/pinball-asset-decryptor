"""PAD-470 proof shot: the Text tab on a card where two battles' award lines read the same.

    python scripts/shot_pad470.py <repo> <card.raw> <out_png> [edit]

Builds a scratch project whose text/strings.tsv holds the card's game-program rows the way
an extract made before PAD-470 wrote them (one row per text, no modes) and an
.extract_source.json pointing at the card, so a build with PAD-470 brings the project up to
date from the card when the Text tab opens - the path an existing project takes. Opens the
Text tab, searches "KAIJU AWARD" and prints the rows. With ``edit`` (a build that has the
rows) the Battle vs Gigan row gets GIGAN AWARD and the Battle vs Megalon row SPACEGODZILLA
JACKPOT, and the Megalon row is left selected so its note shows.
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

QUERY = os.environ.get("PAD470_QUERY") or "KAIJU AWARD"
EDITS = {"Battle vs Gigan": "GIGAN AWARD", "Battle vs Megalon": "SPACEGODZILLA JACKPOT"}


def _project(repo, card, project):
    """The card's program rows, as an extract before PAD-470 wrote them."""
    sys.path.insert(0, repo)
    from pinball_decryptor.core import text_manifest
    from pinball_decryptor.plugins.stern import progtext
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        raw = img.preview(part, "/%s/game" % game, cap=256 << 20)
    rows = []
    for e in progtext.enumerate_program_strings(raw):
        row = {"path": "/%s/game" % game, "original": e["text"], "replacement": "",
               "budget": e["budget"]}
        row["grow" if e.get("growable") else "fixed"] = True
        if e.get("refs") == 0:
            row["unused"] = True
        rows.append(row)
    os.makedirs(project, exist_ok=True)
    text_manifest.save(project, rows)
    st = os.stat(card)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.abspath(card), "input_name": os.path.basename(card),
                   "size": st.st_size, "mtime": int(st.st_mtime)}, f)
    # an extract leaves its checksums; the tabs that work on one look for them
    open(os.path.join(project, ".checksums.md5"), "w").close()
    return len(rows)


def main():
    repo, card, out = sys.argv[1:4]
    edit = "edit" in sys.argv[4:]
    print("repo:", repo, flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad470-")
    project = os.path.join(scratch, "heisei")
    print("program rows written:", _project(repo, card, project), flush=True)
    os.environ["PAD251_CARD"] = card
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)["text"]             # noqa: E731
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
            page.locator(".rail").get_by_text("Text", exact=True).first.click()
            rig._wait(lambda: state().get("rows"), 120, 0.5)
            rig._wait(lambda: not state().get("scanning"), 300, 0.5)
            box = page.locator(".text-page .search input").first
            box.click()
            box.fill(QUERY)
            time.sleep(1.0)
            s = state()
            hits = [i for i, r in enumerate(s["rows"]) if r and r.get("o") == QUERY]
            for i in hits:
                r = s["rows"][i]
                print("row %d: %r in=%r own-row=%s" % (i, r["o"], r.get("in"), bool(r.get("pt"))),
                      flush=True)
            if edit:
                last = None
                for i in hits:
                    r = s["rows"][i]
                    if r.get("pt") and r.get("in") in EDITS:
                        api("text.select", i)
                        api("text.apply", EDITS[r["in"]])
                        last = i if r["in"] == "Battle vs Megalon" else last
                        print("applied %r to %s" % (EDITS[r["in"]], r["in"]), flush=True)
                if last is not None:
                    api("text.select", last)
            elif hits:
                api("text.select", hits[0])
            time.sleep(1.0)
            print("note:", state().get("scene_note"), flush=True)
            page.mouse.move(5, 895)
            time.sleep(2)
            page.screenshot(path=out)
            with open(os.path.join(project, "text", "strings.tsv"), encoding="utf-8") as f:
                for line in f:
                    if QUERY in line:
                        print("tsv:", line.rstrip("\n"), flush=True)
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
