"""PAD-1289: Pokemon LE 0.82's Spike 3 port, drafted by s3port.py from Star Wars ELG 1.10's proven Spike 3 port and
proven on the Spike 3 rig (tools/spike3_emu/proofs/s3proof.sh TITLE=pokemon_le).

What the run found and this ticket fixed:
- the device table's names are UTF-8: Pokemon's "POKÉ BALL SPOT" read as Latin-1 has an unprintable \\x89, which ended
  s3port's walk of the table there and lost the 16 QR scanner switches before it - every switch line 16 low (the rig
  delivered Berry target left as 36, the draft said 20). s3nodes (the rig's own view of the table) dropped the record
  and the 123 behind it (the POKÉ BALL coil and ~120 playfield lights) the same way.
- Star Wars ELG's own mode-book flags (done_flag_0 66, place_flag_completed_2 68) turned up at lined-up instructions
  on Pokemon and were carried: they are ELG's game content, never another title's.
- a Spike 3 card keeps its modes in /games/pad/padmode inside the encrypted games volume, which the Modes tab's
  "modes from a card" (mode_from_card.read_padmode) never opened.

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder holding `star_wars_elg.game` (sha1
ceb8d70b...) and `pokemon_le.game` (sha1 36560010...), each a card's games/<game>/game.
"""
import hashlib
import importlib.util
import os
import pathlib
import re
import struct

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PORTS3 = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3"
ELG_PORT = PORTS3 / "star_wars_elg-1.10.port"
PK_PORT = PORTS3 / "pokemon_le-0.82.port"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"star_wars_elg": "ceb8d70b73a63698d06afddfe571c1bbab775c0a",
       "pokemon_le": "36560010984f742b74fb8e582f7465c76e852e3d"}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _s3port():
    return _load("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")


def _entries(text):
    out = {}
    for line in text.splitlines():
        t = line.split()
        if t and t[0] in ("site", "data", "value", "event", "switch"):
            out[(t[0], t[1])] = t[2]
    return out


#: the lines measured by hand on this program, not drafted from the reference: PAD-1326's co-op (portcoop: the
#: message table and its BALL line) and PAD-1327's start menu, champion framework and audit add
HAND = ("message_", "coop_", "comp_menu_", "challenge_", "game_scores", "audit_add")


def _own(entries):
    return {k: v for k, v in entries.items() if not k[1].startswith(HAND)}


# ---- the device table's names are UTF-8 ---------------------------------------------------------------------------

class _FakeElf:
    """a device table of 0x50-byte records in a flat image (address = offset): a name pointer at +0, the
    group / index / class word at +0x20"""

    def __init__(self, recs):
        names = b"\0" + b"\0".join(n.encode("utf-8") for n, _g, _i, _c in recs) + b"\0"
        base = 0x1000
        self.b = bytearray(base + 0x50 * (len(recs) + 2))
        self.b[:len(names)] = names
        self.ptr, at = {}, 1
        for k, (n, g, i, c) in enumerate(recs):
            a = base + 0x50 * (k + 1)
            self.ptr[a] = at
            struct.pack_into("<Q", self.b, a + 0x20, g | (i << 16) | (c << 32))
            at += len(n.encode("utf-8")) + 1
        self.b = bytes(self.b)
        self.segs = [(0, 0, len(self.b), 0)]

    def off(self, a):
        return a if 0 <= a < len(self.b) else None


def test_the_table_walk_reads_names_as_utf8_and_keeps_the_switches_before_an_accented_one():
    S = _s3port()
    recs = [("QR SCANNER STATUS READY", 2, 0, 1), ("QR SCANNER STATUS STRING", 2, 1, 1),
            ("POKÉ BALL SPOT", 8, 80, 3), ("LEFT OUTLANE", 7, 17, 1), ("TROUGH 1", 7, 37, 1)]
    got = S.device_records(_FakeElf(recs))
    assert [r[0] for r in got] == [n for n, *_ in recs]
    # the switch ids are the rank among the table's switches: the QR inputs come first
    assert S.switch_ids(_FakeElf(recs))["LEFT OUTLANE"] == 3


def test_the_rigs_table_reader_reads_names_as_utf8():
    N = _load("s3nodes", ROOT / "tools" / "spike3_emu" / "s3nodes.py")
    e = N.Elf.__new__(N.Elf)
    e.d = b"\0POK\xc3\x89 BALL SPOT\0TROUGH \xff\0"
    e.off = lambda va: va
    assert e.cstr(1) == "POKÉ BALL SPOT" and e.cstr(1).isprintable()
    assert e.cstr(17) =="TROUGH \xff"                 # not UTF-8: read as before


