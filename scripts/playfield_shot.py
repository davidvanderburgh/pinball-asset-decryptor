"""Capture the virtual playfield page that scripts/playfield_demo.py serves.

    python scripts/playfield_demo.py field --lcd --window none > pf.log &
    python scripts/playfield_shot.py pf.log shots/playfield/field [chromium|webkit|msedge]

Screenshots the main page, a hovered-and-held switch (the tooltip, the held
ring, the made dot the fake switch block reports back), a key press, the key
panel's Plunge, the save dialog, and the villain vision page. Exits 1 on any
page error, so a CI step fails on a broken page rather than uploading one.
"""
import os
import sys
import time


def main():
    log, out = sys.argv[1], sys.argv[2]
    engine = sys.argv[3] if len(sys.argv) > 3 else "chromium"
    os.makedirs(out, exist_ok=True)
    txt = ""
    for _ in range(120):
        try:
            txt = open(log, encoding="utf8", errors="replace").read()
        except OSError:
            txt = ""
        if "LCDURL" in txt:
            break
        time.sleep(0.5)
    else:
        print(txt)
        sys.exit("the demo never printed its URLs")
    url = [ln.split()[1] for ln in txt.splitlines() if ln.startswith("URL ")][0]
    lcd = [ln.split()[1] for ln in txt.splitlines()
           if ln.startswith("LCDURL ")][0]
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as p:
        if engine == "webkit":
            b = p.webkit.launch()
        elif engine == "msedge":
            b = p.chromium.launch(channel="msedge")
        else:
            b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1180, "height": 900})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
        pg.goto(url)
        pg.wait_for_timeout(3000)
        pg.screenshot(path=os.path.join(out, "main.png"))
        kind = pg.evaluate("document.querySelector('.pf-stage') ? 'field' : "
                           "document.querySelector('.pf-rows') ? 'schematic' "
                           ": 'waiting'")
        print("view:", kind)
        if kind == "field":
            box = pg.locator(".pf-stage canvas").bounding_box()
            st = pg.evaluate("() => fetch('/state?t=' + new URLSearchParams("
                             "location.search).get('t')).then(r => r.json())")
            sc = box["width"] / st["view"]["base"][0]
            k, x, y, sid = st["view"]["switches"][2]
            pg.mouse.move(box["x"] + x * sc + 6, box["y"] + y * sc)
            pg.wait_for_timeout(800)
            pg.screenshot(path=os.path.join(out, "tip.png"))
            pg.mouse.down()
            pg.wait_for_timeout(1000)
            pg.screenshot(path=os.path.join(out, "held.png"))
            pg.mouse.up()
            pg.wait_for_timeout(500)
        elif kind == "schematic":
            row = pg.locator(".pf-rows .r:not(.dead)").nth(3)
            row.hover()
            pg.wait_for_timeout(300)
            pg.mouse.down()
            pg.wait_for_timeout(800)
            pg.screenshot(path=os.path.join(out, "held.png"))
            pg.mouse.up()
        pg.mouse.click(5, 5)
        pg.keyboard.down("ArrowLeft")
        pg.wait_for_timeout(400)
        pg.keyboard.up("ArrowLeft")
        if pg.locator(".kp-btns .btn").count():
            pg.locator(".kp-btns .btn").first.click()
            pg.wait_for_timeout(800)
            pg.screenshot(path=os.path.join(out, "plunge.png"))
        if pg.locator(".pf-states .btn").count():
            pg.locator(".pf-states .btn").first.click()
            pg.wait_for_timeout(400)
            pg.screenshot(path=os.path.join(out, "save.png"))
            pg.keyboard.press("Escape")
        pg2 = b.new_page(viewport={"width": 380, "height": 420})
        pg2.on("pageerror", lambda e: errors.append("lcd: " + str(e)))
        pg2.goto(lcd)
        pg2.wait_for_timeout(4000)
        pg2.screenshot(path=os.path.join(out, "lcd.png"))
        b.close()
    print("page errors:", errors)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
