"""The stock-rule probe's desk side (item 158): its Godzilla LE 1.16 config, the log reader and the
insert oracle's port reading. The probe itself (stock_probe.c) is proven in the emulator only."""
import importlib.util
import os
import struct

import pytest

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu", "modes", "sdk")
PORT = os.path.join(SDK, "ports", "godzilla_le-1.16.port")
CFG = os.path.join(SDK, "stock_probe.godzilla_le-1.16.cfg")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SDK, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg_lines():
    out = []
    with open(CFG, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].split()
            if line:
                out.append(line)
    return out


def test_config_names_what_the_probe_needs():
    keys = {line[0] for line in _cfg_lines()}
    assert {"game", "version", "get", "mgr", "slots", "field", "watch"} <= keys
    watches = {int(line[1]): line for line in _cfg_lines() if line[0] == "watch"}
    assert set(watches) == {4, 12}
    assert "vt" in watches[4] and "vt" in watches[12]
    slots = dict(zip(*[iter(next(line for line in _cfg_lines() if line[0] == "slots")[1:])] * 2))
    assert slots["start"] == "8" and slots["shot"] == "42" and slots["stop"] == "11"
    # every address the probe CALLS is guarded by its first two instruction words
    for line in _cfg_lines():
        if line[0] in ("get", "gamelit", "award"):
            assert len(line) == (5 if line[0] == "award" else 4), line


def test_config_matches_the_port():
    game = version = None
    with open(PORT, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if parts[:1] == ["game"]:
                game = parts[1]
            if parts[:1] == ["version"]:
                version = parts[1]
    cfg = {line[0]: line[1] for line in _cfg_lines() if line[0] in ("game", "version")}
    assert (cfg["game"], cfg["version"]) == (game, version)


def test_reader_names_bits_and_handler_entries(tmp_path, capsys):
    reader = _load("stock_probe_read")
    log = tmp_path / "mode.log"
    log.write_text(
        "   56000 [mode] SP ready on godzilla_le 1.16: 2 rule(s) watched, field +0x18\n"
        "   80000 [mode] SP MARK START 12\n"
        "   80200 [mode] SP START 12 battle_ebirah p1 lr 0xd000 field 0x0 -> 0x22200 lit 0x22200 active 1\n"
        "   81000 [mode] SP shot 0x100000 p1\n"
        "   81001 [mode] SP SHOT 12 battle_ebirah p1 shot 0x100000 x 1 lr 0x7eabc field 0x22200 -> 0x22200"
        " lit 0x22200 -> 0x22200 active 1 pw+0x8c 15\n"
        "   81100 [mode] SP AWARD caward_add val 250000 lr 0x85480 r0 0x1 r1 0x0 r2 0x3d090 r3 0x0 stk 0x0 p1\n"
        "   82000 [mode] SP STOP 12 battle_ebirah p1 reason 0 lr 0xd000\n"
        "   83000 [mode] SP AWARD caward_add val 10 lr 0x1 r0 0x1 r1 0x0 r2 0xa r3 0x0 stk 0x0 p1\n",
        encoding="utf-8")
    assert reader.main([str(log), "--port", PORT, "--names", "0x200=Left spinner b"]) == 0
    out = capsys.readouterr().out
    assert "==== START 12" in out
    assert "switch shot 0x100000 (Left ramp)" in out
    assert "HANDLER 12 battle_ebirah: shot 0x100000 (Left ramp) x 1 | field 0x22200 -> 0x22200" in out
    assert "Left spinner b" in out                      # --names wins over the port's lamp line
    assert "val 250000" in out and "val 10 " not in out  # awards only while a watched rule runs


def test_lamp_watch_reads_the_port_and_a_block(tmp_path):
    lw = _load("lamp_watch")
    lamps = {name: (mask, node, ch, w) for name, mask, node, ch, w in lw.port_lamps(PORT)}
    assert lamps["LEFT RAMP"] == (0x100000, 9, 48, 3)
    assert lamps["TOP SPINNER"] == (0x1800, 9, 67, 3)
    assert lamps["TANK 1"][1:] == (8, 55, 1)
    assert "TANK 6" in lw.default_names(lw.port_lamps(PORT))
    block = bytearray(8192)
    struct.pack_into("<I", block, 0, lw.MAGIC)
    block[lw.VAL_OFF + lw.IDX * 9 + 48] = 255
    (tmp_path / "padled").write_bytes(bytes(block))
    (tmp_path / "stop").write_text("")
    # a stop file already there: the logger writes its header and stops at once
    assert lw.main(["log", str(tmp_path / "padled"), PORT, str(tmp_path / "lamps.txt"), "--stop",
                    str(tmp_path / "stop"), "--names", "LEFT RAMP,TANK 1"]) == 0
    head = (tmp_path / "lamps.txt").read_text()
    assert "LEFT RAMP@9:48+3" in head and "TANK 1@8:55+1" in head
    (tmp_path / "log.txt").write_text("# x\n1000 FULL LEFT_RAMP=255,0,0 TANK_1=0\n1100 TANK_1=9\n1200 LEFT_RAMP=0,0,0\n")
    samples = lw.read_log(str(tmp_path / "log.txt"))
    assert samples[-1][1] == {"LEFT RAMP": (0, 0, 0), "TANK 1": (9,)}
    n, stats = lw.window_stats(samples, 1000, 1200)
    assert n == 3 and stats["LEFT RAMP"][0] == 2 and stats["TANK 1"][0] == 2


@pytest.mark.parametrize("name", ["stock_probe.c"])
def test_probe_source_is_ascii_and_documents_its_triggers(name):
    text = open(os.path.join(SDK, name), "rb").read()
    assert all(b < 128 for b in text)
    for trigger in (b"stockprobe.start", b"stockprobe.stop", b"stockprobe.mark", b"stockprobe.cfg"):
        assert trigger in text
