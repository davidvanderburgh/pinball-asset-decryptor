"""The framework's own core for a port: shots from the switch drain, the end of ball from the event bus,
the player up through the scores (portswitch), and one core rule in the runtime, the app and the drafter.

- The runtime's switch_edge hook (pad_mode_runtime.c on_switch_edge, edge_is_hit), lifted verbatim and
  compiled for the HOST over fake switch tables of both framework generations: a hit is the edge the
  game's handler runs on, only from the drain, only in a game, only through the game's mode mask.
- maps_has takes a range across CONTIGUOUS mappings (another object's mprotect splits the code), never
  across a hole or a mapping without the asked bits.
- The core rule: portgen.core_missing, mode_project.core_missing and core_of_port agree on every
  alternative (switch_edge / switch_hit with switch lines, ball_end_event with hook_dispatch, 32-bit).
- A derived port never carries another title's struct values (award screen, display, lamp slots,
  messages) or a copied end-of-ball bus id; the framework core fills what no reference placed.
- With the game programs present (PAD_PORT_ELFS, a folder of <game>-<version>.elf; skipped otherwise):
  the drain, the bus id and the switch names on builds of both generations.
Desk only: no card, no emulator.
"""
import os
import pathlib
import types

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import port_derive as D
from pinball_decryptor.plugins.stern import portgen as G
from pinball_decryptor.plugins.stern import portswitch as S
from tests.test_spike2_mode_roster import _host_run, _lift

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


# ---- the runtime's switch_edge hook ------------------------------------------------------------------
_EDGE = r"""
#include <stdio.h>
#include <string.h>
#define N_SWITCH_IDS 256
#define SYS_GETTID 224
static long fake_syscall(long n) { (void)n; return 7; }
#define syscall fake_syscall
static void say(const char *fmt, ...) { (void)fmt; }
static int in_game = 1;
int pm_in_game(void) { return in_game; }
static volatile unsigned switch_fired[N_SWITCH_IDS];
@EDGE@

/* generation B: 0x20-byte records (level byte at +0x18) pointing at 0x28-byte descriptors from +8 */
static unsigned char recs_b[16][0x20] __attribute__((aligned(8)));
static unsigned char descs_b[16][0x28] __attribute__((aligned(8)));
/* generation A: 0x2c-byte records that ARE the descriptors, level byte at +1 of the state from +0 */
static unsigned char recs_a[16][0x2c] __attribute__((aligned(8)));
static unsigned char state_a[16][4];
static unsigned base_b, base_a, count = 12;
static unsigned short mask;

static void put16(unsigned char *p, unsigned v) { p[0] = v & 255; p[1] = v >> 8; }
static void put32(unsigned char *p, unsigned long v) { unsigned u = (unsigned)v; memcpy(p, &u, 4); }

static void edge_at(unsigned id, unsigned level, unsigned lr)
{
    unsigned r[6] = { id, 0, 0, 0, 0, lr };
    if (edge.desc_via >= 0) recs_b[id][0x18] = (unsigned char)level;
    else state_a[id][1] = (unsigned char)(level ^ 1u);          /* A: the byte still holds the old level */
    on_switch_edge(r);
}

static void sw_b(unsigned id, unsigned flags, unsigned pol)
{
    put32(recs_b[id] + 8, (unsigned long)descs_b[id]);
    put16(descs_b[id] + 0x1a, flags);
    put16(descs_b[id] + 0x1c, pol);
}

static void sw_a(unsigned id, unsigned flags, unsigned pol)
{
    put32(recs_a[id], (unsigned long)state_a[id]);
    put16(recs_a[id] + 0x1e, flags);
    put16(recs_a[id] + 0x20, pol);
}

int main(int argc, char **argv)
{
    unsigned in = 0x1000 + 8, out = 0x3000;          /* a return address inside / outside the drain */
    unsigned i;
    int gen_a = !strcmp(argv[1], "A");
    base_b = (unsigned)(unsigned long)recs_b;
    base_a = (unsigned)(unsigned long)recs_a;
    edge.records = (unsigned)(unsigned long)(gen_a ? &base_a : &base_b);
    edge.count = (unsigned)(unsigned long)&count;
    edge.mode_mask = (unsigned)(unsigned long)&mask;
    edge.drain = 0x1000; edge.drain_end = 0x1180;
    edge.size = gen_a ? 0x2c : 0x20;
    edge.level_at = gen_a ? 1 : 0x18;
    edge.level_via = gen_a ? 0 : -1;
    edge.level_before = gen_a;
    edge.desc_via = gen_a ? -1 : 8;
    edge.flags_at = gen_a ? 0x1e : 0x1a;
    edge.polarity_at = gen_a ? 0x20 : 0x1c;
    for (i = 1; i < 16; i++) {
        unsigned flags = i == 5 ? 0x400 : i == 6 ? 0x800 : i == 7 ? 0xc00 : i == 9 ? 0x1400 : 0;
        unsigned pol = i == 7 ? 4 : 0;
        if (gen_a) sw_a(i, flags, pol); else sw_b(i, flags, pol);
    }
    edge_at(5, 0, in); edge_at(5, 1, in);            /* handler on the level-0 edge: one hit */
    edge_at(6, 0, in); edge_at(6, 1, in);            /* on the level-1 edge: one hit */
    edge_at(7, 0, in); edge_at(7, 1, in);            /* both edges, active high: the closing edge */
    edge_at(8, 1, in); edge_at(8, 0, in);            /* no handler, active low: the closing edge (0) */
    edge_at(8, 0, out);                              /* not from the drain (a switch reset): nothing */
    edge_at(13, 0, in);                              /* past the game's switch count: nothing */
    mask = 0x10;
    edge_at(9, 0, in);                               /* the mode mask shares no bit with 0x1400: no hit */
    mask = 0x1000;
    edge_at(9, 0, in);                               /* ... and now it does */
    mask = 0;
    in_game = 0;
    edge_at(5, 0, in);                               /* attract: no hit */
    for (i = 1; i < 16; i++) printf("%u ", switch_fired[i]);
    printf("\n%d%d%d%d%d\n", edge_is_hit(0, 0x400, 0, 0, 0), edge_is_hit(1, 0x400, 0, 0, 0),
           edge_is_hit(1, 0, 4, 1, 0), edge_is_hit(1, 0x800, 0, 1, 0x400), edge_is_hit(1, 0x800, 0, 1, 0x800));
    return 0;
}
"""


