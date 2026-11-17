"""PAD-1297: the mode family on a Stern Spike 3 card.

The census (docs/plans/spike3_modes.md, "The family on Spike 3") found one part that goes on
a Spike 3 card as files alone: the score feed (scorefeed.cfg beside the 64-bit runtime). The
Spike 3 Write now carries it, with the modes or by itself; every other part a project asks for
is left out with a sentence of its own. The emulator run (the game's scores posted to a stand-in
server) is the ticket's proof.
"""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import score_feed as SF
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from tests._ext4_fake import FakeExt4Reader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "http://192.168.1.50:8080/scores"


class _Reader(FakeExt4Reader):
    def read_symlink(self, node):
        return bytes(node["i_block"][:node["size"]]).decode()


def _tree(link="star_wars_elg/game"):
    return {"game": ("symlink", link),
            "star_wars_elg": {"game": b"\x7fELF\x02" + b"\0" * 64}}


def _logged():
    said = []
    return said, (lambda m, kind="info": said.append((kind, m)))


class _Result:
    def __init__(self, lines):
        self.replaced, self.new, self.lines, self.mode_names = [], [], lines, []


@pytest.fixture
def build(monkeypatch):
    """MW.plan and p2_payload stood in for: what the Spike 3 plan asks of them."""
    seen = {}
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(MW, "project_modes", lambda p: [])
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [])
    monkeypatch.setattr(MW, "gate", lambda dest_is_device: (True, ""))
    monkeypatch.setattr(MW, "card_refusal", lambda p, real_card=False: "")
    monkeypatch.setattr(S3M, "feed_wanted", lambda p, real_card=True: (URL, "PROF"))
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.setattr(MP, "project_profile", lambda p, probe=False: (None, None))

    def plan(project, hud, bank, elf, scratch, **kw):
        seen.update(kw, elf=elf, hud=hud, bank=bank)
        lines = ["score feed: " + SF.HOW % kw["score_feed"]] if kw.get("score_feed") else []
        return _Result(lines)

    def payload(result, out_dir, project=None, arch="arm"):
        seen["arch"] = arch
        return {"so": "/o/mode.so", "cfgs": [], "port": "/o/game.port", "assets": [],
                "extras": ["/o/scorefeed.cfg"], "bundle": ""}
    monkeypatch.setattr(MW, "plan", plan)
    monkeypatch.setattr(MW, "p2_payload", payload)
    return seen


def test_a_card_of_the_score_feed_alone_gets_the_runtime_and_its_file(build, tmp_path):
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path))
    assert mp is not None and mp.names == []
    assert build["modes_on"] is False and build["score_feed"] == URL
    assert build["score_feed_prof"] == "PROF" and build["arch"] == "a64"
    assert build["elf"].startswith(b"\x7fELF\x02")      # the card's own 64-bit program
    assert build["hud"] == b"" and build["bank"] == b""  # no mode: no scene is read or rewritten
    assert [(n, m) for n, _p, m in mp.files()] == [("mode.so", 0o755), ("scorefeed.cfg", 0o644),
                                                   ("game.port", 0o644)]
    assert mp.lines == ["Score feed: " + SF.HOW % URL]


def test_the_feed_goes_on_with_the_modes(build, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "project_modes", lambda p: [("m", type("S", (), {"name": "BLAST"})())])
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path))
    assert build["modes_on"] is True and build["score_feed"] == URL
    assert mp.names == ["BLAST"]


def test_the_feed_needs_no_mode_maker_preview(build, monkeypatch, tmp_path):
    # as on Spike 2 (_feed_for_build): the feed is a Play option, not a part of the mode maker
    monkeypatch.setattr(MW, "preview_on", lambda: False)
    monkeypatch.setattr(MW, "preview_left_out", lambda p: "")
    assert S3M.plan("proj", _Reader(_tree()), str(tmp_path)) is not None
    assert build["modes_on"] is False and build["score_feed"] == URL


def test_modes_left_out_still_leave_the_feed_on(build, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "project_modes", lambda p: [("m", type("S", (), {"name": "BLAST"})())])
    monkeypatch.setattr(MW, "card_refusal", lambda p, real_card=False: "no port for this game")
    said, log = _logged()
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path), log=log)
    assert mp is not None and mp.names == [] and build["modes_on"] is False
    assert any("mode(s) are left out of this build: no port for this game" in m for _k, m in said)


def test_no_feed_and_no_modes_is_no_plan(build, monkeypatch, tmp_path):
    monkeypatch.setattr(S3M, "feed_wanted", lambda p, real_card=True: ("", None))
    assert S3M.plan("proj", _Reader(_tree()), str(tmp_path)) is None
    assert "score_feed" not in build


def test_a_multiboot_card_takes_no_feed_and_says_so(build, tmp_path):
    said, log = _logged()
    assert S3M.plan("proj", _Reader(_tree(S3M.MULTIBOOT_LINK)), str(tmp_path), log=log) is None
    assert any(k == "warning" and m.startswith("Score feed: left out of this build: this is a "
                                                "multi-boot card") for k, m in said)


