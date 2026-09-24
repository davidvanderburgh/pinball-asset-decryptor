"""The game's OWN rules take another shot for one of theirs: the "counts as" table (item 160).

WHAT IT IS. A rule the game shipped with (Godzilla's battle vs Ebirah, its tank attack
multiball) is compiled code whose SHOT HANDLER tests the raw shot mask for fixed bits: Ebirah
counts a spin only when the dispatch carries ``0x200``, its left spinner's middle bit, and does
nothing with a lit bit it has no test for (item 158, emulator-proven). So a shot the rule does
not know can only count by ARRIVING as the bit the rule tests. The Mode SDK runtime does that
from a small table beside the mode files, ``stock.cfg`` (MODE_SDK.md "Counts as"):

    counts_as 12 Left ramp -> Left spinner

While the battle runs and its left spinner is still lit, every Left ramp reaches Ebirah's
handler as ``0x200`` (one ramp = one spin: 200,000 and the count down by one; the ramp needs
the spinner's 15 hits unless the count word is lowered, item 159), the LEFT RAMP insert blinks
Ebirah's yellow, and once the count hits 0 the ramp passes through untouched. The table empty
= every rule plays stock.

THIS MODULE is the app's side: the rows a project keeps (``<project>/modes/stock.json``), the
rules and shots a card's PORT names (``rule`` lines; the spinners' middle bits are ``shot`` lines
since this item), the rendering of ``stock.cfg`` that Write puts on the card's system partition
with the modes and Try it drops in the rig, and the checks (a rule the port has, shots the port
names, a target that is ONE bit, no row twice). The Modes tab's table (``webui/modes_stock_remap``)
reads and writes the rows through here and nothing else.
"""
from __future__ import annotations

import json
import os
import re

#: the runtime's file, beside the mode files (a card: /usr/local/padmode; the rig: /dump)
FILE_NAME = "stock.cfg"
#: where a project keeps its rows, below the modes folder
PROJECT_FILE = "stock.json"
FORMAT = 1
#: what the runtime keeps (pad_mode_runtime.c STOCK_ROWS)
MAX_ROWS = 16
#: the stand-in's inserts when a row says nothing else: Ebirah's yellow, 300 ms on / 200 ms off
DEFAULT_LIGHT = ("ffff00", "blink", 500, 300)

_NUMBER = re.compile(r"^(0[xX][0-9a-fA-F]+|\d+)$")


class StockRemapError(ValueError):
    """A row that cannot be kept or written, with the reason in words."""


