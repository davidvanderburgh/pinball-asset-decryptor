"""PAD-176 with Port + build: every ported card is built at its own
original's size (the SD card size on the Write tab is popped for the chain),
so while the chain runs card_size.size_fixed() says so, and a ported card
that runs out of room is told to build that card on its own for a bigger
size, never to set the control the port ignores."""

import os

from pinball_decryptor.plugins.stern import card_size as cs
from tests.test_webui_card_size import _bare_app


def test_the_port_chain_marks_its_builds_as_fixed_size(monkeypatch):
    from pinball_decryptor.core import mod_port
    a = _bare_app()
    a._settings = {"card_size": "16G"}
    monkeypatch.setenv(cs.ENV, "16G")
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)
    seen = []

    def run_ports(*args):
        seen.append((os.environ.get(cs.ENV), cs.size_fixed()))
        return []
    monkeypatch.setattr(mod_port, "run_ports", run_ports)
    a._run_port_chain("PROJECT", [])
    assert seen == [(None, True)]
    # the Write tab's own builds take a size again once the chain is over
    assert not cs.size_fixed() and os.environ.get(cs.ENV) == "16G"


def test_the_flag_goes_even_when_the_chain_fails(monkeypatch):
    from pinball_decryptor.core import mod_port
    a = _bare_app()
    a._settings = {"card_size": ""}
    monkeypatch.delenv(cs.FIXED_ENV, raising=False)

    def boom(*args):
        raise RuntimeError("a port failed")
    monkeypatch.setattr(mod_port, "run_ports", boom)
    try:
        a._run_port_chain("PROJECT", [])
    except RuntimeError:
        pass
    assert not cs.size_fixed()