def test_the_reference_games_own_mode_book_flags_are_never_carried():
    S = _s3port()
    for name in ("done_flag_0", "place_flag_completed_0", "place_flag_completed_2"):
        assert S.GAME_VALUE.match(name), name
    for name in ("ball_end_event", "proc_exit_hooks", "event_flags"):
        assert not S.GAME_VALUE.match(name), name


# ---- the shipped port, proven on the rig ------------------------------------------------------------------------

def test_the_pokemon_port_carries_the_core_with_its_own_switch_ids_and_none_of_star_wars_content():
    text = PK_PORT.read_text(encoding="utf-8")
    e = _entries(text)
    for name in ("tick", "switch_hit", "switch_hit2", "hook_dispatch", "score_add", "agent_header", "agent_begin",
                 "multiball_serve"):
        assert ("site", name) in e, name
    for name in ("cur_player", "scores", "score_mult", "mode_mask"):
        assert ("data", name) in e, name
    assert e[("value", "ball_end_event")] == "0x34"
    sw = {int(t[1]): (int(t[2], 0), " ".join(t[3:])) for t in (l.split() for l in text.splitlines())
          if t and t[0] == "switch"}
    assert len(sw) == 45
    # the ids the rig delivered (switch_hit_log): Berry target left 36, Left orbit 48, Rear ramp made 50,
    # Captive ball-target 71 - with their mode-file bits
    assert sw[36] == (0x80, "Berry target left") and sw[48] == (0x40000, "Left orbit")
    assert sw[50] == (0x100000, "Rear ramp made") and sw[71] == (0x8000000000, "Captive ball-target")
    assert re.search(r"^text example_start_shot\s+Berry target left$", text, re.M)
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert not [l for l in body if l.split()[0] in ("lamp", "scene", "callout")]
    assert not [l for l in body if re.match(r"(site|value|text)\s+(show_(\d|name|kind|secs|proc)|block_|right_gate|"
                                            r"mode_flag|held_coils|place_flag|done_flag)", l)]
    assert "NOT RUN" not in text and "Emulator-proven 2026-11-15 (PAD-1289)" in text


def test_the_app_lists_and_takes_the_pokemon_port_for_spike3_only():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_runtime as MR, mode_write as MW
    assert MR.port_file("pokemon_le", "0_82_0", arch="a64") == str(PK_PORT)
    assert MR.port_arch(str(PK_PORT)) == "a64"
    prof = MP.profiles()["pokemon_le_0_82_spike3"]
    assert prof.port == "spike3/pokemon_le-0.82.port"
    assert "(Spike 3)" in prof.label
    assert not MW.port_unproven(str(PK_PORT))


def test_pokemon_spike3_is_in_the_proof_tables_the_rig_proved():
    from pinball_decryptor.plugins.stern import mode_project as MP
    key = "pokemon_le-0.82/spike3"
    for table in ("BALL_SAVE_PROVEN", "MULTIBALL_PROVEN"):
        assert key in getattr(MP, table), table
    # no Spike 2 Pokemon build carries over, and what was not run is not claimed
    for table in ("PLACE_PROVEN", "DONE_PROVEN", "STACK_FLAGS_PROVEN"):
        assert key not in getattr(MP, table), table
    cannot = dict(MP.profile_from_port(str(PK_PORT)).cannot)
    assert "ball_save" not in cannot and "multiball" not in cannot
    # every Spike 3 port's shots are switch lines, seen reaching a mode on the rig: no "not been seen" banner
    for k in ("pokemon_le-0.82/spike3", "star_wars_elg-1.10/spike3", "walking_dead_remastered_le-0.92/spike3"):
        assert k in MP.SWITCH_SHOTS_PROVEN, k
    for k in ("pokemon_le_0_82_spike3", "star_wars_elg_1_10_spike3", "walking_dead_remastered_le_0_92_spike3"):
        assert MP.profiles()[k].switch_shots_note == "", k


def test_the_proof_rig_knows_pokemon():
    env = (PROOFS / "titles" / "pokemon_le.env").read_text(encoding="utf-8")
    assert "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw" in env and "pokemon_le-0.82.port" in env
    assert re.search(r"^COINS=\$\{COINS:-4\}", env, re.M)           # not on free play
    for cfg in ("clock.cfg", "save.cfg", "savectl.cfg", "mb.cfg"):
        text = (PROOFS / "modes" / "pokemon_le" / cfg).read_text(encoding="utf-8")
        assert re.search(r"^trigger\s+0x80 3$", text, re.M) and re.search(r"^shots\s+0x8000140000$", text, re.M)
    s3proof = (PROOFS / "s3proof.sh").read_text(encoding="utf-8")
    assert 'titles/$TITLE.env' in s3proof and 'cp "$MODES/${CFG:-save.cfg}"' in s3proof
    play = (PROOFS / "play.sh").read_text(encoding="utf-8")
    assert "coil|mode)" in play and '$P coin "$SLOT" "$COINS"' in play