@pytest.mark.parametrize("gen", ["A", "B"])
def test_a_switch_edge_is_a_hit_on_the_edge_the_game_acts_on(tmp_path, gen):
    src = _src()
    block = _between(src, "static struct {\n    unsigned records, count, mode_mask, drain, drain_end;",
                     "/* The switch_edge site's tables")
    code = _EDGE.replace("@EDGE@", block)
    out = _host_run(tmp_path, code, flags=("-fno-pie", "-no-pie", "-Wno-unused-function", "-Wno-unused-variable"),
                    args=(gen,))
    fired, table = out.split("\n")[:2]
    #          1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
    assert fired.split() == ["0", "0", "0", "0", "1", "1", "1", "1", "1", "0", "0", "0", "0", "0", "0"], out
    assert table == "10101"


# ---- maps_has across contiguous mappings -------------------------------------------------------------
def test_a_range_may_cross_contiguous_mappings_never_a_hole(tmp_path):
    src = _src()
    maps = _between(src, "#define N_MAPS", "/* ---- rule 2:")
    code = r"""
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
@HEX@
@MAPS@
static void add(const char *s) { maps_line(s, s + strlen(s)); }
int main(void)
{
    add("00008000-00100000 r-xp 00000000 08:01 1234       /games/beatles/game");
    add("00100000-00101000 rwxp 000f8000 08:01 1234       /games/beatles/game");   /* a trampoline's page */
    add("00101000-00533000 r-xp 000f9000 08:01 1234       /games/beatles/game");
    add("0053b000-0055c000 rw-p 0052b000 08:01 1234       /games/beatles/game");
    add("0055c000-0055d000 rw-p 00000000 00:00 0");
    printf("%d %d %d %d %d %d %d\n",
           maps_has(0xffffc, 8, MAP_R | MAP_X | MAP_GAME),       /* across the split: yes */
           maps_has(0x100ffc, 8, MAP_R | MAP_X | MAP_GAME),      /* across the other split: yes */
           maps_has(0xffffc, 0x2000, MAP_R | MAP_X | MAP_GAME),  /* over all three: yes */
           maps_has(0x532ffc, 8, MAP_R),                         /* into the hole: no */
           maps_has(0x55bffc, 8, MAP_R),                         /* data into anonymous data: yes */
           maps_has(0x55bffc, 8, MAP_R | MAP_GAME),              /* ... but the second is not the game's */
           maps_has(0xfffffffffffffff0ul, 0x20, MAP_R));         /* wraps: no */
    return 0;
}
"""
    code = code.replace("@HEX@", _lift(src, "static int hexval(")).replace("@MAPS@", maps)
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function",))
    assert out.split() == ["1", "1", "1", "0", "1", "0", "0"]


