"""PAD-1286: the Spike 3 proof pass on Star Wars ELG 1.10 - what the Modes tab offers on the Spike 3 card once the
emulator has seen it (Ball save, a mode in the place of the game's own, a mode on the game's modes completed), the
port lines s3port.py now carries for it (the game's mode books, each flag by its name in both programs' flag
tables), and the rig fix that let a ball save be proven at all (s3balls' trough direction: tests/test_spike3_balls.py).
docs/plans/spike3_modes.md "The proof pass on a Spike 3 port (PAD-1286)" is the recipe."""
import importlib.util
import os
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3" / "star_wars_elg-1.10.port"


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    return S


def _profile():
    from pinball_decryptor.plugins.stern import mode_project as mp
    return mp, mp.profile_from_port(str(PORT))


def _port_values():
    out = {}
    for line in PORT.read_text(encoding="utf-8").splitlines():
        t = line.split()
        if len(t) >= 3 and t[0] in ("value", "text"):
            out[(t[0], t[1])] = t[2] if t[0] == "value" else line.split(None, 2)[2].split("#")[0].strip()
    return out


# ---- the Modes tab -----------------------------------------------------------------------------------------------
def test_the_spike3_card_offers_ball_save_place_and_done():
    mp, pr = _profile()
    key = "star_wars_elg-1.10/spike3"
    assert key in mp.BALL_SAVE_PROVEN and key in mp.PLACE_PROVEN and key in mp.DONE_PROVEN
    cannot = dict(pr.cannot)
    for part in ("ball_save", "place", "done"):
        assert part not in cannot, cannot.get(part)
    assert [n for _i, n, _c in pr.places] == ["Inner Loop", "Orbits", "Ramps"]
    assert all(c for _i, _n, c in pr.places)                 # each counts as the game's own, through its flag
    assert (128, "Captive Multiball") in pr.done_modes and len(pr.done_modes) == 4


def test_spike2_proofs_still_do_not_carry_over():
    """PAD-1277's rule stands: a table holding the Spike 2 build does not offer the Spike 3 one."""
    mp, pr = _profile()
    assert "star_wars_elg-1.10" in mp.SPARE_IO_PROVEN          # the Spike 2 build's own proof ...
    assert pr.spare == ("in",)                                  # ... and PAD-1329's of the Spike 3 one: no spare output


# ---- the port ----------------------------------------------------------------------------------------------------
def test_the_port_carries_the_games_mode_books():
    v = _port_values()
    assert v[("value", "place_flag_completed_0")] == "69"          # FG_INNER_LOOP_MODE_COMPLETED
    assert v[("value", "place_flag_completed_1")] == "67"          # FG_ORBITS_MODE_COMPLETED
    assert v[("value", "place_flag_completed_2")] == "68"          # FG_RAMPS_MODE_COMPLETED
    assert v[("value", "done_flag_0")] == "66"                     # FG_CAPTIVE_MULTIBALL_COMPLETED
    assert v[("text", "done_name_0")] == "Captive Multiball"
    assert "# not carried (64-bit layout, measure it): value place_flag" not in PORT.read_text(encoding="utf-8")


# ---- s3port: the flag names, the books by name --------------------------------------------------------------------
class _Prog:
    """A program the size of its flag table: the names in one segment, the pointer table read through ptr (Spike 3's
    RELATIVE relocs, Spike 2's data words)."""

    def __init__(self, names, a64, base=0x1000):
        blob = b"\0"
        self.at = []
        for n in names:
            self.at.append(base + len(blob))
            blob += n.encode() + b"\0"
        self.b = blob
        self.a64 = a64
        self.segs = [(base, 0, len(blob), 4)]
        step = 8 if a64 else 4
        self.ptr = {0x9000 + step * i: va for i, va in enumerate(self.at)}

    def cstr(self, va):
        o = va - self.segs[0][0]
        e = self.b.find(b"\0", o)
        return self.b[o:e].decode()


NAMES = ["FG_INVALID"] + ["FG_X_%d" % i for i in range(1, 66)] + [
    "FG_CAPTIVE_MULTIBALL_COMPLETED", "FG_ORBITS_MODE_COMPLETED", "FG_RAMPS_MODE_COMPLETED",
    "FG_INNER_LOOP_MODE_COMPLETED"]


def test_flag_names_reads_both_pointer_widths():
    S = _s3port()
    for a64 in (True, False):
        names = S.flag_names(_Prog(NAMES, a64))
        assert names[0] == "FG_INVALID" and names[67] == "FG_ORBITS_MODE_COMPLETED" and len(names) == len(NAMES)
    assert S.flag_names(_Prog(["FG_INVALID", "FG_A"], True)) == []       # too short to be the table


def test_mode_books_renumbers_each_flag_by_its_name(monkeypatch):
    S = _s3port()
    ref, tgt = _Prog(NAMES, False), _Prog(NAMES[:66] + ["FG_NEW"] + NAMES[66:], True)   # one flag more before them
    rval = {"place_flag_completed_0": "69", "place_flag_completed_1": "67", "place_flag_completed_2": "68",
            "done_flag_0": "66", "done_flag_1": "5", "mode_flag_1": "86"}
    rtext = {"done_name_0": "Captive Multiball"}
    vals, text, why = S.mode_books(ref, rval, rtext, tgt, starts={0: (1, 86), 1: (2, 88)})
    assert vals == {"place_flag_completed_0": 70, "place_flag_completed_1": 68, "done_flag_0": 67}
    assert text == ["text %-20s %s" % ("done_name_0", "Captive Multiball")]
    assert any("place_flag_completed_2" in w and "no start" in w for w in why)
    # a flag the Spike 3 program does not have is left out, said why
    vals, _t, why = S.mode_books(ref, {"done_flag_0": "66"}, rtext, _Prog(NAMES[:66] + ["FG_OTHER"] * 4, True), {})
    assert vals == {} and any("not one of the Spike 3" in w for w in why)


# ---- the recipe's rig jobs ---------------------------------------------------------------------------------------
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"


def _cfg(name):
    out = {}
    for line in (PROOFS / "modes" / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            k, _, v = line.partition(" ")
            out.setdefault(k, []).append(v.strip())
    return out


def test_the_recipe_jobs_and_their_mode_files_are_there():
    for f in ("s3proof.sh", "play.sh", "build_probe.sh", "place_probe_mode.c"):
        assert (PROOFS / f).is_file(), f
    play = (PROOFS / "play.sh").read_text(encoding="utf-8")
    for proof in ("ballsave", "game", "mb", "coil", "stackmb"):
        # a case label, maybe shared with another proof (PAD-1289: `coil|mode)`)
        assert re.search(r"^(\w+\|)*%s(\|\w+)*\)$" % proof, play, re.M), proof
    assert _cfg("save.cfg")["ball_save"] == ["15"] and "ball_save" not in _cfg("savectl.cfg")
    assert _cfg("place.cfg")["in_place_of"] == ["1"] and "trigger" not in _cfg("place.cfg")
    assert _cfg("done.cfg")["starts_on"] == ["completed 1 1"]
    assert _cfg("mb.cfg")["multiball"] == ["3 10"] and _cfg("stackmb.cfg")["stack"] == ["no"]
    assert _cfg("coil.cfg")["coil_hold"][0] == "right_gate 2000"
    assert "pm_game_mode_start(1)" in (PROOFS / "place_probe_mode.c").read_text(encoding="utf-8")
    for sh in ("s3proof.sh", "play.sh", "build_probe.sh"):
        assert b"\r\n" not in (PROOFS / sh).read_bytes(), sh          # bash in WSL reads them
