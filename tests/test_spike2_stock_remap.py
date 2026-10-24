"""Item 160 "counts as": a stock rule takes another shot for one of its own - the desk side.

The port's ``rule`` lines and the spinner shots on both Godzilla ports, the project's rows
(``stock_remap.py``: load / save, the checks, the ``stock.cfg`` rendering and its reading back),
Write's payload and install command carrying ``stock.cfg``, ``mode_install.py``'s file list, and
the runtime's DECISION lifted verbatim from ``pad_mode_runtime.c`` and run on the host (skips
without a host C compiler; the run in the emulator is the proof of the wrap itself).
"""
import os
import pathlib
import re
import sys

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import stock_remap as SR

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
LE = str(SDK / "ports" / "godzilla_le-1.16.port")
PRO = str(SDK / "ports" / "godzilla_pro-1.15.port")


# ---- the ports -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("port,slot,vt12,vt4", [(LE, 42, 0x636d78, 0x640820), (PRO, 41, 0x6266d0, 0x630100)])
def test_both_godzilla_ports_name_the_rules_and_what_wraps_them(port, slot, vt12, vt4):
    rules = {rid: (label, vt) for rid, label, vt in SR.port_rules(port)}
    assert set(rules) == set(range(1, 27))           # PAD-699: every one of the game's own modes
    assert rules[12] == ("Battle vs Ebirah", vt12) and rules[4] == ("Tank Attack Multiball", vt4)
    assert SR.port_can(port)
    p = MP.read_port(port)
    assert p["value"]["stock_slot_shot"] == slot and p["value"]["stock_slot_active"] == 14
    assert p["value"]["stock_field"] == 0x18
    assert p["site"]["stock_rule_get"][1:] == (0xe351001a, 0xe92d4008)      # cmp r1,#26 ; push {r3,lr}
    assert p["data"]["stock_mode_manager"]


def test_the_spinners_middle_bits_are_named_shots_now():
    le = dict(SR.port_shots(LE))
    assert le["Left spinner"] == 0x200 and le["Top spinner"] == 0x2000 and le["Shield ramp spinner"] == 0x20000
    pro = dict(SR.port_shots(PRO))
    assert pro["Left spinner"] == 0x200 and pro["Top spinner"] == 0x2000 and pro["Right spinner"] == 0x20000
    assert SR.shot_mask(SR.port_shots(LE), "left SPINNER") == 0x200          # any case
    assert SR.shot_mask(SR.port_shots(LE), "0x100000") == 0x100000 == SR.shot_mask(SR.port_shots(LE), "Left ramp")
    assert SR.shot_mask(SR.port_shots(LE), "no such shot") == 0


def test_a_port_without_rule_lines_takes_no_row(tmp_path):
    bare = tmp_path / "bare.port"
    bare.write_text("game g\nversion 1\nshot 0x1 A\nshot 0x2 B\n", encoding="utf-8")
    assert SR.port_rules(str(bare)) == [] and not SR.port_can(str(bare))
    assert SR.check_row({"rule": 1, "from": "A", "to": "B"}, [], SR.port_shots(str(bare))).startswith("This game's port names none")


# ---- the rows and their checks -------------------------------------------------------------------------
def _rules():
    return SR.port_rules(LE)


def _shots():
    return SR.port_shots(LE)


def test_the_ebirah_row_is_fine_and_the_bad_ones_say_why():
    ok = {"rule": 12, "from": "Left ramp", "to": "Left spinner"}
    assert SR.check_row(ok, _rules(), _shots()) == ""
    assert "names no rule 99" in SR.check_row({"rule": 99, "from": "Left ramp", "to": "Left spinner"}, _rules(), _shots())
    assert "Pick one of the game's own rules" in SR.check_row({"rule": "x", "from": "Left ramp", "to": "Left spinner"}, _rules(), _shots())
    assert "not a shot" in SR.check_row({"rule": 12, "from": "Left rampp", "to": "Left spinner"}, _rules(), _shots())
    assert "not a shot" in SR.check_row({"rule": 12, "from": "Left ramp", "to": ""}, _rules(), _shots())
    # Building is two bits on the port's lamp line but ONE on its shot line; TOP SPINNER's lamp mask 0x1800 is not a shot
    assert "more than one bit" in SR.check_row({"rule": 12, "from": "Left ramp", "to": "0x1800"}, _rules(), _shots())
    assert "already carries" in SR.check_row({"rule": 12, "from": "0x300", "to": "0x200"}, _rules(), _shots())
    twice = {"rule": 12, "from": "left ramp", "to": "Top spinner"}
    assert "already counts as something for rule 12" in SR.check_row(twice, _rules(), _shots(), [ok])
    assert SR.check_row({"rule": 4, "from": "Left ramp", "to": "Top spinner"}, _rules(), _shots(), [ok]) == ""


