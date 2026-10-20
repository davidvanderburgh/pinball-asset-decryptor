"""PAD-653 proof shots: the Light shows tab's playfield column must keep its width while a show plays.

    python scripts/shot_pad653.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shots). The
same project as scripts/shot_pad646.py (Godzilla Pro 1.15 stock card, a blocks mode with three shows of its own).
The show plays while the column's width is read every 40 ms; writes into <out_dir>:

- <prefix>_light_show_width.png  the playfield column cut out at 9 ms, 312 ms, 1 s and 1.6 s into the show (the
                                 scrubber stops it there), side by side on one fixed frame, so a moving edge shows
- <prefix>_light_show_width.json the widths read (px) and the clock text each was read at
"""

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad646 as P  # noqa: E402
import webui_shot  # noqa: E402

FIELD_JS = """() => { const f = document.querySelector('.ls-field'), c = document.querySelector('.ls-clock'),
    b = document.querySelector('.ls-transport button');
    const r = f.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, clock: c ? c.textContent : '',
    button: b ? [b.textContent.trim(), b.getBoundingClientRect().width] : null }; }"""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import block_modes as BM, mode_project as MP
    from PIL import Image

    scratch = tempfile.mkdtemp(prefix="pad653-")
    project = os.path.join(scratch, "GZ 1.15 Pro Extract")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": P.CARD, "input_name": os.path.basename(P.CARD)}, f)
    slug, _path = BM.new_blocks_mode(project, "KAIJU LIGHTS", example="ramps")
    BM.save(project, slug, P._program(BM, MP, True))
    proc, url = S._serve(repo, scratch, project)
    result = {}
    try:
        def shots(page):
            webui_shot.api(url, "modes.select", slug, "code")
            time.sleep(3)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.get_by_role("tab", name="Light shows").first.click()
            page.wait_for_selector(".ls-field .pf-art, .ls-field .pf-none", timeout=120000)
            time.sleep(1)
            # the readings: every 40 ms over 4 s of the show playing (a pass of Kaiju roar is 3.25 s)
            reads = []
            for _ in range(100):
                reads.append(page.evaluate(FIELD_JS))
                time.sleep(0.04)
            widths = sorted({round(r["w"], 1) for r in reads})
            result.update(widths=widths, buttons=sorted({(r["button"][0], round(r["button"][1], 1)) for r in reads}), reads=[(round(r["w"], 1), r["clock"]) for r in reads])
            # the cut-outs: the scrubber stops the show at four moments whose clock reads differ in length
            # ("9 ms", "312 ms", "1 s", "1.6 s"), the lengths that pushed the column about; same box for all
            frames = []
            for i, ms in enumerate((9, 312, 1000, 1600)):
                page.evaluate("""(ms) => { const s = document.querySelector('.ls-scrub');
                    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    set.call(s, String(ms)); s.dispatchEvent(new Event('input', { bubbles: true })); }""", ms)
                time.sleep(0.5)
                png = os.path.join(scratch, "f%d.png" % i)
                page.screenshot(path=png)
                frames.append((png, page.evaluate(FIELD_JS)))
            x0 = int(min(r["x"] for _p, r in frames))
            y0 = int(min(r["y"] for _p, r in frames))
            box_w = int(max(r["x"] + r["w"] for _p, r in frames) - x0) + 40
            box_h = int(max(r["h"] for _p, r in frames))
            sheet = Image.new("RGB", (box_w * len(frames) + 12 * (len(frames) - 1), box_h), (255, 255, 255))
            for i, (png, _r) in enumerate(frames):
                im = Image.open(png).crop((x0, y0, x0 + box_w, y0 + box_h))
                sheet.paste(im, (i * (box_w + 12), 0))
            out = os.path.join(out_dir, "%s_light_show_width.png" % prefix)
            sheet.save(out)
            result["frames"] = [(round(r["w"], 1), r["clock"]) for _p, r in frames]
            print("shot", out, flush=True)
        S._shoot(url, shots, height=1150)
    finally:
        proc.terminate()
        with open(os.path.join(out_dir, "%s_light_show_width.json" % prefix), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        print("widths:", result.get("widths"), "buttons:", result.get("buttons"), "frames:", result.get("frames"), flush=True)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
