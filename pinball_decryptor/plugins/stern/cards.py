"""Which CARD an override set is prepared from (PAD-161), as a pure function the Emulate
tab and Try it share.

Moved here from ``gui/emulate_tab.py`` (feature/emulate-prepare, 2026-09-22) so that
:func:`.mode_write.build_tryit_set` can prepare a Try it set the way the Emulate tab's own
"apply my edits" path does - from the card the extract measured, run over the card picked -
without importing a Tk module from a plugin. The functions are the tab's, verbatim; the tab
imports them back from here.
"""
from __future__ import annotations

import os


def _title_label(names):
    """``godzilla_le-1_16_0`` out of a card's ``.sidx`` names (see
    ``engine.card_title_index``): the versioned one, else the first."""
    stems = [n[:-len(".sidx")] for n in names]
    return next((s for s in stems if "-" in s), stems[0] if stems else "?")


def override_base_card(card_path, assets_dir, title_index):
    """``(base, note)`` - the card image the override set is prepared FROM,
    and a sentence for the log about that choice (``""`` when there is none).

    THE CARD THE PROJECT WAS EXTRACTED FROM, when the card picked to run is
    another copy of the same game version (PAD-161).  Every offset in an
    extract - where each scene picture sits, which strings are the stock
    ones - was measured on that card.  A card PAD BUILT from the project
    already holds earlier edits, and a picture kept at its own size or a
    longer line of text moves everything after it in its scene, so edits
    prepared from the built card went where its scenes no longer have them:
    a newer picture overwrote the scene's structure and the game stopped at
    the Stern logo (v0.217.2), or every picture in that scene was skipped
    and the run refused (v0.217.3).  Prepared from the original, each file
    in the set is what a fresh build would put on the card, which is what it
    needs to be to run over the built one.

    *title_index* is ``engine.card_title_index`` (passed in, so this stays
    pure): a different title or version keeps the old behaviour - the set is
    prepared from the picked card - and says so, because bytes from one
    version bound over another are a broken title of their own.
    """
    from ...core.admin import resolve_mapped_drive
    from ...core.extract_source import _names_this_image, read_extract_source
    rec = read_extract_source(assets_dir)
    src = resolve_mapped_drive(str((rec or {}).get("input_path") or ""))
    if not src or (os.path.normcase(os.path.abspath(src))
                   == os.path.normcase(os.path.abspath(card_path))):
        return card_path, ""
    if not os.path.isfile(src):
        # Same name and size is the source card moved.  Only asked here:
        # every card PAD builds is the size of its original, so where the
        # original is still there, the title index decides instead.
        if _names_this_image(rec, card_path):
            return card_path, ""
        return card_path, (
            "your edits were extracted from %s, which is not there any more, "
            "so they are prepared from the card picked here. If PAD built "
            "that card, an edit it no longer holds where the extract found it "
            "is skipped (the log below names it)." % src)
    picked, source = title_index(card_path), title_index(src)
    if not picked or not source:
        return card_path, ""
    if picked != source:
        return card_path, (
            "the card picked here is %s, but your edits were extracted from "
            "%s (%s), so some of them may not land on it."
            % (_title_label(picked), _title_label(source), src))
    return src, (
        "your edits are prepared from %s, the card this project was extracted "
        "from, and run on top of the card picked here. Prepared from a card "
        "PAD already built, they would land where its scenes no longer have "
        "them." % src)
