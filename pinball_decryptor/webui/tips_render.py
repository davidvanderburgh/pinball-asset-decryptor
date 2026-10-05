"""The "?" window's words as blocks the page draws (PAD-386: no more wall of text).

A tip's body (``webui/help_content.py``) is one of:

* words, in a light markdown: paragraphs split by a blank line, ``- `` bullets, ``1. ``
  steps, ``### `` a subheading, ``> `` a callout, ``| a | b |`` table rows (the
  ``|---|`` row under the head is skipped); inline ``**bold**``, ``*italic*``, ```code```
  and ``[words](#anchor)``, a jump inside the window.  Plain words draw as they always
  did: no tip written before this used any of it by accident;
* PAD-380's ``{"text", "table": {"head", "rows"}, "after"}``;
* a list of the above and of picture blocks:
  ``{"cards": [{"icon", "tone", "title", "text"}]}`` (a row of coloured cards),
  ``{"flow": [{"icon", "title", "text"}]}`` (steps joined by arrows),
  ``{"note": words, "kind": "tip" | "warn"}`` (a callout);
* a function returning any of these, read when the window renders.

:func:`render` turns any of them into a list of blocks, each a dict with ``t``:
``p`` / ``h`` (runs), ``ul`` / ``ol`` (items of runs), ``table`` (head of runs, rows of
cells ``{"r", "chip"}``), ``note`` (kind, blocks), ``cards`` and ``flow``.  A run is
``[kind, text]`` (kind ``t`` text, ``b`` bold, ``i`` italic, ``c`` code) or
``["a", text, anchor]``.  Never raises: a body it cannot read draws nothing.
"""

import re

# **bold**, `code`, [words](target), *italic* (a lone star with no space inside it)
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]*)\)"
                     r"|(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_BULLET = re.compile(r"^\s*[-*] +(.*)$")
