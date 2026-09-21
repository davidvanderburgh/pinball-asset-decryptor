"""PAD-176 — a working folder carries BOTH its baked-in mods and its own
replacements.

A modder's project folder is an extract of his last built card plus the round
of replacements assigned since.  The transfer only ever carried the second:
the baked ones are the folder's baseline, not edits, so the baked-mod
comparison was skipped whenever the folder had any replacements at all.  The
documented way out was to make a pristine extract of the old card, which needs
that card — his was on another machine, several editions of work deep.

So the transfer offers both passes: the baked mods first, then the folder's
own replacements on top (they win on any slot the two share, being the newer
round).  Declining either pass still runs the other.

What triggers the offer is field 3, the stock extract of the old version.  It
was first keyed on recognising the source card by the build record beside it,
which is absent whenever the card was renamed, moved, kept on another drive or
built by an older version: the modder this was written for filled every field
correctly and was never asked.  Field 3 has one use, so supplying it IS the
ask.
"""

from types import SimpleNamespace

import pytest

from pinball_decryptor import app as app_mod
from pinball_decryptor.core import extract_source


def _fake_app(stock_dir=None):
    """An App stand-in with just what _transfer_plan_ready touches."""
    me = SimpleNamespace(calls=[], logs=[], _transfer_old_stock=stock_dir)
    me.window = SimpleNamespace(
        append_log=lambda t, level="info": me.logs.append((level, t)))
    me._transfer_baked_mods = lambda src, tgt, then=None: me.calls.append(
        ("baked", src, tgt, then))
    me._confirm_apply_transfer = lambda *a, **k: me.calls.append(
        ("pending", a, k))
    return me


def _plan(n=68):
    return {"totals": {"transfer": n, "flagged": 0, "dropped": 0}}


@pytest.fixture
def _built(monkeypatch):
    """The old folder was extracted from a card this app built."""
    monkeypatch.setattr(extract_source, "built_card_source",
                        lambda d: "GZ Pro 1.16 Custom V1.91.raw")


def _answer(monkeypatch, yes):
    asked = []

    def _ask(title, body):
        asked.append((title, body))
        return yes
    monkeypatch.setattr(app_mod.messagebox, "askyesno", _ask)
    return asked


def test_both_passes_run_baked_first_then_the_folder_s_own(monkeypatch,
                                                           _built):
    me = _fake_app(stock_dir="stock")
    asked = _answer(monkeypatch, True)
    app_mod.App._transfer_plan_ready(me, "V1.92", "new", _plan())

    assert len(asked) == 1
    assert asked[0][0] == "Carry the baked-in mods too?"
    assert "GZ Pro 1.16 Custom V1.91.raw" in asked[0][1]
    assert "68 replacement(s)" in asked[0][1]
    assert "stock extract of the old version" in asked[0][1]

    # Pass 1 is the baked comparison, with pass 2 hanging off it.
    kind, src, tgt, then = me.calls[0]
    assert (kind, src, tgt) == ("baked", "V1.92", "new")
    assert then is not None
    assert len(me.calls) == 1, "the second pass must wait for the first"

    # Pass 2 is this folder's own replacements, said plainly.
    then()
    kind, args, kwargs = me.calls[1]
    assert kind == "pending"
    assert args == ("V1.92", "new", _plan())
    assert "on top of the baked-in mods" in kwargs["intro"]


def test_declining_carries_only_the_folder_s_own(monkeypatch, _built):
    """Answered, not ignored: no lecture about filling a field they filled."""
    me = _fake_app(stock_dir="stock")
    _answer(monkeypatch, False)
    app_mod.App._transfer_plan_ready(me, "V1.92", "new", _plan())

    assert [c[0] for c in me.calls] == ["pending"]
    assert me.calls[0][2]["intro"] is None


def test_without_a_stock_extract_it_cannot_offer_and_asks_for_one(monkeypatch,
                                                                  _built):
    """Field 3 is what makes the baked comparison possible, so with it empty
    the offer would be a lie; name it instead."""
    me = _fake_app(stock_dir=None)
    asked = _answer(monkeypatch, True)
    app_mod.App._transfer_plan_ready(me, "V1.92", "new", _plan())

    assert asked == [], "nothing to offer without a stock extract"
    intro = me.calls[0][2]["intro"]
    assert "NOT included" in intro
    assert "GZ Pro 1.16 Custom V1.91.raw" in intro
    assert "Stock extract of the OLD version" in intro
    assert [t for lvl, t in me.logs if lvl == "warning"]


def test_an_unrecognised_source_card_is_still_offered_both(monkeypatch):
    """The offer hangs on field 3, not on recognising the card.  A card that
    was renamed, moved, kept on another drive or built by an older version has
    no build record to find, and that is the case that reached a real user:
    every field right, no question asked."""
    monkeypatch.setattr(extract_source, "built_card_source", lambda d: None)
    me = _fake_app(stock_dir="stock")
    asked = _answer(monkeypatch, True)
    app_mod.App._transfer_plan_ready(me, "V1.92", "new", _plan())

    assert len(asked) == 1
    assert "the card it was extracted from" in asked[0][1]
    assert [c[0] for c in me.calls] == ["baked"]


def test_no_stock_extract_and_no_build_record_stays_silent(monkeypatch):
    """Without field 3 there is nothing to offer and nothing to warn about:
    the long-standing behaviour."""
    monkeypatch.setattr(extract_source, "built_card_source", lambda d: None)
    me = _fake_app(stock_dir=None)
    asked = _answer(monkeypatch, True)
    app_mod.App._transfer_plan_ready(me, "fresh", "new", _plan())

    assert asked == []
    assert me.calls[0][2]["intro"] is None
    assert me.logs == []


def test_a_folder_with_no_replacements_still_takes_the_baked_route(monkeypatch,
                                                                   _built):
    """The case the baked route was written for: nothing pending, so there is
    no second pass to offer and none is asked about."""
    me = _fake_app(stock_dir="stock")
    asked = _answer(monkeypatch, True)
    app_mod.App._transfer_plan_ready(
        me, "fresh V1.91", "new",
        {"totals": {"transfer": 0, "flagged": 0, "dropped": 0}})

    assert asked == []
    assert [c[0] for c in me.calls] == ["baked"]
    assert me.calls[0][3] is None


def test_a_first_pass_that_finds_nothing_still_runs_the_second(monkeypatch):
    """Every way a pass can end except a failed apply continues the chain —
    turning down (or empty-handed) pass one is not a reason to drop the round
    the user actually asked for."""
    me = _fake_app()
    ran = []
    monkeypatch.setattr(app_mod.messagebox, "showinfo", lambda *a: None)
    app_mod.App._confirm_apply_transfer(
        me, "src", "tgt", {"totals": {"transfer": 0, "flagged": 0}},
        then=lambda: ran.append(True))
    assert ran == [True]