def test_render_writes_the_ports_names_and_parse_reads_them_back():
    rows = [{"rule": 12, "from": "left ramp", "to": "LEFT SPINNER"}, {"rule": 4, "from": "0x100000", "to": "Godzilla target"}]
    text = SR.render(rows, _rules(), _shots(), port_name="godzilla_le-1.16.port")
    assert "# Battle vs Ebirah\ncounts_as 12 Left ramp -> Left spinner\n" in text
    assert "# Tank Attack Multiball\ncounts_as 4 Left ramp -> Godzilla target\n" in text
    # no row carries a trailing comment: a runtime before 2026-09-23 took it for part of the shot
    assert all("#" not in ln for ln in text.splitlines() if ln.startswith("counts_as"))
    assert text.endswith("\n") and "\r" not in text
    assert SR.parse(text) == [(12, "Left ramp", "Left spinner"), (4, "Left ramp", "Godzilla target")]
    assert SR.render([], _rules(), _shots()) == ""
    with pytest.raises(SR.StockRemapError, match="Row 1: .*names no rule 99"):
        SR.render([{"rule": 99, "from": "Left ramp", "to": "Left spinner"}], _rules(), _shots())
    assert SR.problems([{"rule": 12, "from": "Left ramp", "to": "Left spinner"}] * (SR.MAX_ROWS + 1), _rules(), _shots())


def test_load_and_save_round_trip_and_an_empty_table_is_no_file(tmp_path):
    proj = tmp_path / "proj"
    assert SR.load(str(proj)) == []
    rows = [{"rule": 12, "from": "Left ramp", "to": "Left spinner", "instead": False}]
    SR.save(str(proj), rows)
    assert os.path.isfile(SR.project_file(str(proj)))
    assert SR.load(str(proj)) == rows
    SR.save(str(proj), [])
    assert not os.path.isfile(SR.project_file(str(proj)))
    (proj / "modes").mkdir(exist_ok=True)
    (proj / "modes" / SR.PROJECT_FILE).write_text("{not json", encoding="utf-8")
    assert SR.load(str(proj)) == []


def test_write_file_renders_the_projects_rows_for_the_port(tmp_path):
    proj = tmp_path / "proj"
    assert SR.write_file(str(proj), LE, str(tmp_path / "stock.cfg")) == 0
    assert not (tmp_path / "stock.cfg").exists()
    SR.save(str(proj), [{"rule": 12, "from": "Left ramp", "to": "Left spinner"}])
    assert SR.write_file(str(proj), LE, str(tmp_path / "stock.cfg")) == 1
    assert "counts_as 12 Left ramp -> Left spinner" in (tmp_path / "stock.cfg").read_text(encoding="utf-8")
    assert "Battle vs Ebirah takes Left ramp as Left spinner" in SR.describe(SR.load(str(proj)), _rules(), _shots())
    bare = tmp_path / "bare.port"
    bare.write_text("game g\nversion 1\nshot 0x1 A\n", encoding="utf-8")
    with pytest.raises(SR.StockRemapError, match="names none"):
        SR.write_file(str(proj), str(bare), str(tmp_path / "x.cfg"))


# ---- Write carries it -----------------------------------------------------------------------------------
class _Plan:
    def __init__(self, tmp_path, stock=True):
        self.object = ""
        self.mode_files = [("mode.cfg", str(tmp_path / "m.cfg"))]
        (tmp_path / "m.cfg").write_text("name X\n")
        self.port = LE
        self.asset_files = []
        self.stock_file = ""
        if stock:
            (tmp_path / "s.cfg").write_text("counts_as 12 Left ramp -> Left spinner\n")
            self.stock_file = str(tmp_path / "s.cfg")