# ---- one core rule -----------------------------------------------------------------------------------
_SITES = {
    "shots": [(), ("shot_dispatch",), ("switch_edge",), ("switch_hit",), ("switch_edge", "switch_hit"),
              ("shot_dispatch", "switch_edge")],
    "end": [(), ("ball_end",), ("hook_dispatch",), ("ball_end", "hook_dispatch")],
    "score": [(), ("score_add",), ("score_add32",), ("score_add", "score_add32")],
}
_DATA = [(), ("cur_player",), ("cur_player", "scores"), ("cur_player", "scores32"), ("scores32",)]


def _port(sites, data, event, switches):
    lines = ["game g", "version 1"] + ["site %s 0x%x 0 0" % (n, 0x100 + 8 * i) for i, n in enumerate(sites)]
    lines += ["data %s 0x%x" % (n, 0x9000 + 4 * i) for i, n in enumerate(data)]
    if event is not None:
        lines.append("value ball_end_event 0x%x" % event)
    lines += ["switch %d 0x%x Target %d" % (40 + k, 1 << k, k) for k in range(switches)]
    return lines


def test_the_drafter_and_the_app_share_the_runtimes_core_rule(tmp_path):
    """Every combination of the core's alternatives: portgen.core_missing (the drafter) and
    mode_project.core_missing (the app) refuse and accept the same ports, naming the same entries."""
    n = 0
    for shots in _SITES["shots"]:
        for end in _SITES["end"]:
            for score in _SITES["score"]:
                for data in _DATA:
                    for event in (None, 0x34, 0x30, 208):
                        for switches in (0, 2):
                            sites = ("tick",) + shots + end + score
                            p = tmp_path / "t.port"
                            p.write_text("\n".join(_port(sites, data, event, switches)) + "\n", encoding="utf-8")
                            port = MP.read_port(str(p))
                            values = {} if event is None else {"ball_end_event": event}
                            app = MP.core_missing(port)
                            drafter = G.core_missing(set(sites), set(data), values, switches)
                            assert (app == []) == (drafter == []), (sites, data, event, switches, app, drafter)
                            if any(s in sites for s in ("score_add", "score_add32")) or "scores32" not in data:
                                assert app == drafter, (sites, data, event, switches)
                            s, d = G.core_names(set(sites), values, switches)
                            assert (s, d) == MP._core_names(port)
                            n += 1
    assert n == 6 * 4 * 4 * 5 * 4 * 2


def test_the_core_names_are_the_runtimes():
    """Every name core_of_port can pick is one core_names picks, and the other way round."""
    import re
    body = _lift(_src(), "static void core_of_port(")
    runtime = set(re.findall(r'"([a-z_0-9]+)"', body)) - {"ball_end_event"}
    picked = set()
    for sites, values, sw in ((("shot_dispatch", "ball_end", "score_add"), {}, 0),
                              (("switch_edge", "hook_dispatch", "score_add32"), {"ball_end_event": 0x30}, 3),
                              (("switch_hit", "hook_dispatch", "score_add32"), {"ball_end_event": 0x34}, 3)):
        s, d = G.core_names(set(sites) | {"tick"}, values, sw)
        picked |= set(s) | set(d)
    assert picked == runtime


def test_the_switch_sites_are_hooked_sites():
    for name in ("switch_edge", "switch_hit", "switch_hit_2", "tick", "clip_play", "layered_waiter"):
        assert G.is_hooked_site(name), name
    for name in ("switch_drain", "find_node", "string_new"):
        assert not G.is_hooked_site(name), name


# ---- a derived port: the framework core, and no other title's struct values ----------------------------
class _Tgt:
    def word(self, va):
        return 0xE92D4010


def _ref(name, game, version):
    return types.SimpleNamespace(name=name, game=game, version=version, label="%s %s" % (game, version))


