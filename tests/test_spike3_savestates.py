"""PAD-1147 - save states on Spike 3.

The rig half (s3run.sh's checkpointable run and --restore, s3save.sh,
s3restore.sh, s3state.sh) is proven on the emulator; these cover what the app
asks of it - the Emulate tab's slot table, Launch and load on a Spike 3 card,
the commands it builds - and the one shared layout the load's video resync
depends on (s3vid.h, s3vid.c and s3vidhost.py agreeing on the session word).
"""

import importlib.util
import os
import re
import sys

import pytest

from pinball_decryptor.webui import emulate_core, emulate_rig
from tests.test_webui_emulate import _Done, _lines, _svc, _wait
from tests.test_webui_emulate_spike3 import _pick, _s3_rig
from tests.webui_harness import web_app

NS = "emulate"
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "spike3_emu")


@pytest.fixture(autouse=True)
def rig_on(monkeypatch):
    monkeypatch.setattr(emulate_rig, "rig_available", lambda: True)


def _wsl(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("the WSL argv is Windows-only")
    monkeypatch.setattr(emulate_core, "_wsl_head",
                        lambda root=False: ["wsl.exe"] + (["-u", "root"] if root else []) + ["-e"])


def test_launch_from_a_save_state_adds_restore(monkeypatch):
    _wsl(monkeypatch)
    cmd = emulate_core.spike3_launch_cmd(r"D:\cards\x.raw", 3, 240, restore="pokemon_le/s2")
    assert cmd[-2:] == ["--restore", "pokemon_le/s2"]
    assert "--restore" not in emulate_core.spike3_launch_cmd(r"D:\cards\x.raw", 3, 240)


def test_load_and_slots_go_through_the_launcher_as_root(monkeypatch):
    _wsl(monkeypatch)
    load = emulate_core.spike3_load_cmd(3, "s2")
    assert load[:4] == ["wsl.exe", "-u", "root", "-e"]
    assert load[5].endswith("/spike3_emu/s3launch.sh")
    assert load[-3:] == ["--load", "3", "s2"]
    assert emulate_core.spike3_slots_cmd("delete", "pokemon_le/s2")[-3:] == \
        ["--slots", "delete", "pokemon_le/s2"]


_S3_SLOTS = (b"root|/var/lib/pad-s3/saves\n"
             b"slot|pokemon_le/s2|61000000|pokemon_le|ball one|1762900000\n"
             b"slot|fallout_le/s1|52000000|fallout_le||1762900000\n"
             b"total|113000000\nfree|900000000000\n")


def _spike3_with_slots(w, svc, monkeypatch, tmp_path, lines=()):
    from tests.test_webui_emulate import _Recorder
    card = tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"
    card.write_bytes(b"\0" * 512)
    answers = _s3_rig(monkeypatch)
    answers["--slots list"] = _Done(_S3_SLOTS)
    rec = _Recorder(answers=answers, lines=lines)
    monkeypatch.setattr(svc, "_run", rec.run)
    monkeypatch.setattr(svc, "_popen", rec.popen)
    _pick(w, svc, card)
    _wait(w, lambda: w.state(NS).get("slots"))
    return rec


def test_a_spike3_card_lists_the_spike3_rigs_save_states(tmp_path, monkeypatch):
    """The table reads the Spike 3 rig's slots, not Spike 2's, scoped to the
    card's title the way Spike 2's are."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _spike3_with_slots(w, svc, monkeypatch, tmp_path)
        rows = w.state(NS)["slots"]
        assert [r["iid"] for r in rows] == ["pokemon_le/s2"]
        assert rows[0]["name"] == "ball one"
        assert any(c[-2:] == ["--slots", "list"] for c in rec.calls)
        assert not any("slots.sh" in " ".join(c) for c in rec.calls)


def test_rename_and_delete_act_on_the_spike3_slots(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _spike3_with_slots(w, svc, monkeypatch, tmp_path)
        w.run(lambda: svc._slot_cmd(["label", "pokemon_le/s2", "boss fight"]))
        _wait(w, lambda: any("label" in c for c in rec.calls))
        cmd = next(c for c in rec.calls if "label" in c)
        assert cmd[-4:] == ["--slots", "label", "pokemon_le/s2", "boss fight"]


def test_launch_with_nothing_running_starts_a_run_from_the_slot(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _spike3_with_slots(w, svc, monkeypatch, tmp_path, lines=(
            "s3launch: unpacking save state pokemon_le/s2",
            "s3launch: starting slot 1 for 240 min"))
        w.call(NS + ".select_slot", "pokemon_le/s2")
        w.call(NS + ".slot_launch")
        _wait(w, lambda: any("--restore" in c for c in rec.calls))
        launch = next(c for c in rec.calls if "--restore" in c)
        assert launch[launch.index("--restore") + 1] == "pokemon_le/s2"
        _wait(w, lambda: svc._s3_restore is None)       # used once, by that start
        assert not any("loadgame.sh" in " ".join(c) for c in rec.calls)


def test_launch_into_a_running_spike3_run_loads_it_there(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _spike3_with_slots(w, svc, monkeypatch, tmp_path)
        rec.answers["--load"] = _Done(b"[loadgame] loading slot 's2' (pokemon_le)\n"
                                      b"[loadgame] loaded slot 's2'\n")
        w.run(lambda: (setattr(svc, "_proc", object()), setattr(svc, "_s3_slot", 2)))
        try:
            w.call(NS + ".select_slot", "pokemon_le/s2")
            w.call(NS + ".slot_launch")
            _wait(w, lambda: any("--load" in c for c in rec.calls))
            _wait(w, lambda: not svc._loading)
            load = next(c for c in rec.calls if "--load" in c)
            assert load[-3:] == ["--load", "2", "s2"]
            _wait(w, lambda: any("[loadgame] loaded slot 's2'" in ln for ln in _lines(w)))
            assert not any("--restore" in c for c in rec.calls)
        finally:
            w.run(lambda: (setattr(svc, "_proc", None), setattr(svc, "_s3_slot", None)))


def test_a_save_of_another_title_is_refused_before_anything_runs(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        rec = _spike3_with_slots(w, svc, monkeypatch, tmp_path)
        # the table hides other titles; a stale selection is refused anyway
        w.run(lambda: svc._slot_by_iid.update(
            {"fallout_le/s1": {"iid": "fallout_le/s1", "game": "fallout_le"}}))
        w.run(lambda: setattr(svc, "_slot_sel", "fallout_le/s1"))
        assert w.call(NS + ".slot_launch") is False
        assert not any("--restore" in c or "--load" in c for c in rec.calls)


def test_the_s3vid_session_word_is_where_both_sides_read_it():
    """s3vid.h's feed header is magic, version, host_alive, session: the
    guest (s3vid.c) re-opens its streams when the session moves, the host
    (s3vidhost.py) writes it at byte 12 and ends old decoders through each
    channel's `closed` word - the load's video resync."""
    hdr = open(os.path.join(HERE, "s3vid.h"), encoding="utf-8").read()
    feed = re.search(r"struct s3vid_feed \{(.*?)\};", hdr, re.S).group(1)
    names = [n.strip() for ws in re.findall(r"unsigned ([a-z_, ]+);", feed) for n in ws.split(",")]
    assert names[:4] == ["magic", "version", "host_alive", "session"]
    chan = re.search(r"struct s3vid_chan \{(.*?)unsigned pad\[", hdr, re.S).group(1)
    cnames = [n.strip() for ws in re.findall(r"unsigned ([a-z_, ]+);", chan) for n in ws.split(",")]
    spec = importlib.util.spec_from_file_location("s3vidhost_t", os.path.join(HERE, "s3vidhost.py"))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    assert cnames.index("closed") == h.CLOSED
    assert cnames.index("open_gen") == h.OPEN_GEN
    src = open(os.path.join(HERE, "s3vidhost.py"), encoding="utf-8").read()
    assert src.count('struct.pack_into("<I", self.f, 12,') == 1
    assert 'struct.pack_into("<I", m, 12,' in src
    c = open(os.path.join(HERE, "s3vid.c"), encoding="utf-8").read()
    assert "feed->session != st[c].session" in c


def test_new_session_closes_every_channel_and_moves_the_session(tmp_path):
    spec = importlib.util.spec_from_file_location("s3vidhost_t2", os.path.join(HERE, "s3vidhost.py"))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    import struct
    feed = tmp_path / "s3vid.feed"
    size = 16 + h.CH * h.CHAN_SZ
    buf = bytearray(size)
    struct.pack_into("<IIII", buf, 0, h.S3VID_MAGIC, h.S3VID_VERSION, 7, 1234)
    feed.write_bytes(bytes(buf))
    assert h.new_session(str(feed)) == 0
    out = feed.read_bytes()
    assert struct.unpack_from("<I", out, 12)[0] not in (0, 1234)
    for c in range(h.CH):
        assert struct.unpack_from("<I", out, 16 + c * h.CHAN_SZ + h.CLOSED * 4)[0] == 1
    other = tmp_path / "not_a_feed"
    other.write_bytes(bytes(size))
    assert h.new_session(str(other)) == 1
    assert other.read_bytes() == bytes(size)


@pytest.mark.parametrize("script", ["s3save.sh", "s3restore.sh", "s3state.sh", "s3run.sh", "s3launch.sh"])
def test_the_save_state_scripts_are_lf_only(script):
    """WSL's bash reads these: a CRLF line is a syntax error there."""
    data = open(os.path.join(HERE, script), "rb").read()
    assert b"\r\n" not in data