_STEP = re.compile(r"^\s*\d+\. +(.*)$")
_HEAD = re.compile(r"^(#{1,6}) +(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# a table cell that is an answer: a chip, then the rest of its words
_CHIPS = (("yes", re.compile(r"^(✓|Yes\b\.?)\s*", re.I)),
          ("part", re.compile(r"^(not yet\b\.?)\s*", re.I)),
          ("no", re.compile(r"^(No\b\.?)\s*", re.I)))


def slug(words):
    """The anchor a heading gets, as GitHub makes them, so a markdown file's own
    ``[x](#heading)`` links land in the window too."""
    s = re.sub(r"[^\w\- ]", "", str(words).lower().strip())
    return s.replace(" ", "-")


def runs(text):
    """*text*'s inline marks as runs."""
    out, at = [], 0
    text = str(text or "")
    for m in _INLINE.finditer(text):
        if m.start() > at:
            out.append(["t", text[at:m.start()]])
        bold, code, words, target, italic = m.groups()
        if bold is not None:
            out.append(["b", bold])
        elif code is not None:
            out.append(["c", code])
        elif words is not None:
            # a jump inside the window; any other link is just its words (the window
            # never sends anyone out of the app)
            out.append(["a", words, target[1:]] if target.startswith("#") else ["t", words])
        else:
            out.append(["i", italic])
        at = m.end()
    if at < len(text):
        out.append(["t", text[at:]])
    return out


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _cell(text, first):
    text = str(text)
    if not first:
        for chip, pat in _CHIPS:
            m = pat.match(text)
            if m:
                label = m.group(1).rstrip(".")
                rest = re.sub(r"^[,;:]\s*", "", text[m.end():])     # "Yes, with ..." -> "with ..."
                return {"chip": chip, "label": "" if label == "✓" else label,
                        "r": runs(rest)}
    return {"chip": "", "label": "", "r": runs(text)}


def _table(head, rows):
    return {"t": "table", "head": [runs(h) for h in head],
            "rows": [[_cell(c, i == 0) for i, c in enumerate(r)] for r in rows]}


def words(text):
    """Blocks for one piece of light markdown."""
    blocks, para, lst, table, quote = [], [], None, None, None

    def flush():
        nonlocal para, lst, table, quote
        if para:
            blocks.append({"t": "p", "r": runs("\n".join(para))})
        if lst:
            blocks.append({"t": lst[0], "items": [runs(i) for i in lst[1]]})
        if table:
            head, rows = table[0], table[1:]
            blocks.append(_table(head, rows))
        if quote is not None:
            blocks.append({"t": "note", "kind": "tip", "b": words("\n".join(quote))})
        para, lst, table, quote = [], None, None, None

    for line in str(text or "").split("\n"):
        if line.startswith(">"):
            if quote is None:
                flush()
                quote = []
            quote.append(line[2:] if line.startswith("> ") else line[1:])
            continue
        if not line.strip():
            flush()
            continue
        h = _HEAD.match(line)
        if h:
            flush()
            blocks.append({"t": "h", "r": runs(h.group(2)), "id": slug(h.group(2))})
            continue
        if line.lstrip().startswith("|"):
            if table is None:
                flush()
                table = []
            if not _RULE.match(line):
                table.append(_cells(line))
            continue
        b, s = _BULLET.match(line), _STEP.match(line)
        if b or s:
            kind = "ul" if b else "ol"
            if lst is None or lst[0] != kind:
                flush()
                lst = (kind, [])
            lst[1].append((b or s).group(1))
            continue
        if lst is not None and line[:1].isspace():
            lst[1][-1] += " " + line.strip()          # a bullet's next line
            continue
        if lst is not None or table is not None or quote is not None:
            flush()
        para.append(line)
    flush()
    return blocks


def _picture(block):
    if "cards" in block:
        return {"t": "cards", "items": [
            {"icon": c.get("icon") or "info", "tone": c.get("tone") or "",
             "title": c.get("title") or "", "r": runs(c.get("text") or "")}
            for c in block["cards"]]}
    if "flow" in block:
        return {"t": "flow", "items": [
            {"icon": c.get("icon") or "", "title": c.get("title") or "",
             "r": runs(c.get("text") or "")} for c in block["flow"]]}
    if "note" in block:
        return {"t": "note", "kind": block.get("kind") or "tip",
                "b": render(block["note"])}
    if "table" in block or "text" in block:           # PAD-380's shape
        out = words(block.get("text") or "")
        t = block.get("table")
        if t:
            out.append(_table(t.get("head") or [], t.get("rows") or []))
        return out + words(block.get("after") or "")
    return []


def render(body):
    """Blocks for a tip's *body*, whatever its shape (module docstring)."""
    try:
        if callable(body):
            body = body()
        if isinstance(body, str):
            return words(body)
        if isinstance(body, dict):
            got = _picture(body)
            return got if isinstance(got, list) else [got]
        if isinstance(body, (list, tuple)):
            out = []
            for part in body:
                out += render(part)
            return out
    except Exception:                                   # noqa: BLE001
        pass
    return []


def md_part(path, heading):
    """The words under ``## heading`` in the markdown file at *path*, up to the next
    ``#`` or ``##`` heading ("" when the file or the heading is missing)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return ""
    out, inside = [], False
    for line in lines:
        h = _HEAD.match(line)
        if h and len(h.group(1)) <= 2:
            if inside:
                break
            inside = len(h.group(1)) == 2 and h.group(2) == heading
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def plain(blocks):
    """The words of *blocks* with no marks: what a test or a search reads."""
    out = []

    def r(rs):
        return "".join(x[1] for x in rs or [])

    for b in blocks or []:
        t = b.get("t")
        if t in ("p", "h"):
            out.append(r(b["r"]))
        elif t in ("ul", "ol"):
            out += [r(i) for i in b["items"]]
        elif t == "table":
            out.append(" | ".join(r(h) for h in b["head"]))
            out += [" | ".join(((c["label"] or ("✓" if c["chip"] == "yes" else "")) + " "
                                + r(c["r"])).strip() for c in row)
                    for row in b["rows"]]
        elif t == "note":
            out.append(plain(b["b"]))
        elif t in ("cards", "flow"):
            out += ["%s: %s" % (i["title"], r(i["r"])) for i in b["items"]]
    return "\n".join(out)