# ---- the port's rules and shots --------------------------------------------------------------------
def _port_number(tok):
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def port_rules(port_path):
    """``[(id, label, vtable)]`` of the ``rule`` lines of a port, in the port's order; ``[]``
    for a port without them (then no rule of that game can take another shot)."""
    out = []
    try:
        with open(port_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                s = raw.strip()
                if not s.startswith("rule "):
                    continue
                w = s[5:].split(None, 2)
                if len(w) < 2:
                    continue
                try:
                    rid, vt = _port_number(w[0]), _port_number(w[1])
                except ValueError:
                    continue
                label = (w[2] if len(w) > 2 else "").split("#", 1)[0].strip() or "rule %d" % rid
                out.append((rid, label, vt))
    except OSError:
        return []
    return out


def port_can(port_path):
    """True when the port names what the runtime needs to wrap a rule (``rule`` lines, the
    manager's get, the manager and the shot slot: pad_mode_runtime.c ``stock_arm``)."""
    if not port_rules(port_path):
        return False
    from .mode_project import read_port
    try:
        port = read_port(port_path)
    except OSError:
        return False
    return ("stock_rule_get" in port["site"] and bool(port["data"].get("stock_mode_manager"))
            and "stock_slot_shot" in port["value"])


def port_shots(port_path):
    """``[(name, mask)]`` of the port's ``shot`` lines."""
    from .mode_project import read_port
    try:
        return list(read_port(port_path)["shot"])
    except OSError:
        return []


def shot_mask(shots, name):
    """The mask of a shot given by name (the port's spelling, any case) or as a number; 0 when
    the port names no such shot."""
    s = (name or "").strip()
    if not s:
        return 0
    if _NUMBER.match(s):
        try:
            return int(s, 0)
        except ValueError:
            return 0
    for n, m in shots:
        if n.lower() == s.lower():
            return m
    return 0


def shot_name(shots, mask):
    """The port's name for a one-shot mask, or its hex."""
    for n, m in shots:
        if m == mask:
            return n
    return "0x%x" % mask


# ---- the project's rows ------------------------------------------------------------------------------
def project_file(project):
    return os.path.join(project, "modes", PROJECT_FILE)


def load(project):
    """The project's rows: ``[{"rule": int, "from": str, "to": str}]`` (shots by NAME, as the
    person picked them). A missing or unreadable file is no rows."""
    path = project_file(project) if project else ""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or int(data.get("format", 1) or 1) > FORMAT:
        return []
    rows = []
    for r in data.get("rows") or ():
        if not isinstance(r, dict):
            continue
        try:
            rows.append({"rule": int(r.get("rule")), "from": str(r.get("from") or ""),
                         "to": str(r.get("to") or "")})
        except (TypeError, ValueError):
            continue
    return rows


def save(project, rows):
    """Write the rows (an empty list removes the file: nothing to carry)."""
    path = project_file(project)
    if not rows:
        if os.path.isfile(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"format": FORMAT, "rows": [dict(rule=int(r["rule"]), **{"from": r["from"], "to": r["to"]})
                                               for r in rows]}, f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


# ---- the checks and the file -------------------------------------------------------------------------
def check_row(row, rules, shots, others=()):
    """Why *row* cannot be kept against a port's *rules* and *shots*, or "" when it can.
    *others* are the rows already there (a shot maps once per rule)."""
    ids = {rid for rid, _l, _v in rules}
    if not ids:
        return "This game's port names none of its own rules, so none can take another shot."
    try:
        rid = int(row.get("rule"))
    except (TypeError, ValueError):
        return "Pick one of the game's own rules."
    if rid not in ids:
        return "This game's port names no rule %d." % rid
    src, dst = shot_mask(shots, row.get("from")), shot_mask(shots, row.get("to"))
    if not src:
        return "\"%s\" is not a shot this game's port names." % (row.get("from") or "")
    if not dst:
        return "\"%s\" is not a shot this game's port names." % (row.get("to") or "")
    if dst & (dst - 1):
        return ("\"%s\" is more than one bit; a rule tests ONE bit, so the shot it counts as must "
                "be a single-bit shot." % row.get("to"))
    if src & dst:
        return "\"%s\" already carries \"%s\"." % (row.get("from"), row.get("to"))
    for o in others:
        if o is row:
            continue
        if int(o.get("rule", -1)) == rid and shot_mask(shots, o.get("from")) == src:
            return "\"%s\" already counts as something for rule %d." % (row.get("from"), rid)
    return ""


def problems(rows, rules, shots):
    """One sentence per row that cannot be written, in row order (empty = all fine)."""
    out = []
    for i, r in enumerate(rows):
        why = check_row(r, rules, shots, rows[:i])
        if why:
            out.append("Row %d: %s" % (i + 1, why))
    if len(rows) > MAX_ROWS:
        out.append("The runtime keeps %d rows; there are %d." % (MAX_ROWS, len(rows)))
    return out


def render(rows, rules, shots, port_name=""):
    """The text of ``stock.cfg`` for *rows* against a port (its shots by NAME as the port spells
    them, so the runtime's log names them). Rows that cannot be written raise
    :class:`StockRemapError` naming them; no rows is "" (nothing to carry)."""
    bad = problems(rows, rules, shots)
    if bad:
        raise StockRemapError(" ".join(bad))
    if not rows:
        return ""
    labels = {rid: label for rid, label, _v in rules}
    lines = ["# stock.cfg - the game's own rules take another shot for one of theirs (item 160)%s"
             % (", for %s" % port_name if port_name else ""),
             "# counts_as <rule id> <shot> -> <shot>   the runtime re-reads this file twice a second",
             "# light <rule id> <colour> [pattern] [ms] [on ms]   the stand-in's inserts (yellow blink 500 300 when absent)"]
    for r in rows:
        src, dst = shot_mask(shots, r["from"]), shot_mask(shots, r["to"])
        # the rule's label on a line of its own: a runtime older than 2026-09-23 read a trailing
        # comment as part of the shot after `->` and refused the row
        lines.append("# %s" % labels.get(int(r["rule"]), "rule %d" % int(r["rule"])))
        lines.append("counts_as %d %s -> %s" % (int(r["rule"]), shot_name(shots, src), shot_name(shots, dst)))
    return "\n".join(lines) + "\n"


def parse(text):
    """The ``counts_as`` rows of a ``stock.cfg`` text, as the runtime reads them:
    ``[(rule, from, to)]`` with the shots as written (a name or a number)."""
    out = []
    for raw in (text or "").splitlines():
        s = raw.split("#", 1)[0].strip()
        if not s.startswith("counts_as "):
            continue
        rest = s[len("counts_as "):].strip()
        rid, _, rest = rest.partition(" ")
        src, arrow, dst = rest.partition("->")
        if not arrow:
            continue
        try:
            out.append((int(rid, 0), src.strip(), dst.strip()))
        except ValueError:
            continue
    return out


def write_file(project, port_path, out_path):
    """Render the project's rows for *port_path* into *out_path* (Write's and Try it's stage).
    Returns the row count, 0 (and no file) when the project has none. Raises
    :class:`StockRemapError` for rows the port cannot take."""
    rows = load(project)
    if not rows:
        return 0
    rules, shots = port_rules(port_path), port_shots(port_path)
    if not rules:
        raise StockRemapError("the counts-as rows need a port that names the game's own rules; %s "
                              "names none" % os.path.basename(port_path))
    text = render(rows, rules, shots, port_name=os.path.basename(port_path))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return len(rows)


def describe(rows, rules, shots):
    """One sentence for the Write log and scan, or "" with no rows."""
    if not rows:
        return ""
    labels = {rid: label for rid, label, _v in rules}
    parts = []
    for r in rows:
        parts.append("%s takes %s as %s" % (labels.get(int(r["rule"]), "rule %s" % r["rule"]),
                                            r["from"], r["to"]))
    return "the game's own rules take another shot (stock.cfg): " + "; ".join(parts)
