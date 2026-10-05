"""PAD-380 proof shots: "What a mode can and can't do", and Display priority's words.

    python scripts/shot_pad380.py <repo> <out_dir> <prefix>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots). Writes into <out_dir>:

- <prefix>_first_mode.png  a Godzilla Pro 1.15 project with no mode yet: the first mode's page
- <prefix>_new_menu.png    the same project with one form mode: the New menu open
- <prefix>_show_page.png   that form mode's Show page, with its Display priority row
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402


def _shot(page, out_dir, prefix, name):
    out = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
    page.screenshot(path=out)
    print("shot", out, flush=True)


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import mode_project as MP

    scratch = tempfile.mkdtemp(prefix="pad380a-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    proc, url = S._serve(repo, scratch, project)
    try:
        S._shoot(url, lambda page: _shot(page, out_dir, prefix, "first_mode"))
    finally:
        proc.terminate()

    scratch = tempfile.mkdtemp(prefix="pad380b-")
    project = S._project(scratch, "GZ 1.15 Pro Extract")
    slug = MP.new_mode(project, spec=MP.ModeSpec(name="TARGET RUSH", title=MP.GODZILLA_PRO_1_15.key,
                                                 priority=180))
    slug = slug[0] if isinstance(slug, tuple) else slug
    proc, url = S._serve(repo, scratch, project)
    try:
        def menu_and_show(page):
            page.get_by_role("button", name="New").first.click()
            time.sleep(1)
            _shot(page, out_dir, prefix, "new_menu")
            page.keyboard.press("Escape")
            time.sleep(0.5)
            webui_shot.api(url, "modes.select", os.path.basename(str(slug)), "form")
            time.sleep(2)
            page.get_by_role("tab", name="Show").first.click()
            time.sleep(1.5)
            _shot(page, out_dir, prefix, "show_page")
        S._shoot(url, menu_and_show, height=1100)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
