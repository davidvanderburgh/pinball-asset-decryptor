"""The user guide stays readable and its links work (PAD-732).

A Pinside user asked for the guide pages to stay short, sectioned and accurate
after they had grown into walls of text one release note at a time. These
checks are the part of that a test can hold: no paragraph or bullet runs past a
few sentences, no page carries version history (that belongs in the release
notes), and every relative link and #anchor between the pages lands. Run
directly (`python tests/test_guide_docs.py`) it prints every offender.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "docs", "guide")

#: the pages a reader is sent to: the README's front page and its guide
PAGES = [os.path.join(ROOT, "README.md")] + sorted(
    os.path.join(GUIDE, n) for n in os.listdir(GUIDE) if n.endswith(".md"))
#: kept out of the length check only: its disclaimers are worded with care, and
#: shortening one could change what it says
LENGTH_EXEMPT = {"legal.md"}

#: a prose paragraph may run to this many sentences, a bullet or a table cell
#: to one fewer ("no paragraphs more than a few sentences")
MAX_PARAGRAPH_SENTENCES = 4
MAX_ITEM_SENTENCES = 3
#: and no block of either may be longer than this many lines on the page
MAX_BLOCK_LINES = 8

#: "From v0.219.2 ...", "Before v1.2", "(v0.183.0)": history, not how it works now
VERSION_HISTORY = re.compile(
    r"\b(?:[Ff]rom|[Bb]efore|[Uu]ntil|[Uu]p to|[Ss]ince|[Aa]fter|fixed)\s+v\d+\.\d+"
    r"|\(v\d+\.\d+\.\d+\)")

#: a sentence ends at . ! or ? followed by a space and a capital, an opening
#: mark or a digit; "e.g." and the like don't count
_SENTENCE_END = re.compile(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)[.!?]['\")\]*_]*\s+(?=[A-Z0-9*(\"'`_\[])")


def _strip_markup(text):
    text = re.sub(r"`[^`]*`", "x", text)                       # code spans
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)     # links, images
    return text


def sentences(text):
    """How many sentences *text* has; a bold lead-in ("**Add your images.**")
    is a label, not one of them."""
    text = re.sub(r"^\*\*[^*]+\*\*", "", _strip_markup(text).strip()).strip()
    if not text:
        return 0
    return len(_SENTENCE_END.findall(text)) + 1


def blocks(path):
    """(kind, first line number, [lines]) for each paragraph, bullet and table
    row on the page, outside code fences and HTML."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    out, cur, fence = [], None, False

    def close():
        nonlocal cur
        if cur:
            out.append(cur)
        cur = None

    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            close()
            fence = not fence
            continue
        if fence:
            continue
        if not s or s.startswith(("#", "<", "![", "---", ">")):
            close()
            continue
        if s.startswith("|"):
            close()
            if not re.fullmatch(r"\|[\s|:-]*\|?", s):
                for cell in s.strip("|").split("|"):
                    out.append(("cell", n, [cell]))
            continue
        if re.match(r"([-*+]|\d+\.)\s", s):
            close()
            cur = ("item", n, [re.sub(r"^([-*+]|\d+\.)\s+", "", s)])
            continue
        if cur is None:
            cur = ("para", n, [s])
        else:
            cur[2].append(s)
    close()
    return out


def length_problems(path):
    probs = []
    for kind, n, body in blocks(path):
        count = sentences(" ".join(body))
        cap = MAX_PARAGRAPH_SENTENCES if kind == "para" else MAX_ITEM_SENTENCES
        if count > cap:
            probs.append("%s:%d: %s of %d sentences (at most %d)"
                         % (os.path.relpath(path, ROOT), n, kind, count, cap))
        if len(body) > MAX_BLOCK_LINES:
            probs.append("%s:%d: %s of %d lines (at most %d)"
                         % (os.path.relpath(path, ROOT), n, kind, len(body), MAX_BLOCK_LINES))
    return probs


def history_problems(path):
    probs = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            m = VERSION_HISTORY.search(line)
            if m:
                probs.append("%s:%d: version history %r"
                             % (os.path.relpath(path, ROOT), n, m.group(0)))
    return probs


def slug(heading):
    """GitHub's anchor for a heading."""
    h = re.sub(r"`|\*\*|__", "", heading.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path):
    seen, out = {}, set()
    fence = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip().startswith("```"):
                fence = not fence
            m = None if fence else re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
            if m:
                s = slug(m.group(1))
                k = seen.get(s, 0)
                seen[s] = k + 1
                out.add(s if k == 0 else "%s-%d" % (s, k))
    return out


def link_problems(path):
    probs = []
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    here = os.path.dirname(path)
    targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'(?:href|src)="([^"]+)"', text)
    for t in targets:
        if re.match(r"[a-z]+:", t):                         # http:, mailto: ...
            continue
        file_part, _, frag = t.partition("#")
        dest = os.path.normpath(os.path.join(here, file_part)) if file_part else path
        where = os.path.relpath(path, ROOT)
        if not os.path.exists(dest):
            probs.append("%s: link to %s: no such file" % (where, t))
        elif frag and dest.endswith(".md") and frag not in anchors(dest):
            probs.append("%s: link to %s: no such heading" % (where, t))
    return probs


class GuideDocsTest(unittest.TestCase):
    def test_no_wall_of_text(self):
        probs = [p for page in PAGES if os.path.basename(page) not in LENGTH_EXEMPT
                 for p in length_problems(page)]
        self.assertEqual(probs, [], "\n" + "\n".join(probs))

    def test_no_version_history(self):
        probs = [p for page in PAGES for p in history_problems(page)]
        self.assertEqual(probs, [], "\n" + "\n".join(probs))

    def test_links_land(self):
        probs = [p for page in PAGES for p in link_problems(page)]
        self.assertEqual(probs, [], "\n" + "\n".join(probs))

    def test_the_checks_catch_what_they_are_for(self):
        self.assertEqual(sentences("One. Two, e.g. this. Three! Four?"), 4)
        self.assertEqual(sentences("**A label.** One. Two."), 2)
        self.assertEqual(sentences("Runs `a.b. C` here. Then (v1.2) more."), 2)
        self.assertTrue(VERSION_HISTORY.search("From v0.219.2 a clip"))
        self.assertTrue(VERSION_HISTORY.search("is fixed (v0.217.3)."))
        self.assertFalse(VERSION_HISTORY.search("Godzilla 1.16 and v1.22.0 LE"))
        self.assertEqual(slug("SD card size (Stern Spike 2)"), "sd-card-size-stern-spike-2")
        self.assertEqual(slug("The cabinet: Country, Power, Edition, Topper"),
                         "the-cabinet-country-power-edition-topper")


if __name__ == "__main__":
    found = []
    for page in PAGES:
        if os.path.basename(page) not in LENGTH_EXEMPT:
            found += length_problems(page)
        found += history_problems(page) + link_problems(page)
    print("\n".join(found) or "the guide pages pass")
    sys.exit(1 if found else 0)
