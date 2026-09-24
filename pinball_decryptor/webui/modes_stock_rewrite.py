"""The Modes tab's "Rewrite in C" rows (item 161): one CODE row per rule of the game's own the
card's port names, saying whether its shot logic is the game's own or rewritten by a code mode
of the project, and an action that starts a rewrite from the SDK's template.

A mixin of the Modes tab service (``tabs/modes.py`` adds it to the class and calls
:meth:`refresh_stock_rewrite` from its refresh; nothing else there). The rewrite is an ordinary
code mode of the project (``modes/<slug>/<slug>.c``, :mod:`..plugins.stern.stock_rewrite`), so
it lists, opens, builds and writes as every code mode does.

State (``modes.rewrite``): ``on`` (the port names rules), ``msg``, ``rows``
(``[{"id", "label", "slug", "template", "status"}]``), ``sel`` (a rule id or None), ``note``.
"""

import os

from .rpc import rpc

REWRITE_TIP = ("The game's own rules (a battle, a multiball) are compiled into the game. A rewrite is a "
               "code mode of this project whose C runs INSTEAD of one rule's shot handler: what a shot "
               "does is yours (which shots, in what order, what they pay), while the rule's start, "
               "clock, screens and ending stay the game's own. It starts from the SDK's example for the "
               "rule, builds and writes like every code mode, and with the folder gone the rule plays as "
               "it always did.")

EMPTY = {"on": False, "msg": "", "rows": [], "sel": None, "note": ""}


class StockRewriteMixin:
    def __init__(self, window):
        super().__init__(window)
        self.set(rewrite=dict(EMPTY))

    def _rewrite_set(self, **kw):
        st = dict(self.get("rewrite") or {})
        st.update(kw)
        self.set(rewrite=st)

    def refresh_stock_rewrite(self):
        from ..plugins.stern import stock_remap as SR
        from ..plugins.stern import stock_rewrite as SW
        project = self.project()
        keep = (self.get("rewrite") or {}).get("sel")
        port, why = self._remap_port()             # item 160's: the card's port, or the reason
        if not port:
            self._rewrite_set(on=False, msg=why, rows=[], sel=None, note="")
            return
        if not SR.port_rules(port) or not SR.port_can(port):
            self._rewrite_set(on=False, msg="%s names none of the game's own rules, so none can be "
                                            "rewritten yet." % os.path.basename(port), rows=[], sel=None, note="")
            return
        rows = SW.rows(project, port)
        n = sum(1 for r in rows if r["slug"])
        msg = "%s: %d rule(s) of the game's own. %s" % (
            os.path.basename(port), len(rows),
            "%d rewritten by this project's code (Write builds it into the card's mode.so with the modes)." % n
            if n else "Every rule plays its own shot logic.")
        ids = [r["id"] for r in rows]
        self._rewrite_set(on=True, msg=msg, rows=rows, sel=keep if keep in ids else None, note="")

    @rpc
    def rewrite_refresh(self):
        self.refresh_stock_rewrite()
        return True

    @rpc
    def rewrite_select(self, rule_id):
        rows = (self.get("rewrite") or {}).get("rows") or []
        try:
            rule_id = int(rule_id)
        except (TypeError, ValueError):
            rule_id = None
        row = next((r for r in rows if r["id"] == rule_id), None)
        self._rewrite_set(sel=rule_id if row else None, note=row["status"] if row else "")
        return True

    @rpc
    def rewrite_new(self, rule_id=None):
        """Start a rewrite of the rule from the SDK's template: a new code mode of the project.
        Returns the note shown (empty = made)."""
        from ..plugins.stern import stock_remap as SR
        from ..plugins.stern import stock_rewrite as SW
        project = self.project()
        port, why = self._remap_port()
        if port and (not SR.port_rules(port) or not SR.port_can(port)):
            port, why = "", ("%s names none of the game's own rules, so none can be rewritten yet."
                             % os.path.basename(port))
        if not port:
            self._rewrite_set(note=why)
            return why
        if rule_id is None:
            rule_id = (self.get("rewrite") or {}).get("sel")
        try:
            rule_id = int(rule_id)
        except (TypeError, ValueError):
            self._rewrite_set(note="Pick one of the game's own rules.")
            return "Pick one of the game's own rules."
        try:
            slug, path = SW.new_rewrite(project, rule_id, port)
        except SW.StockRewriteError as e:
            self._rewrite_set(note=str(e))
            return str(e)
        self._say("rewrite: made modes/%s/%s.c from the SDK's template; it replaces the shots of rule %d. "
                  "Edit it, then Try it builds it in." % (slug, slug, rule_id))
        self._refresh_all()
        self._rewrite_set(sel=rule_id, note="Made modes/%s/%s.c. It is a code mode of this project now: open it "
                                            "from the list, Try it builds it in, Write puts it on the card." % (slug, slug))
        return ""
