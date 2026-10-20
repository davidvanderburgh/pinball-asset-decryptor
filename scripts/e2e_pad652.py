"""PAD-652 end-to-end: every way through the new-mode wizard makes its mode, in the served app.

    python scripts/e2e_pad652.py <repo>

A Godzilla Pro 1.15 project with no mode. Through the page: the first-mode page's Blocks tile
(name, Make it), New mode > C (name, a brief, Make it and copy for an agent: the clipboard
gets the agent's words, naming the mode's file and MODE_SDK.md), New mode > Form > Blank mode,
and New mode > Form > KAIJU RUSH. Each must add its mode to the project's modes folder.
Prints PASS or the first FAIL.
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import shot_pad652 as P  # noqa: E402


# the served app opens a new C mode's file: here it is only noted, never opened on the desktop
S.LAUNCHER = r'''
import os, sys
sys.path.insert(0, %r)
def _noted(path, *a, **k):
    with open(os.path.join(os.environ.get("TEMP", "."), "pad652_opened.txt"), "a", encoding="utf-8") as f:
        f.write(str(path) + "\n")
os.startfile = _noted
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _modes(project):
    d = os.path.join(project, "modes")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def _wait_new(project, before, secs=20):
    end = time.time() + secs
    while time.time() < end:
        now = _modes(project)
        new = [m for m in now if m not in before]
        if new:
            return new
        time.sleep(0.3)
    return []


def main():
    repo = os.path.abspath(sys.argv[1])
    sys.path.insert(0, repo)
    scratch = tempfile.mkdtemp(prefix="pad652e-")
    project = P._project(scratch)
    proc, url = S._serve(repo, scratch, project)
    fails = []

    def check(what, ok, more=""):
        print(("ok   " if ok else "FAIL ") + what + (": " + more if more else ""), flush=True)
        if not ok:
            fails.append(what)

    def flow(page):
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        time.sleep(4)
        P._hide_log(page)
        new_btn = page.locator(".modes-list .hd button", has_text="New mode").first

        # 1. the first-mode page's Blocks tile opens the wizard at Blocks
        before = _modes(project)
        page.locator('.modes-first .nmw-tile[data-kind="blocks"]').first.click()
        time.sleep(0.6)
        check("first-mode tile opens the Blocks step", page.locator(".nmw", has_text="New mode: Blocks").count() == 1)
        page.locator("#nmw-blocks-name").fill("WIZ BLOCKS")
        page.locator(".nmw button", has_text="Make it").first.click()
        made = _wait_new(project, before)
        check("Blocks > Make it makes a blocks mode", bool(made), str(made))
        check("the wizard closes", page.locator(".nmw").count() == 0)
        time.sleep(1.5)

        # 2. New mode > C, with a brief for an agent
        before = _modes(project)
        new_btn.click()
        time.sleep(0.6)
        check("New mode opens three tiles", page.locator(".nmw .nmw-tile").count() == 3)
        page.locator('.nmw .nmw-tile[data-kind="c"]').click()
        time.sleep(0.5)
        page.locator("#nmw-c-name").fill("WIZ AGENT")
        page.locator(".nmw-brief").fill("A hurry-up on the ramps")
        page.locator(".nmw button", has_text="Make it and copy for an agent").click()
        made = _wait_new(project, before)
        check("C > Make it and copy makes a C mode", bool(made), str(made))
        time.sleep(1.5)
        clip = page.evaluate("() => navigator.clipboard.readText()")
        c_file = made and os.path.join(project, "modes", made[0], made[0] + ".c")
        check("the C file is there", bool(c_file) and os.path.isfile(c_file), str(c_file))
        check("the agent's words name the file, the SDK guide and the brief",
              bool(c_file) and c_file in clip and "MODE_SDK.md" in clip and "A hurry-up on the ramps" in clip
              and "Godzilla" in clip, clip)
        print("--- clipboard ---\n" + clip + "\n---", flush=True)

        # 3. New mode > Form > Blank mode
        before = _modes(project)
        new_btn.click()
        time.sleep(0.6)
        page.locator('.nmw .nmw-tile[data-kind="form"]').click()
        time.sleep(0.5)
        page.locator(".nmw .nmw-ex", has_text="Blank mode").click()
        made = _wait_new(project, before)
        check("Form > Blank mode makes a form mode", bool(made), str(made))
        time.sleep(1.5)

        # 4. New mode > Form > KAIJU RUSH
        before = _modes(project)
        new_btn.click()
        time.sleep(0.6)
        page.locator('.nmw .nmw-tile[data-kind="form"]').click()
        time.sleep(0.5)
        page.locator(".nmw .nmw-ex", has_text="KAIJU RUSH").click()
        made = _wait_new(project, before)
        check("Form > KAIJU RUSH makes the example", bool(made), str(made))
        time.sleep(1)
        print("modes folder:", _modes(project), flush=True)

    try:
        S._shoot(url, flow)
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)
    print("PASS" if not fails else "FAIL: " + "; ".join(fails), flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
