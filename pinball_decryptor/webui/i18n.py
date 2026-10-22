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

#: the languages the app offers: (code, its own name for itself, the short
#: code the top bar's button shows).  The app is written in American English;
#: English (UK) is the same words spelled the British way (en-gb.json, made by
#: scripts/i18n_extract.py --british).
LANGUAGES = (("en", "English (US)", "EN-US"), ("en-gb", "English (UK)", "EN-GB"),
             ("es", "Español", "ES"), ("de", "Deutsch", "DE"), ("fr", "Français", "FR"))
CODES = tuple(lang[0] for lang in LANGUAGES)
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
_TWO_WORDS = re.compile(r"[A-Za-z]+\s+[A-Za-z]+")
_SHAPE = re.compile(r"[()\u2014\u00b7:;,]")
#: where one sentence ends and the next starts
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
#: a path is a path in every language
_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/[\w.-]+/)")


def normalize(text):
    return _WS.sub(" ", str(text)).strip()


def language(code):
    """*code* if the app offers it, else English."""
    code = str(code or "").strip().lower().replace("_", "-")
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
            if not template_ok(parts):
                continue
            lit = sum(len(p.strip()) for p in parts)
            rx = re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$",
                            re.S)
            entry = (lit, rx, value)
            if len(parts[0]) >= 2:
                self.buckets.setdefault("p" + parts[0][:2], []).append(entry)
            elif len(parts[-1]) >= 2:
                self.buckets.setdefault("s" + parts[-1][-2:], []).append(entry)
            else:
                self.general.append(entry)

    def __len__(self):
        return len(self.exact) + len(self.general) + sum(
            len(b) for b in self.buckets.values())

    def lookup(self, text, _depth=0):
        """The translation of *text*, or None."""
        s = normalize(text)
        if not s or _PATH.match(s):
            return None
        got = self.exact.get(s)
        if got is not None:
            return got
        # sentences the catalog knows each of, word for word, before any
        # template: a template's holes can span the sentence breaks ("{}'s own
        # {} from the {}" over "...the board's own program from the card, but
        # ..."), and a text made of known sentences is the more exact match
        if _depth == 0:
            parts = _SENTENCE.split(s)
            if len(parts) > 1:
                known = [self.exact.get(normalize(p)) if _LETTER.search(p) else p
                         for p in parts]
                if all(k is not None for k in known):
                    return " ".join(known)
        # the most specific template first, whichever bucket it came from
        cands = sorted(self.buckets.get("p" + s[:2], []) + self.buckets.get("s" + s[-2:], [])
                       + self.general, key=lambda e: -e[0])
        for _lit, rx, value in cands:
            m = rx.match(s)
            if m and not any(_GRAMMAR.match(g) for g in m.groups()):
                return self._fill(value, m.groups(), _depth)
        # sentences the app put together ("A." + " B."): each one the
        # catalog knows, or none of them
        if _depth == 0:
            parts = _SENTENCE.split(s)
            if len(parts) > 1:
                out = [p if not _LETTER.search(p) else self.lookup(p, 1) for p in parts]
                if all(o is not None for o in out):
                    return " ".join(out)
            # pieces set side by side ("6 games · .pkg"): each its own,
            # the ones the catalog does not know left as they are
            bits = s.split(" · ")
            if len(bits) > 1:
                out = [self.lookup(b, 1) for b in bits]
                if any(o is not None for o in out):
                    return " · ".join(o if o is not None else b for o, b in zip(out, bits))
        return None

    def _hole(self, g, depth):
        """A hole's words, translated when they are words the catalog has
        ("the Audio tab" by "The {} tab")."""
        w = g.strip()
        if depth > 1 or not _LETTER.search(w):
            return g
        got = self.lookup(w, depth + 1)
        if got is None and w[:1].islower():
            got = self.lookup(w[:1].upper() + w[1:], depth + 1)
            if got is not None:
                got = got[:1].lower() + got[1:]
        return g if got is None else g.replace(w, got)

    def _fill(self, value, groups, depth):
        groups = [self._hole(g, depth) for g in groups]
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


def template_ok(parts):
    """Whether a template (its literal *parts* around the holes) has words
    enough of its own to be trusted: "{} of {}" would turn a game called
    "House of Horrors" into "House de Horrors", and "{} mode{}" a folder
    called "heisei modes" into "heisei modos"."""
    if len(_LETTER.findall("".join(parts))) < MIN_LETTERS:
        return False
    if parts[0] == "" and parts[-1] == "":
        # open at both ends: it needs two words side by side of its own
        # open at both ends: two words side by side of its own, or a word
        # with some shape around it ("{} file(s) — {}")
        return any(_TWO_WORDS.search(p) or (_LETTER.search(p) and _SHAPE.search(p))
                   for p in parts)
    return True


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