def test_the_write_logs_the_feed_under_its_own_name():
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "spike3_write.py"),
               encoding="utf-8").read()
    # PAD-1323: with the random clips' and the screen times' lines beside it
    assert 'line if line.startswith(("Score feed:", "Random clips:", "Screen times:", "Co-op play:", "Handicap",'
    assert '"Prolonged Competition:", "Records on the high scores:"))   # PAD-1327' in src
    assert 'else "Modes: %s" % line' in src


# ---- feed_wanted: the feed's own gate, quiet ------------------------------------------------
@pytest.fixture
def feed_project(tmp_path, monkeypatch):
    from pinball_decryptor.core import ext4_grow
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, ""))
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    monkeypatch.setattr(SF, "project_title", lambda p, probe=False: "PROF")
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "")
    SF.save(str(tmp_path), True, URL)
    return str(tmp_path)


def test_feed_wanted_is_the_projects_address(feed_project):
    assert S3M.feed_wanted(feed_project) == (URL, "PROF")


def test_feed_wanted_is_nothing_when_the_title_cannot_carry_it(feed_project, monkeypatch):
    monkeypatch.setattr(SF, "title_refusal", lambda prof: "no game end known")
    assert S3M.feed_wanted(feed_project) == ("", None)


def test_feed_wanted_is_nothing_when_the_card_cannot_take_files(feed_project, monkeypatch):
    from pinball_decryptor.core import ext4_grow
    monkeypatch.setattr(ext4_grow, "available", lambda: (False, "no debugfs"))
    assert S3M.feed_wanted(feed_project) == ("", None)
    assert S3M.feed_wanted(feed_project, real_card=False) == (URL, "PROF")   # Try it writes no card


def test_feed_wanted_is_nothing_when_switched_off(feed_project):
    SF.save(feed_project, False, URL)
    assert S3M.feed_wanted(feed_project) == ("", None)


def test_the_shipped_spike3_port_passes_the_feeds_gate():
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = MP.profiles().get("star_wars_elg_1_10_spike3")
    assert prof is not None and SF.title_refusal(prof) == ""


# ---- the rest of the family: one sentence each ----------------------------------------------
def _engine_block():
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "engine.py"),
               encoding="utf-8").read()
    i = src.index("from . import spike3_modes as _S3M")
    return src[i:src.index("variant_slots, variant_prof, sound_modes", i)]


def test_every_part_the_engine_leaves_out_has_its_reason():
    named = re.findall(r'\("([^"]+)", ', _engine_block())
    # PAD-1323: random clips and screen times go on now; PAD-1324: the music modes; PAD-1325: EDITION;
    # PAD-1326: co-op and the handicaps ; PAD-1327: Prolonged Competition - five parts are left out
    # PAD-1327 round 4: the records on the high scores too - four parts are left out
    # PAD-1328: the attract items' and inactivity pausing's own gates (_attract_for_build / _idle_for_build) say why -
    # two parts are left out with the family's sentence
    assert len(named) == 2 and set(named) == set(S3M.FAMILY_LEFT_OUT)
    assert "attract items" not in named and "inactivity pausing the timers" not in named
    assert "music modes" not in S3M.FAMILY_LEFT_OUT
    assert "handicaps" not in named and "handicaps" not in S3M.FAMILY_LEFT_OUT
    assert "co-op play" not in named and "co-op play" not in S3M.FAMILY_LEFT_OUT
    assert "editions" not in named and "editions" not in S3M.FAMILY_LEFT_OUT
    assert "Prolonged Competition" not in S3M.FAMILY_LEFT_OUT


def test_the_score_feed_is_not_left_out_any_more():
    assert "score feed" not in _engine_block() and "_feed_on" not in _engine_block()
    assert not any("feed" in k for k in S3M.FAMILY_LEFT_OUT)


def test_the_old_blanket_sentence_is_gone():
    assert "go on Spike 2 cards only" not in _engine_block()


def test_each_left_out_part_reads_as_its_own_sentence():
    lines = S3M.family_left_out_lines(["picture settings", "Prolonged Competition", "not a part", "co-op play"])
    assert lines == ["Picture settings: left out of this build: " + S3M.FAMILY_LEFT_OUT["picture settings"] + "."]
    for why in S3M.FAMILY_LEFT_OUT.values():
        assert "—" not in why and not why.endswith(".")


def test_the_feed_goes_on_with_code_modes(build, monkeypatch, tmp_path):
    # PAD-1295 put code modes on Spike 3 cards: they count as the card's modes, and the feed rides along
    from pinball_decryptor.plugins.stern import code_modes as CM
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [("c", type("C", (), {"name": "ZAP"})())])
    monkeypatch.setattr(CM, "profile_for", lambda p, code: None)
    said, log = _logged()
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path), log=log)
    assert mp is not None
    assert build["modes_on"] is True and build["code_ok"] is True and build["arch"] == "a64"
    assert build["score_feed"] == URL
    assert any("ZAP (code mode)" in m for _k, m in said)


def test_code_modes_left_out_still_leave_the_feed_on(build, monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [("c", type("C", (), {"name": "ZAP"})())])
    monkeypatch.setattr(MW, "card_refusal", lambda p, real_card=False: "no port for this game")
    said, log = _logged()
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path), log=log)
    assert mp is not None and mp.names == [] and build["modes_on"] is False and build["score_feed"] == URL
    assert any("1 mode(s) are left out of this build: no port for this game" in m for _k, m in said)
