"""The app's languages (PAD-458, docs/plans/app_languages.md).

The page is written in English and translated where it is SHOWN: the
browser side (static/js/core/i18n.js) looks every piece of text the page
draws up in a catalog, ``static/i18n/<lang>.json``, and puts the
translation in its place.  This module is the same lookup for the few
things Python lays out itself before the page sees them (the ? window's
words, whose bold and links would otherwise split a sentence into pieces).

A catalog maps English to the language:

* an exact key: ``"Scan": "Escanear"``;
* a TEMPLATE, a key with ``{}`` holes: ``"Saved {} files": "{} archivos
  guardados"``.  A hole matches any run of text, numbers included (the
  harvester, scripts/i18n_extract.py, writes every number as a hole).  The
  translation fills its holes in order, or by number (``{1} ... {0}``) when
  the language wants them the other way round.  A hole's words are looked
  up themselves too ("Tips — {}" with a tab name in it).

Whitespace is compared loosely (runs of blanks, a no-break space, a line
break inside a paragraph all count as one space); a text that does not
match anything is left in English.  The log is never translated: support
reports read the same in every language.
"""

import json
import os
import re
import threading

#: the languages the app offers: code -> its own name for itself
LANGUAGES = (("en", "English"), ("es", "Español"), ("de", "Deutsch"),
             ("fr", "Français"))
CODES = tuple(c for c, _ in LANGUAGES)
DEFAULT = "en"

CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "static", "i18n")

_WS = re.compile(r"[\s\u00a0]+")
_LETTER = re.compile(r"[A-Za-z]")
#: a template needs this many letters of its own: "{} of {}" would turn a
#: game called "House of Horrors" into "House de Horrors"
MIN_LETTERS = 4
#: an English grammar word or plural ending in a hole ("{} file{}" with "s",
#: "it {} not" with "does") would land in the translation as English: such a
#: match is no match, and the text stays English, whole
_GRAMMAR = re.compile(r"^(?:s|es|ies|y|is|are|was|were|does|do|did|has|have|"
                      r"it|its|they|them|their|this|these|that|those|one|"
                      r"isn't|aren't|doesn't|don't)$", re.I)
_HOLE = re.compile(r"\{(\d*)\}")


def normalize(text):
    return _WS.sub(" ", str(text)).strip()


def language(code):
    """*code* if the app offers it, else English."""
    code = str(code or "").strip().lower()
    return code if code in CODES else DEFAULT


class Catalog:
    """One language's lookup (module docstring)."""

    def __init__(self, mapping):
        self.exact = {}
        self.buckets = {}
        self.general = []
        for key, value in (mapping or {}).items():
            if not isinstance(value, str) or not value or key.startswith("_"):
                continue
            key = normalize(key)
            if "{}" not in key:
                self.exact[key] = value
                continue
            parts = key.split("{}")
            lit = sum(len(p.strip()) for p in parts)
            if len(_LETTER.findall("".join(parts))) < MIN_LETTERS:
                continue                  # "{} of {}" would match a game's name
            rx = re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$",
                            re.S)
            entry = (lit, rx, value)
            if len(parts[0]) >= 2:
                self.buckets.setdefault("p" + parts[0][:2], []).append(entry)
            elif len(parts[-1]) >= 2:
                self.buckets.setdefault("s" + parts[-1][-2:], []).append(entry)
            else:
                self.general.append(entry)
        for b in list(self.buckets.values()) + [self.general]:
            b.sort(key=lambda e: -e[0])

    def __len__(self):
        return len(self.exact) + len(self.general) + sum(
            len(b) for b in self.buckets.values())

    def lookup(self, text, _depth=0):
        """The translation of *text*, or None."""
        s = normalize(text)
        if not s:
            return None
        got = self.exact.get(s)
        if got is not None:
            return got
        cands = (self.buckets.get("p" + s[:2], []) + self.buckets.get("s" + s[-2:], [])
                 + self.general)
        for _lit, rx, value in cands:
            m = rx.match(s)
            if m and not any(_GRAMMAR.match(g) for g in m.groups()):
                return self._fill(value, m.groups(), _depth)
        return None

    def _fill(self, value, groups, depth):
        if depth == 0:
            groups = [self.exact.get(g.strip(), g) for g in groups]
        it = iter(range(len(groups)))

        def put(m):
            if m.group(1):
                i = int(m.group(1))
            else:
                i = next(it, None)
            return groups[i] if i is not None and i < len(groups) else ""
        return _HOLE.sub(put, value)

    def tr(self, text):
        """*text* translated, or *text* itself."""
        got = self.lookup(text)
        return text if got is None else got


_cache = {}
_lock = threading.Lock()


def catalog(code):
    """The Catalog for language *code* (None for English or a missing file)."""
    code = language(code)
    if code == DEFAULT:
        return None
    with _lock:
        if code not in _cache:
            try:
                with open(os.path.join(CATALOG_DIR, code + ".json"),
                          encoding="utf-8") as f:
                    _cache[code] = Catalog(json.load(f))
            except (OSError, ValueError):
                _cache[code] = None
        return _cache[code]


def translator(code):
    """A function text -> text for language *code* (identity for English)."""
    cat = catalog(code)
    if cat is None:
        return lambda t: t
    return cat.tr