class _Ex:
    def to_exec_path(self, p):
        return "/x/" + os.path.basename(p)


def test_the_p2_payload_and_the_install_command_carry_stock_cfg(tmp_path):
    pay = MW.p2_payload(_Plan(tmp_path), str(tmp_path / "p2"))
    assert [os.path.basename(x) for x in pay["extras"]] == [SR.FILE_NAME]
    assert open(pay["extras"][0]).read() == "counts_as 12 Left ramp -> Left spinner\n"
    cmd = MW.install_command(_Ex(), str(tmp_path / "card.raw"), pay, 1700000000)
    assert "--file /x/stock.cfg" in cmd and cmd.index("--file") < cmd.index("--port")
    pay = MW.p2_payload(_Plan(tmp_path, stock=False), str(tmp_path / "p2b"))
    assert pay["extras"] == [] and "--file" not in MW.install_command(_Ex(), "c", pay, 1)


def test_stock_plan_fills_the_plan_from_the_project(tmp_path):
    proj = tmp_path / "proj"
    plan = _Plan(tmp_path, stock=False)
    plan.lines = []
    MW.stock_plan(str(proj), plan, str(tmp_path / "tree"))
    assert plan.stock_file == "" and plan.lines == []
    SR.save(str(proj), [{"rule": 12, "from": "Left ramp", "to": "Left spinner"}])
    MW.stock_plan(str(proj), plan, str(tmp_path / "tree"))
    assert plan.stock_file.endswith(os.path.join("padmode", "stock.cfg")) and os.path.isfile(plan.stock_file)
    assert plan.lines and "Battle vs Ebirah takes Left ramp as Left spinner" in plan.lines[-1]
    SR.save(str(proj), [{"rule": 99, "from": "Left ramp", "to": "Left spinner"}])
    with pytest.raises(MW.ModeWriteError, match="names no rule 99"):
        MW.stock_plan(str(proj), _Plan(tmp_path, stock=False), str(tmp_path / "tree2"))


def test_the_change_scan_names_the_table_and_says_when_no_mode_carries_it(tmp_path):
    """A counts-as table rides with the modes' runtime, which Write installs only with a mode: the
    scan says so for a project of rows alone (a silent drop before), and names the table once a
    mode carries it (the same words as the Write log)."""
    import json
    proj = tmp_path / "gz"
    proj.mkdir()
    with open(proj / ".extract_source.json", "w", encoding="utf-8") as f:
        json.dump({"input_path": str(proj / "godzilla_le-1_16_0.raw"), "input_name": "godzilla_le-1_16_0.raw"}, f)
    assert MW.pending_lines(str(proj)) == []
    SR.save(str(proj), [{"rule": 12, "from": "Left ramp", "to": "Left spinner"}])
    lines = MW.pending_lines(str(proj))
    assert lines == [MW.COUNTS_AS_NEEDS_A_MODE % 1]
    assert "NOT written" in lines[0] and "at least one mode" in lines[0]
    _card, prof = MP.project_profile(str(proj))
    MP.new_mode(str(proj), "NEW MODE", MP.blank_spec(prof))
    lines = MW.pending_lines(str(proj))
    assert lines[-1] == "the game's own rules take another shot (stock.cfg): Battle vs Ebirah takes Left ramp as Left spinner"
    assert all("NOT written" not in ln for ln in lines)


def test_mode_install_lists_stock_cfg_as_a_file_it_places_and_removes():
    sys.path.insert(0, str(ROOT / "tools" / "spike2_emu"))
    try:
        import mode_install as MI
    finally:
        sys.path.pop(0)
    assert ("stock.cfg", 0o100644) in MI.EXTRA_FILES and ("stock.cfg", 0o100644) in MI.ALL_FILES
    src = (ROOT / "tools" / "spike2_emu" / "mode_install.py").read_text(encoding="utf-8")
    assert '"--file"' in src and "extras=a.file" in src
    for name in ("modes/tryit.sh", "modes/cardmodes.sh"):
        assert "stock.cfg" in (ROOT / "tools" / "spike2_emu" / name).read_text(encoding="utf-8"), name


