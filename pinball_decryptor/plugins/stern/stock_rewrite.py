"""A stock rule's shot logic REWRITTEN in C (item 161): the project side.

A rewrite is an ordinary CODE MODE of the project (``modes/<slug>/<slug>.c`` beside an
``assets.json``, :mod:`.code_modes`) whose C registers a handler for one of the game's own
rules (``PM_STOCK_HANDLER(<rule id>, fn)`` or a ``struct pm_stock_handler`` with
``.rule_id = <rule id>``, ``tools/spike2_emu/modes/sdk/pad_stock.h``). Write carries it exactly
as it carries every code mode: compiled with the mode-file interpreter into the card's
``mode.so`` (:func:`.mode_write.compile_command`), its ``<slug>.assets`` beside it. The
runtime attaches the record to the rule at boot; with the folder gone the game's rule plays as
it always did.

This module knows which rules of a card's port have a TEMPLATE (the SDK's examples: battle vs
Ebirah's ``ebirah_rewrite.c``), which of the project's code modes rewrite which rule, and makes a
new rewrite from a template (the Modes tab's "Rewrite in C..." action).
"""
from __future__ import annotations

import os
import re

from . import code_modes as CM
from . import mode_project as MP
from . import mode_runtime as MR

#: rule id -> the SDK example that rewrites it (tools/spike2_emu/modes/sdk/examples/)
TEMPLATES = {12: "ebirah_rewrite.c"}
_HANDLER_RE = re.compile(r"PM_STOCK_HANDLER\s*\(\s*(\d+)\s*,")
_RECORD_RE = re.compile(r"\.rule_id\s*=\s*(\d+)")
_NAME_RE = re.compile(r'#define\s+MODE_NAME\s+"([^"]*)"')


class StockRewriteError(ValueError):
    """A rewrite that cannot be made; the message is a sentence."""


def rule_of(path):
    """The id of the game's rule the C file at *path* registers a handler for, or None."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    m = _HANDLER_RE.search(text) or _RECORD_RE.search(text)
    return int(m.group(1)) if m else None


def rewrites(project):
    """``{rule id: slug}`` for the project's code modes that rewrite one of the game's rules
    (the first folder, in slug order, wins a rule two folders name)."""
    out = {}
    for slug in CM.code_slugs(project) if project else []:
        rule = rule_of(CM.source_path(project, slug))
        if rule is not None and rule not in out:
            out[rule] = slug
    return out


def template_path(rule_id):
    """The SDK example that rewrites *rule_id*, or None."""
    name = TEMPLATES.get(int(rule_id))
    if not name:
        return None
    path = os.path.join(MR.sdk_dir(), "examples", name)
    return path if os.path.isfile(path) else None


def template_name(rule_id):
    """The template's MODE_NAME, or "" when the rule has no template."""
    path = template_path(rule_id)
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            m = _NAME_RE.search(f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def rows(project, port):
    """One row per rule the port names: ``{"id", "label", "slug", "template", "status"}``.
    ``slug`` is the project's rewrite of that rule ("" when the game's own shot logic plays),
    ``template`` the name of the example a new rewrite would start from ("" when none)."""
    from . import stock_remap as SR
    have = rewrites(project) if project else {}
    out = []
    for rid, label, _vt in SR.port_rules(port):
        slug = have.get(rid, "")
        tmpl = TEMPLATES.get(rid, "") if template_path(rid) else ""
        if slug:
            status = "rewritten by modes/%s/%s.c" % (slug, slug)
        elif tmpl:
            status = "the game's own (a template is ready: %s)" % tmpl
        else:
            status = "the game's own (no template for this rule yet: write one against pad_stock.h)"
        out.append({"id": rid, "label": label, "slug": slug, "template": tmpl, "status": status})
    return out


def new_rewrite(project, rule_id, port):
    """Copy the rule's template into ``modes/<slug>/<slug>.c`` with a default ``assets.json``
    (the mode's name, nothing of its own), as the tab's New code mode does. Returns
    ``(slug, path)``. Refuses a rule the port does not name, a rule with no template, and a
    rule the project already rewrites."""
    from . import mode_tryit as MT
    from . import stock_remap as SR
    if not project or not os.path.isdir(project):
        raise StockRewriteError(MP.NO_PROJECT_HELP)
    rule_id = int(rule_id)
    labels = {rid: label for rid, label, _vt in SR.port_rules(port)}
    if rule_id not in labels:
        raise StockRewriteError("%s names no rule %d." % (os.path.basename(port), rule_id))
    have = rewrites(project)
    if rule_id in have:
        raise StockRewriteError("%s is already rewritten by modes/%s/%s.c; edit that, or delete it first."
                                % (labels[rule_id], have[rule_id], have[rule_id]))
    tpl = template_path(rule_id)
    if not tpl:
        raise StockRewriteError("There is no template for %s yet: write a code mode against pad_stock.h "
                                "(MODE_SDK.md, \"Rewriting a stock rule's shot logic\")." % labels[rule_id])
    with open(tpl, "r", encoding="utf-8") as f:
        text = f.read()
    base = os.path.splitext(os.path.basename(tpl))[0]
    slug = MT._free_slug(project, MP.slugify(base))
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder)
    path = os.path.join(folder, slug + ".c")
    if slug != base:
        text = text.replace('.name = "%s"' % base, '.name = "%s"' % slug)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    MT._write_default_assets(project, slug, MT._c_title(template_name(rule_id) or labels[rule_id], slug))
    return slug, path


def describe_suffix(project, slug, port=None):
    """`` - replaces the shots of Battle vs Ebirah`` for a code mode that rewrites a rule, else
    ``""``. With *port* the rule's label comes from it; without, the rule's id."""
    rule = rule_of(CM.source_path(project, slug)) if project else None
    if rule is None:
        return ""
    label = "rule %d" % rule
    if port:
        from . import stock_remap as SR
        for rid, lab, _vt in SR.port_rules(port):
            if rid == rule:
                label = lab
    return " - replaces the shots of %s (the game's own rule plays its shots through this code)" % label