def _draft(ref, placed, extra=()):
    lines = ["game x", "version 1"]
    for (kind, name), v in placed.items():
        lines.append("site %-16s 0x%08x 0x1 0x2" % (name, v) if kind == "site" else "data %-22s 0x%08x" % (name, v))
    lines += list(extra)
    return dict(ref=ref, lines=lines, placed=dict(placed), how={k: "located (strict)" for k in placed},
                missing=[], seconds=0.1)


_CORE = {("site", "tick"): 0x100, ("site", "shot_dispatch"): 0x200, ("site", "ball_end"): 0x300,
         ("site", "score_add"): 0x400, ("data", "cur_player"): 0x9000, ("data", "scores"): 0x9100}
_VALUES = ("value event_next            0x84", "value award_message_at      0xa0", "value display_at 0x7c",
           "value lamp_slot_size 40", "value light_owner 3", "value ball_end_event 0x34",
           "value switch_hit_at 1", "shot 0x1 Left ramp")


def _no_framework(*_a):
    return dict(values=[], mapped=[], switch_lines=[], example="", notes=[])


@pytest.fixture(autouse=True)
def _no_own_shots(monkeypatch):
    """The fake program has no switch handlers to read shots from."""
    monkeypatch.setattr(D, "_own_shots", lambda tgt, family: ([], [], "none found", None))


def test_a_derived_port_never_carries_another_titles_struct_values(monkeypatch):
    monkeypatch.setattr(D, "framework_core", _no_framework)
    refs = [_ref("a-1.0", "godzilla_pro", "1.15")]
    a = _draft("a-1.0", {**_CORE, ("data", "message_table"): 0x9400, ("data", "message_count"): 0x9404,
                         ("data", "mode_mask"): 0x9408}, _VALUES)
    body, prov, missing, notes = D.merge({"a-1.0": a}, refs, _Tgt(), "batman", "1.13.0", "plain")
    text = "\n".join(body)
    assert missing == [] or missing == ["shots"]
    assert "value event_next" in text and "data mode_mask" in text          # the framework's own
    for gone in ("award_message_at", "display_at", "lamp_slot_size", "light_owner", "ball_end_event",
                 "switch_hit_at"):
        assert "value %s" % gone not in text, gone
    assert "\ndata message_table" not in text and "\ndata message_count" not in text
    assert "message_table" not in prov and any("Left off" in n and "the award screen" in n for n in notes)


def test_the_same_title_keeps_its_struct_values_but_never_a_copied_bus_id(monkeypatch):
    monkeypatch.setattr(D, "framework_core", _no_framework)
    refs = [_ref("a-1.0", "godzilla_pro", "1.15")]
    a = _draft("a-1.0", {**_CORE, ("data", "message_table"): 0x9400}, _VALUES)
    body, _prov, _missing, notes = D.merge({"a-1.0": a}, refs, _Tgt(), "godzilla_le", "1.16.0", "cmode")
    text = "\n".join(body)
    for kept in ("award_message_at", "display_at", "lamp_slot_size", "event_next"):
        assert "value %s" % kept in text, kept
    assert "data message_table" in text and "value ball_end_event" not in text
    assert not any("Left off" in n for n in notes)


def test_the_framework_fills_the_core_no_reference_placed(monkeypatch):
    def fw(tgt, lines, placed, provenance):
        lines["site"] += ["site hook_dispatch    0x00000500 0x1 0x2", "site switch_edge      0x00000600 0x1 0x2",
                          "site switch_drain     0x00000700 0x1 0x2"]
        lines["data"] += ["data cur_player             0x00009000"]
        for k, v in ((("site", "hook_dispatch"), 0x500), (("site", "switch_edge"), 0x600),
                     (("site", "switch_drain"), 0x700), (("data", "cur_player"), 0x9000)):
            placed[k] = v
        return dict(values=[("ball_end_event", 0x30), ("switch_record_size", 0x2c)],
                    mapped=[(46, 1, "(g)adget target"), (52, 2, "Penguin vuk")],
                    switch_lines=S.switch_lines([(46, 1, "(g)adget target"), (52, 2, "Penguin vuk")]),
                    example="(g)adget target", notes=[])

    monkeypatch.setattr(D, "framework_core", fw)
    refs = [_ref("a-1.0", "turtles_pro", "1.58")]
    a = _draft("a-1.0", {("site", "tick"): 0x100, ("site", "score_add"): 0x400, ("data", "scores"): 0x9100}, _VALUES)
    body, _prov, missing, _notes = D.merge({"a-1.0": a}, refs, _Tgt(), "batman", "1.13.0", "plain")
    text = "\n".join(body)
    assert missing == []
    assert "value ball_end_event        0x30" in text and "value ball_end_event 0x34" not in text
    assert "switch 46   0x1                (g)adget target" in text
    assert "text example_start_shot     (g)adget target" in text
    assert "\nshot 0x1 Left ramp" not in text                   # another title's shots never come across