# ---- the runtime: the port reader and the decision, lifted ---------------------------------------------
def test_the_runtime_reads_rule_lines_and_the_file_beside_the_modes():
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'str_eq(key, "rule")' in src and "static void rule_line(" in src
    assert '"/usr/local/padmode/stock.cfg"' in src and '"/dump/stock.cfg"' in src
    assert 'str_eq(key, "counts_as")' in src and 'str_eq(key, "light")' in src
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    for name in ("pm_stock_rule_hook", "pm_stock_counts_as", "PM_CAN_STOCK_RULES", "pm_stock_shot_fn"):
        assert name in hdr, name
    # the wrap goes in AFTER the modes' ticks, so a probe wrapping the same slot wraps first
    tick = src[src.index("static void on_tick(unsigned *r)"):]
    tick = tick[:tick.index("\n}\n")]
    assert tick.index("EACH_MODE(m) if (m->tick)") < tick.index("stock_tick();") < tick.index("lamps_tick();")
    assert MR.prebuilt_is_current(), MR.stale_reasons()


DECIDE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
struct stock_row { unsigned rule; uint64_t from, to; unsigned rgb, ms, on_ms; int pattern; int from_c; int instead; };
struct stock_table { unsigned n; struct stock_row row[16]; };
%s
int main(void)
{
    struct stock_table t = { 4, { { 12, 0x100000ull, 0x200ull, 0, 0, 0, 0, 0, 0 },
                                   { 4, 0xc00000ull, 0x2000000000ull, 0, 0, 0, 0, 0, 0 },
                                   { 14, 0x1000000000ull, 0x100000ull, 0, 0, 0, 0, 0, 1 },
                                   { 14, 0x400000ull, 0x200000ull, 0, 0, 0, 0, 0, 1 } } };
    const struct stock_row *hit;
    uint64_t shot;
    #define TRY(rule, in, field) do { shot = (in); int r = stock_decide(&t, rule, &shot, field, &hit); \
        printf("%%u 0x%%llx 0x%%llx -> %%d 0x%%llx %%d\n", (unsigned)(rule), (unsigned long long)(in), \
               (unsigned long long)(field), r, (unsigned long long)shot, hit ? (int)(hit - t.row) : -1); } while (0)
    TRY(12, 0x100000ull, 0x22200ull);        /* lit: the ramp becomes 0x200 */
    TRY(12, 0x100000ull, 0x22000ull);        /* 0x200 cleared: passes through, the row still named */
    TRY(12, 0x1ull, 0x22200ull);             /* the switch-hit dispatch: no row */
    TRY(12, 0x100001ull, 0x22200ull);        /* PAD-699: the 0x1 rides along: remapped, keeping it */
    TRY(12, 0x300000ull, 0x22200ull);        /* a shot's bit outside from: untouched */
    TRY(12, 0x200ull, 0x22200ull);           /* the spinner itself: no row */
    TRY(4, 0x100000ull, 0x22200ull);         /* another rule: no row for it */
    TRY(4, 0x400000ull, 0x2000000000ull);    /* one bit of a two-bit from, lit */
    TRY(4, 0xc00000ull, 0x2000000000ull);    /* both bits of from: still inside from */
    TRY(12, 0ull, 0x22200ull);               /* nothing */
    TRY(14, 0x1000000001ull, 0x300000ull);   /* PAD-699: the Big loop (with its 0x1) instead of the Left ramp */
    TRY(14, 0x100000ull, 0x300000ull);       /* the Left ramp itself: dropped while lit */
    TRY(14, 0x200000ull, 0x300000ull);       /* the Right ramp itself: dropped */
    TRY(14, 0x200000ull, 0x100000ull);       /* not lit: passes through */
    TRY(14, 0x1ull, 0x300000ull);            /* the switch-hit dispatch alone: never touched */
    TRY(14, 0x400000ull, 0x300000ull);       /* the Building instead of the Right ramp */
    return 0;
}
"""


def test_the_decision_replaces_never_ors_and_stops_once_the_target_clears(tmp_path):
    from tests.test_spike2_mode_roster import _host_run, _lift
    fn = _lift(RUNTIME.read_text(encoding="utf-8"), "static int stock_decide(")
    out = _host_run(tmp_path, DECIDE_HARNESS % fn)
    got = [line.split() for line in out.strip().splitlines()]
    assert got == [
        ["12", "0x100000", "0x22200", "->", "1", "0x200", "0"],
        ["12", "0x100000", "0x22000", "->", "0", "0x100000", "0"],
        ["12", "0x1", "0x22200", "->", "0", "0x1", "-1"],
        ["12", "0x100001", "0x22200", "->", "1", "0x201", "0"],
        ["12", "0x300000", "0x22200", "->", "0", "0x300000", "-1"],
        ["12", "0x200", "0x22200", "->", "0", "0x200", "-1"],
        ["4", "0x100000", "0x22200", "->", "0", "0x100000", "-1"],
        ["4", "0x400000", "0x2000000000", "->", "1", "0x2000000000", "1"],
        ["4", "0xc00000", "0x2000000000", "->", "1", "0x2000000000", "1"],
        ["12", "0x0", "0x22200", "->", "0", "0x0", "-1"],
        ["14", "0x1000000001", "0x300000", "->", "1", "0x100001", "2"],
        ["14", "0x100000", "0x300000", "->", "2", "0x100000", "2"],
        ["14", "0x200000", "0x300000", "->", "2", "0x200000", "3"],
        ["14", "0x200000", "0x100000", "->", "0", "0x200000", "-1"],
        ["14", "0x1", "0x300000", "->", "0", "0x1", "-1"],
        ["14", "0x400000", "0x300000", "->", "1", "0x200000", "3"],
    ]


def test_the_ports_rule_lines_fit_the_runtimes_table():
    src = RUNTIME.read_text(encoding="utf-8")
    cap = int(re.search(r"#define N_STOCK_RULES\s+(\d+)", src).group(1))
    for port in (LE, PRO):
        assert 0 < len(SR.port_rules(port)) <= cap


# ---- PAD-699: instead_of rows, every Godzilla mode named, the light moves with the shot -------------------
GZ_PORTS = [str(SDK / "ports" / n) for n in ("godzilla_le-1.16.port", "godzilla_pro-1.16.port", "godzilla_pro-1.15.port")]


@pytest.mark.parametrize("port", GZ_PORTS)
def test_every_godzilla_build_names_its_battles(port):
    rules = {rid: label for rid, label, _vt in SR.port_rules(port)}
    for rid, label in ((6, "Battle vs Megalon and Gigan Multiball"), (12, "Battle vs Ebirah"),
                       (13, "Battle vs Titanosaurus"), (14, "Battle vs Gigan"), (15, "Battle vs Megalon"),
                       (16, "Battle vs King Ghidorah"), (17, "Battle vs Ghidorah and Gigan")):
        assert rules.get(rid) == label, (port, rid)
    assert SR.port_can(port)
    vts = [vt for _r, _l, vt in SR.port_rules(port)]
    assert len(vts) == len(set(vts))


def test_the_ebirah_and_tank_vtables_did_not_move():
    le = {rid: vt for rid, _l, vt in SR.port_rules(LE)}
    pro = {rid: vt for rid, _l, vt in SR.port_rules(PRO)}
    assert (le[12], le[4], le[14]) == (0x636d78, 0x640820, 0x637ac0)
    assert (pro[12], pro[4]) == (0x6266d0, 0x630100)


def test_an_instead_row_is_kept_rendered_and_described(tmp_path):
    proj = str(tmp_path / "proj")
    rows = [{"rule": 14, "from": "Big loop", "to": "Left ramp", "instead": True},
            {"rule": 12, "from": "Left ramp", "to": "Left spinner"}]
    SR.save(proj, rows)
    raw = open(SR.project_file(proj), encoding="utf-8").read()
    assert '"instead": true' in raw and raw.count('"instead"') == 1      # a counts-as row stays as it was
    got = SR.load(proj)
    assert got[0]["instead"] is True and got[1]["instead"] is False
    rules, shots = SR.port_rules(LE), SR.port_shots(LE)
    text = SR.render(got, rules, shots)
    assert "# Battle vs Gigan\ninstead_of 14 Big loop -> Left ramp\n" in text
    assert "counts_as 12 Left ramp -> Left spinner\n" in text
    assert SR.parse(text, instead=True) == [(14, "Big loop", "Left ramp")]
    assert SR.parse(text) == [(12, "Left ramp", "Left spinner")]
    assert "Battle vs Gigan takes Big loop instead of Left ramp" in SR.describe(got, rules, shots)
    assert SR.verb(got[0]) == "instead of" and SR.keyword(got[1]) == "counts_as"


def test_an_old_shot_is_moved_once_per_rule():
    rules, shots = SR.port_rules(LE), SR.port_shots(LE)
    rows = [{"rule": 14, "from": "Big loop", "to": "Left ramp", "instead": True},
            {"rule": 14, "from": "Building", "to": "Left ramp", "instead": True}]
    assert SR.problems(rows, rules, shots) == ['Row 2: "Left ramp" is already moved for rule 14.']
    rows[1]["instead"] = False                                # both counting is fine
    assert SR.problems(rows, rules, shots) == []


def test_the_runtime_parses_instead_of_and_moves_the_light():
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'str_eq(key, "instead_of")' in src
    assert int(re.search(r"#define STOCK_ROWS\s+(\d+)", src).group(1)) == SR.MAX_ROWS
    assert int(re.search(r"#define N_STOCK_RULES\s+(\d+)", src).group(1)) >= 27
    for name in ("static int stock_game_level(", "static unsigned stock_game_rgb(", "static void stock_mirror_tick("):
        assert name in src, name
    tick = src[src.index("static void stock_tick(void)"):]
    tick = tick[:tick.index("\n}\n")]
    assert tick.index("stock_lamps_poll();") < tick.index("stock_mirror_tick();")
    w = src[src.index("static uint64_t stock_w_shot("):]
    w = w[:w.index("\n}\n")]
    assert "stock_remap_shot(x, &shot) == 2" in w and "return 0;" in w


def test_a_derived_port_gets_its_own_rule_lines_from_its_program():
    from pinball_decryptor.plugins.stern import game_mode_blocks as G, portgen
    assert portgen.generated("rule", "14 0x00637ac0 Battle vs Gigan")
    assert portgen.REVISION >= 6

    class M:
        def __init__(self, i, vt, obj, name):
            self.id, self.vtable, self.obj, self.name = i, vt, obj, name
    lines = G.stock_rule_lines([M(14, 0x637ab8, 0x7b5588, "Battle vs Gigan"), M(99, 0, 0, "no object")])
    assert lines[-1] == "rule 14  0x00637ac0 Battle vs Gigan" and len(lines) == 3


@pytest.mark.parametrize("name,slot", [("godzilla_le-1.16.port", 42), ("godzilla_pro-1.16.port", 41),
                                       ("godzilla_pro-1.15.port", 41)])
def test_each_godzilla_port_wraps_its_own_builds_shot_slot(name, slot):
    """PAD-699: Pro 1.16 carried Premium/LE's 42 / 45 (drafted from it); its own vtables have the shot handler at
    v[41] and the mask getter at v[44] (emulator: a wrap of v[42] saw no shot, of v[41] every shot)."""
    v = MP.read_port(str(SDK / "ports" / name))["value"]
    assert (v["stock_slot_shot"], v["stock_slot_mask"]) == (slot, slot + 3)


def test_a_derived_port_takes_the_shot_slot_from_its_own_program(monkeypatch):
    from pinball_decryptor.plugins.stern import game_mode_blocks as G, portgen
    monkeypatch.setattr(G, "stock_shot_slot", lambda elf, modes=None: 41)
    out = ["value stock_slot_shot   42", "value stock_slot_active 14", "value stock_slot_mask       45"]

    class T:
        b = b""
    portgen._stock_slots(out, T())
    assert out[0].split()[:3] == ["value", "stock_slot_shot", "41"] and out[1] == "value stock_slot_active 14"
    assert out[2].split()[:3] == ["value", "stock_slot_mask", "44"]
    monkeypatch.setattr(G, "stock_shot_slot", lambda elf, modes=None: None)
    keep = ["value stock_slot_shot   42"]
    portgen._stock_slots(keep, T())
    assert keep == ["value stock_slot_shot   42"]
