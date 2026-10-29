"""PAD-814: a way in for new users.

Pinside asked for a "getting started" tutorial (swap one song) and a list of
common problems.  Both are pages under docs/guide, linked from the README,
and the ⚙ menu's Help cascade opens them (webui/tabs/shell_extras.py
GUIDE_PAGES), so a user who never saw the README still finds them.
"""

import json
import os
import re

import pytest

from pinball_decryptor.webui.tabs import shell_extras
from tests.webui_harness import web_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "docs", "guide")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _help(w):
    top = w.state("shell")["settings_items"]
    sub = next((it["submenu"] for it in top if it.get("label") == "Help"), None)
    assert sub is not None, "no Help cascade in the gear menu"
    return sub


def test_the_gear_menu_has_the_guides(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        sub = _help(w)
    assert [(it["id"], it["args"], it["label"]) for it in sub] == [
        ("open_guide", ["getting_started"], "Getting started: your first mod…"),
        ("open_guide", ["common_problems"], "Common problems…"),
        ("open_guide", ["using_the_app"], "The full user guide…")]


def test_each_entry_opens_its_page_on_github(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(_service_class(), "open_link_checked",
                        lambda self, url, what="": opened.append((url, what)))
    with web_app(tmp_path, mfr="stern") as w:
        for it in _help(w):
            assert w.call("ui.settings_action", it["id"], *it["args"])
    assert opened == [
        ("https://github.com/davidvanderburgh/pinball-asset-decryptor/blob/main/"
         "docs/guide/%s" % page, "the user guide")
        for page in ("getting-started.md", "common-problems.md", "using-the-app.md")]


def _service_class():
    """The class in shell_extras that carries open_link_checked."""
    return next(c for c in vars(shell_extras).values()
                if isinstance(c, type) and "open_link_checked" in vars(c))


def test_an_unknown_guide_opens_nothing(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(_service_class(), "open_link_checked",
                        lambda self, url, what="": opened.append(url))
    with web_app(tmp_path, mfr="stern") as w:
        assert not w.call("ui.settings_action", "open_guide", "nope")
    assert opened == []


@pytest.mark.parametrize("page", [p for _k, _l, p in shell_extras.GUIDE_PAGES])
def test_every_guide_page_is_in_the_repo(page):
    assert os.path.isfile(os.path.join(GUIDE, page)), page


def _anchors(path):
    """GitHub's heading anchors in a markdown file."""
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"#+\s+(.*)", line)
            if m:
                slug = re.sub(r"[^\w\- ]", "", m.group(1).strip().lower())
                out.add(slug.replace(" ", "-"))
    return out


@pytest.mark.parametrize("page", ["getting-started.md", "common-problems.md"])
def test_the_new_pages_links_all_land(page):
    path = os.path.join(GUIDE, page)
    with open(path, encoding="utf-8") as f:
        links = LINK.findall(f.read())
    assert links
    for link in links:
        if link.startswith("http"):
            continue
        target, _, anchor = link.partition("#")
        dest = os.path.normpath(os.path.join(GUIDE, target)) if target else path
        assert os.path.isfile(dest), link
        if anchor:
            assert anchor in _anchors(dest), link


def test_the_readme_links_both_pages():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        text = f.read()
    for page in ("getting-started.md", "common-problems.md"):
        assert "(docs/guide/%s)" % page in text, page


@pytest.mark.parametrize("code", ["de", "es", "fr"])
def test_the_menu_words_are_translated(code):
    with open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "i18n",
                           code + ".json"), encoding="utf-8") as f:
        cat = json.load(f)
    for word in ["Help"] + [l for _k, l, _p in shell_extras.GUIDE_PAGES]:
        assert cat.get(word), (code, word)