# ---- modes off a written Spike 3 card ----------------------------------------------------------------------------

def _fake_spike3_volume(monkeypatch, files, opened):
    from pinball_decryptor.plugins.stern import ext4, mode_write as MW, spike3, spike3_card

    class Vol:
        size = 1 << 20

        def close(self):
            opened.append("closed")

    class Reader:
        def __init__(self, f, off, size):
            assert isinstance(f, Vol)

        def _iter_dir(self, node):
            yield ".", 0, 2
            for k, name in enumerate(files):
                yield name, k + 10, 1

        def read_inode(self, n):
            return {"mode": ext4.S_IFREG | 0o644, "n": n}

        def read_file_bytes(self, inode):
            return list(files.values())[inode["n"] - 10]

    def lookup(reader, path):
        opened.append(path)
        return {"mode": ext4.S_IFDIR | 0o755} if files is not None and path == "pad/padmode" else None

    monkeypatch.setattr(spike3, "is_spike3_card", lambda p: True)
    monkeypatch.setattr(spike3_card, "open_games", lambda p: Vol())
    monkeypatch.setattr(ext4, "Ext4Reader", Reader)
    monkeypatch.setattr(MW, "lookup", lookup)


def test_modes_are_read_off_a_spike3_card_through_its_games_volume(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import mode_from_card as MFC
    opened = []
    files = {"mode.so": b"\x7fELF", "mode.cfg": b"name BERRY RUSH\n"}
    _fake_spike3_volume(monkeypatch, files, opened)
    assert MFC.read_padmode(str(tmp_path / "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw")) == files
    assert opened == ["pad/padmode", "closed"]


def test_a_stock_spike3_card_has_no_modes(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import mode_from_card as MFC
    opened = []
    _fake_spike3_volume(monkeypatch, None, opened)
    assert MFC.read_padmode(str(tmp_path / "x.raw")) == {}
    assert opened[-1] == "closed"


def test_a_spike3_card_no_key_opens_says_so(monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import mode_from_card as MFC, spike3, spike3_card

    def no_key(p):
        raise spike3_card.Spike3KeyError("No Spike 3 key for this card")
    monkeypatch.setattr(spike3, "is_spike3_card", lambda p: True)
    monkeypatch.setattr(spike3_card, "open_games", no_key)
    with pytest.raises(MFC.CardModesError, match="Spike 3 card its modes cannot be read"):
        MFC.read_padmode(str(tmp_path / "x.raw"))


# ---- on the real programs ---------------------------------------------------------------------------------------

def _prog(game):
    p = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(p):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    with open(p, "rb") as f:
        if hashlib.sha1(f.read()).hexdigest() != SHA[game]:
            pytest.skip("%s.game is another build" % game)
    return p


def test_redrafting_pokemon_gives_the_proven_port():
    S = _s3port()
    ref, tgt = S.Elf(_prog("star_wars_elg")), S.Elf(_prog("pokemon_le"))
    text, M, core, missing = S.draft_spike3(ref, str(ELG_PORT), tgt, "pokemon_le", "0.82")
    assert not core
    # the shipped port is what the rig proved: shots from the two switch_hit sites. A draft now also writes PAD-1322's
    # 64-bit switch_edge source (merged after this port was proven); Pokemon carries those lines once a run proves them
    # there, so the redraft is the shipped port plus exactly those and nothing else
    edge = {("site", "switch_edge"), ("value", "switch_record_reg"), ("value", "switch_id_at"),
            ("value", "switch_level_at"), ("value", "switch_desc_via"), ("value", "switch_flags_at"),
            ("value", "switch_polarity_at")}
    mine, shipped = _own(_entries(text)), _own(_entries(PK_PORT.read_text(encoding="utf-8")))
    assert set(mine) - set(shipped) == edge
    assert {k: v for k, v in mine.items() if k not in edge} == shipped


def test_pokemons_whole_device_table_is_walked():
    S = _s3port()
    recs = S.device_records(S.Elf(_prog("pokemon_le")))
    names = [r[0] for r in recs]
    assert "POKÉ BALL SPOT" in names and "QR SCANNER STATUS READY" in names
    assert S.switch_ids(S.Elf(_prog("pokemon_le")))["BERRY TARGET LEFT"] == 36