# ---- portswitch without a program ---------------------------------------------------------------------
def test_only_playfield_switches_are_shots():
    sws = [dict(id=i, name=n, image=img, handler=1) for i, (n, img) in enumerate([
        ("DIP 1", "System/cab.png"), ("LEFT RAMP", "pf.png"), ("TROUGH 1", "pf.png"), ("SHOOTER LANE", "pf.png"),
        ("LEFT FLIPPER EOS", "pf.png"), ("CRANE POS. #2", "pf.png"), ("SPINNER", "pf.png"), ("TOPPER UP", "pf.png"),
        ("START BUTTON", "cab.png"), ("LEFT SLINGSHOT", "pf.png")], start=1)]
    assert S.shot_switches(sws) == [(2, "LEFT RAMP"), (7, "SPINNER"), (10, "LEFT SLINGSHOT")]
    assert S.nice("(G)ADGET  TARGET") == "(G)adget target" and S.nice("LEFT RAMP") == "Left ramp"
    mapped = [(2, 1, "Left ramp"), (7, 2, "Spinner"), (9, 4, "Bat hit target")]
    assert S.example_start_shot(mapped) == "Bat hit target"
    assert S.switch_lines(mapped[:1]) == ["switch 2    0x1                Left ramp"]


# ---- on the game programs ---------------------------------------------------------------------------
def _elf(name):
    d = os.environ.get("PAD_PORT_ELFS", "")
    p = os.path.join(d, name) if d else ""
    if not p or not os.path.isfile(p):
        pytest.skip("game program not present (PAD_PORT_ELFS): %s" % name)
    with open(p, "rb") as f:
        return G.Elf(f.read())


@pytest.mark.parametrize("name,gen,event,first,n", [
    ("beatles-1.29.0.elf", "B", 0x34, None, 34),
    ("batman-1.13.0.elf", "A", 0x30, (46, "(g)adget target"), 43),
    ("star_wars_elg-1.10.0.elf", "B", 0x34, None, 30),
    ("rush_le-1.18.0.elf", "A", 0x30, None, 38),
])
def test_the_framework_core_is_read_off_the_program(name, gen, event, first, n):
    elf = _elf(name)
    assert G.generation(G.bus_bound(elf)) == gen
    ev, how = S.ball_end_event(elf)
    assert ev == event, how
    src = S.switch_source(elf)
    assert len(src["mapped"]) == n and src["generation"] == gen
    names = " ".join(m[2].upper() for m in src["mapped"])
    for word in ("TROUGH", "SHOOTER", "FLIPPER", "COIN", "START", "TILT"):
        assert word not in names
    if first:
        assert (src["mapped"][0][0], src["mapped"][0][2]) == (first[0], S.nice(first[1]))
    assert G.is_hooked_ok(elf, S.drain(elf)["leaf"])


def test_the_player_up_is_found_through_the_scores():
    elf = _elf("batman-1.13.0.elf")
    p, how = S.cur_player_via_scores(elf, 0x7fcc88)
    assert p == 0x6e5ea8, how


def test_switch_drain_shots_are_proven_only_where_the_emulator_saw_them(tmp_path):
    body = ["site tick 0x10 0 0", "site switch_edge 0x14 0 0", "site hook_dispatch 0x18 0 0",
            "value ball_end_event 0x30", "site score_add 0x1c 0 0", "data cur_player 0x20", "data scores 0x24",
            "switch 46 0x1 (g)adget target", "switch 52 0x2 Penguin vuk"]
    for name, proven in (("batman-1.13", True), ("aerosmith_le-1.15", False)):
        game, version = name.split("-")
        path = tmp_path / ("%s.port" % name)
        lines = ["game %s" % game, "version %s" % version] + body
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        p = MP.profile_from_port(str(path))
        assert p.switch_shots == ("(g)adget target", "Penguin vuk")
        assert (p.switch_shots_note == "") is proven, (name, p.switch_shots_note)
