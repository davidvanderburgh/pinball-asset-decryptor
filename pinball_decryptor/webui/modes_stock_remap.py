"""The Modes tab's "counts as" table (item 160): one of the game's OWN rules takes another shot
for one of its own.

A mixin of the Modes tab service (``tabs/modes.py`` adds it to the class and calls
:meth:`refresh_stock_remap` from its refresh; nothing else there). The rows live in the
project (``modes/stock.json``, :mod:`..plugins.stern.stock_remap`); Write puts them on the
card as ``stock.cfg`` beside the mode files and Try it drops the same file in the rig. The
rules and the shots a row may name are the CARD'S port's (its ``rule`` and ``shot`` lines), so
the table is empty, with a sentence, for a project whose card has no port or whose port names
no rules.

State (``modes.remap``): ``on`` (rows can be added), ``msg``, ``rows`` (``[{"i", "rule",
"label", "from", "to", "problem"}]``), ``rules`` (``[{"id", "label"}]``), ``shots`` (names),
``sel`` (a row index or None), ``note``.
"""

import os

from .rpc import rpc

REMAP_TIP = ("A shot of your choosing counts as one of a rule's own while that rule runs: every "
             "Left ramp reaches the battle vs Ebirah as a left spin (200,000 and the count down "
             "by one) while its left spinner is still lit, and the LEFT RAMP insert blinks the "
             "battle's yellow. One ramp is one spin, so a ramp standing in for a spinner needs "
             "the spinner's count of hits (15 on Ebirah's left spinner). The table is saved with "
             "this project and put on the card by Write with the modes; with no rows the game's "
             "rules play as they always did.")


EMPTY = {"on": False, "msg": "", "rows": [], "rules": [], "shots": [], "sel": None, "note": ""}


class StockRemapMixin:
    def __init__(self, window):
        super().__init__(window)
        self.set(remap=dict(EMPTY))

    def _remap_set(self, **kw):
        st = dict(self.get("remap") or {})
        st.update(kw)
        self.set(remap=st)

    def _remap_port(self):
        """The card's port path, or "" (with the reason in ``msg``) when the project names no
        card the SDK has a port for."""
        from ..plugins.stern import mode_project as MP
        from ..plugins.stern import stock_modes as SM
        project = self.project()
        if not project:
            return "", "Open or extract a card project first (Extract tab) - the table is saved in it."
        pb = SM.project_build(project)
        if not pb:
            return "", "This project names no card, so the game's own rules are not known."
        prof = MP.profile_for_card(pb[0], pb[1])
        if prof is None or not prof.port:
            return "", ("There is no port for %s %s, so its rules cannot take another shot."
                        % (pb[0], pb[1]))
        return MP.port_path(prof), ""

    def refresh_stock_remap(self):
        from ..plugins.stern import stock_remap as SR
        project = self.project()
        keep = (self.get("remap") or {}).get("sel")
        port, why = self._remap_port()
        if not port:
            self._remap_set(on=False, msg=why, rows=[], rules=[], shots=[], sel=None, note="")
            return
        rules = SR.port_rules(port)
        if not rules or not SR.port_can(port):
            self._remap_set(on=False, msg="%s names none of the game's own rules, so none can take "
                                          "another shot yet." % os.path.basename(port),
                            rows=[], rules=[], shots=[], sel=None, note="")
            return
        shots = SR.port_shots(port)
        rows = SR.load(project)
        labels = {rid: label for rid, label, _v in rules}
        out = []
        for i, r in enumerate(rows):
            out.append({"i": i, "rule": int(r["rule"]), "label": labels.get(int(r["rule"]), "rule %s" % r["rule"]),
                        "from": r["from"], "to": r["to"],
                        "problem": SR.check_row(r, rules, shots, rows[:i])})
        n_bad = sum(1 for r in out if r["problem"])
        msg = "%s: %d rule(s) can take another shot. %s" % (
            os.path.basename(port), len(rules),
            "%d row(s) go on the card with the modes as stock.cfg." % len(rows) if rows
            else "No rows - the game's own rules play as they always did.")
        if n_bad:
            msg += " %d row(s) cannot be written (Write stops and says why)." % n_bad
        self._remap_set(on=True, msg=msg, rows=out,
                        rules=[{"id": rid, "label": label} for rid, label, _v in rules],
                        shots=[n for n, _m in shots], sel=keep if keep is not None and keep < len(out) else None,
                        note="")

    @rpc
    def remap_refresh(self):
        self.refresh_stock_remap()
        return True

    @rpc
    def remap_select(self, i):
        rows = (self.get("remap") or {}).get("rows") or []
        try:
            i = int(i)
        except (TypeError, ValueError):
            i = -1
        self._remap_set(sel=i if 0 <= i < len(rows) else None,
                        note=rows[i]["problem"] if 0 <= i < len(rows) and rows[i]["problem"] else "")
        return True

    @rpc
    def remap_add(self, rule, src, dst):
        """Add a row {rule, from shot, to shot}; returns the note shown (empty = added)."""
        from ..plugins.stern import stock_remap as SR
        project = self.project()
        port, why = self._remap_port()
        if not port:
            self._remap_set(note=why)
            return why
        try:
            row = {"rule": int(rule), "from": str(src or "").strip(), "to": str(dst or "").strip()}
        except (TypeError, ValueError):
            self._remap_set(note="Pick one of the game's own rules.")
            return "Pick one of the game's own rules."
        rows = SR.load(project)
        why = SR.check_row(row, SR.port_rules(port), SR.port_shots(port), rows)
        if why:
            self._remap_set(note=why)
            return why
        if len(rows) >= SR.MAX_ROWS:
            why = "The runtime keeps %d rows." % SR.MAX_ROWS
            self._remap_set(note=why)
            return why
        rows.append(row)
        SR.save(project, rows)
        self._say("counts as: %s takes %s as %s" % (row["rule"], row["from"], row["to"]))
        self.refresh_stock_remap()
        self._remap_set(sel=len(rows) - 1, note="Added. Write puts it on the card with the modes.")
        return ""

    @rpc
    def remap_delete(self, i=None):
        from ..plugins.stern import stock_remap as SR
        project = self.project()
        if not project:
            return False
        rows = SR.load(project)
        if i is None:
            i = (self.get("remap") or {}).get("sel")
        try:
            i = int(i)
        except (TypeError, ValueError):
            return False
        if not (0 <= i < len(rows)):
            return False
        gone = rows.pop(i)
        SR.save(project, rows)
        self._say("counts as: row removed (%s took %s as %s)" % (gone["rule"], gone["from"], gone["to"]))
        self.refresh_stock_remap()
        self._remap_set(sel=None, note="Removed." if rows else "No rows - the game's own rules play as they always did.")
        return True
