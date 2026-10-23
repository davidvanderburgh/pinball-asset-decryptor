"""PAD-695 proof: the Rules sheet dialog's Print... button, served from <repo> on a copy of David's Heisei modes.

    python scripts/shot_pad695.py <repo> <out_dir> <prefix>

Writes <prefix>_rules_dialog.png (the dialog with its footer buttons). When the tree has Print...: clicks it with
the preview's print() watched (a headless browser cannot show the print dialog), and prints the very page the
preview shows through Edge's print engine (the one WebView2 uses) to <prefix>_printed.pdf, saying its pages and
their size.
"""

import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad664 as S664  # noqa: E402
import shot_pad666 as S6  # noqa: E402


def main():
    repo, out_dir, prefix = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad695-")
    project = S6._project(scratch)
    S664._copy_modes(S664.HEISEI, project)
    proc, url = S._serve(repo, scratch, project)
    try:
        def go(page):
            time.sleep(5)
            S6._hide_log(page)
            page.locator(".modes-list-acts button", has_text="Rules sheet").first.click()
            page.wait_for_selector(".rs-preview iframe", timeout=120000)
            time.sleep(3)
            btn = page.locator(".rs-modal button", has_text="Print")
            if btn.count():
                btn.first.hover()
                time.sleep(1.5)
            out = os.path.join(out_dir, "%s_rules_dialog.png" % prefix)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            if not btn.count():
                print("no Print button in this tree", flush=True)
                return
            page.evaluate("""() => { const w = document.querySelector('.rs-preview iframe').contentWindow;
                window.__printed = 0; w.print = () => { window.__printed += 1; }; }""")
            btn.first.click()
            time.sleep(1)
            print("print() called on the preview:", page.evaluate("window.__printed"), flush=True)
            for paper in ("letter", "a4"):
                page.locator(".rs-modal .seg button, .rs-modal button", has_text=paper.capitalize() if paper == "letter" else "A4").first.click()
                time.sleep(2)
                doc = page.evaluate("document.querySelector('.rs-preview iframe').srcdoc")
                ctx2 = page.context.browser.new_context()
                p2 = ctx2.new_page()
                p2.set_content(doc)
                p2.emulate_media(media="print")
                p2.evaluate("window.padFitPage && window.padFitPage()")
                pdf = p2.pdf(prefer_css_page_size=True, print_background=True)
                ctx2.close()
                path = os.path.join(out_dir, "%s_printed_%s.pdf" % (prefix, paper))
                with open(path, "wb") as f:
                    f.write(pdf)
                boxes = re.findall(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\]", pdf)
                print(paper, "printed pages:", len(re.findall(rb"/Type\s*/Page[^s]", pdf)),
                      "size(pt):", [(float(w), float(h)) for w, h in boxes], path, flush=True)
        S._shoot(url, go, height=1000)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
