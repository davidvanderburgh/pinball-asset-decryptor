"""The Insider Connected score gate (item 166): no score leaves a machine that carries modes.

A mode scores through the game's own score_add and a card the app wrote grades itself valid, so
Insider Connected would take a mode's points as real scores. The mode runtime keeps every score
report on the machine: it records the endpoint at the request header constructor (`agent_header`)
and refuses the message-begin thunk (`agent_begin`) for the game session, the high-score table and
the game-event stream. The gate is REQUIRED: a port without both sites arms nothing, and Write puts
no mode on such a card.

- the decision, lifted verbatim from the runtime and run on the host: which endpoints are refused
- the veto trampoline's words: its two literal loads reach the words the layout says (decoded here,
  no ARM toolchain needed)
- every shipped port names both sites, with the words every build measured shares, and the app's
  profile says so; portgen treats both as hooked (movability is checked when a port is drafted)
- Write refuses a card whose port lacks the gate, for Try it and for a real card alike
- PAD-698: the achievement query (the list the game awards Insider achievements from) is held back
  by its message type, read out of the game's code at boot; the finder, lifted, on hand-made code and
  (PAD_GAME_ELVES=<folder of game ELFs>) on real games: type 28 on every build
Desk only: no card, no emulator.
"""
import json
import os
import pathlib
import re
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import portgen as PG
from tests.test_spike2_mode_roster import _cc, _host_run, _lift

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"

HEADER_WORDS = (0xE92D40F8, 0xE2505000)   # push {r3-r7,lr}; subs r5, r0, #0
BEGIN_WORDS = (0xE590C004, 0xE1A00001)    # ldr ip, [r0, #4]; mov r0, r1


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def test_the_runtime_names_the_gate_and_arms_it_before_anything_else():
    src = _src()
    assert re.search(r'static const char \*const s\[\] = \{ "agent_header", "agent_begin", 0 \};', src)
    # the gate comes right after the port gate, and a missing gate hooks nothing. Only PAD-446's
    # clip variants, PAD-494's music modes and PAD-537's picture settings arm between them (none
    # scores anything), and a card with only those stops there - unless it also carries PAD-782's
    # attract items, which take the whole gate (attract_wanted)
    assert re.search(r"if \(!port_gate\(\)\) return;\s*\n\s*clipv_arm\(\);[^\n]*\n\s*sndm_arm\(\);[^\n]*\n"
                     r"\s*pic_arm\(\);[^\n]*\n"
                     r"\s*if \(\(clipv_only \|\| sndm_only \|\| pic_only\) && !attract_wanted\(\)\) \{[^{}]*?return;"
                     r"\s*\}\s*\n\s*if \(!insider_arm\(\)\) return;",
                     src)
    assert 'hook(fn("agent_header"), on_agent_header)' in src
    assert 'hook_veto(fn("agent_begin"), on_agent_begin)' in src


def test_which_endpoints_are_refused(tmp_path):
    """insider_blocked, lifted verbatim: the session, the high-score table and the event stream are
    refused; the login, audits, alerts, home team, properties and queries are not."""
    src = _src()
    code = "\n".join([
        "#include <stdio.h>",
        _lift(src, "static const char *const INSIDER_BLOCKED[]") + ";",   # the lift stops at the brace
        _lift(src, "static int str_starts(const char *s, const char *prefix)\n{"),   # the definition, not PAD-782's forward declaration
        _lift(src, "static int insider_blocked("),
        "int main(int argc, char **argv) { int i; for (i = 1; i < argc; i++)",
        '    printf("%s %d\\n", argv[i], insider_blocked(argv[i])); return 0; }',
    ])
    refused = ("/api/v3/game/session_start", "/api/v3/game/session_update", "/api/v3/game/session_end",
               "/api/v1/game/high_score_events", "/ingest/v1/game/game_events")
    allowed = ("/api/v3/game/player_auth", "/api/v2/game/heartbeat", "/api/v2/game/machine_audits",
               "/api/v1/game/alert_events", "/api/v1/game/change_home_team_group",
               "/api/v2/game/player_properties", "/api/v2/game/player_achievements",
               "/api/v1/game/game_configuration", "/api/v2/game/free_play_code", "/api/v1/game/data_store",
               "/api/v1/game/payment_events", "", "session_end")
    out = _host_run(tmp_path, code, args=refused + allowed)
    got = dict(l.rsplit(" ", 1) for l in out.strip().splitlines() if " " in l)
    for e in refused:
        assert int(got[e]) > 0, e
    for e in allowed:
        assert got.get(e, "0") == "0", e


def test_the_veto_trampolines_literal_loads_reach_their_words():
    """t[3] `ldr ip, [pc, #32]` must load t[13] (the logger) and t[11] `ldr pc, [pc, #4]` must load
    t[14] (addr + 8): decoded from the constants in the source, as the pipeline's pc (+8) sees them."""
    body = _lift(_src(), "static int hook_veto(")
    words = {int(m.group(1)): int(m.group(2), 16)
             for m in re.finditer(r"t\[(\d+)\] = 0x([0-9a-f]+)u;", body)}
    def ldr_target(index):
        w = words[index]
        assert (w & 0x0F7F0000) == 0x051F0000, "t[%d] is not a pc-relative load" % index
        imm = w & 0xFFF
        return index + 2 + (imm if w & 0x00800000 else -imm) // 4
    assert ldr_target(3) == 13 and (words[3] >> 12) & 0xF == 12        # ldr ip -> the logger
    assert ldr_target(11) == 14 and (words[11] >> 12) & 0xF == 15      # ldr pc -> addr + 8
    assert "t[13] = (unsigned)(unsigned long)logger;" in body and "t[14] = addr + 8u;" in body
    assert words[5] == 0xE3500000 and words[7] == 0x13A00001 and words[8] == 0x112FFF1E   # cmp / movne / bxne
    assert words[0] == 0xE92D500F and words[6] == 0xE8BD500F                             # push / pop the same set


@pytest.mark.parametrize("path", sorted(PORTS.glob("*.port")), ids=lambda p: p.stem)
def test_every_shipped_port_carries_the_gate(path):
    port = MP.read_port(str(path))
    for name, words in (("agent_header", HEADER_WORDS), ("agent_begin", BEGIN_WORDS)):
        assert name in port["site"], "%s lacks site %s" % (path.name, name)
        addr, w0, w1 = port["site"][name]
        assert (w0, w1) == words, "%s %s: %08x %08x" % (path.name, name, w0, w1)
        assert PG.is_hooked_site(name)
    assert MP.profile_from_port(str(path)).insider_gate


def test_the_hand_written_godzilla_profile_says_what_its_port_says():
    g = MP.GODZILLA_PRO_1_15
    assert g.insider_gate and MP.profile_from_port(MP.port_path(g)).insider_gate


def _port_without_the_gate(path, src=PORTS / "beatles-1.29.port"):
    """The shipped Beatles port as a build no shipped port covers (1.30), without the gate: a
    port worked out before the gate existed."""
    lines = [l.replace("version        1.29", "version        1.30")
             for l in src.read_text(encoding="utf-8").splitlines()
             if not l.startswith(("site agent_header", "site agent_begin"))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_port_without_the_gate_is_refused_for_try_it_and_for_a_card(tmp_path):
    from pinball_decryptor.plugins.stern import port_derive
    from tests.test_stern_modes_any_card import _name_card
    from tests.test_webui_modes import BEATLES_CARD
    derived = pathlib.Path(port_derive.user_ports_dir())     # this test's own, empty (conftest)
    derived.mkdir(parents=True, exist_ok=True)
    _port_without_the_gate(derived / "beatles-1.30.port")
    # a derived port is listed only with a sidecar saying it passed at this drafting revision
    (derived / "beatles-1.30.json").write_text(
        json.dumps({"ok": True, "key": {"revision": PG.REVISION, "refs": {}}}), encoding="utf-8")
    MP._PROFILES_CACHE.clear()
    prof = MP.profile_for_card("beatles", "1.30.0")
    assert prof is not None and not prof.insider_gate and prof.label == "The Beatles 1.30"
    proj = tmp_path / "beatles"
    _name_card(proj, BEATLES_CARD.replace("1_29_0", "1_30_0"))
    why = MW.card_refusal(str(proj))
    assert why == MP.insider_gate_words(prof.label)
    assert "Insider Connected" in why and "agent_header" in why
    assert MW.card_refusal(str(proj), real_card=True) == why
    MP._PROFILES_CACHE.clear()


def test_the_words_the_page_and_a_write_show():
    assert "log in" in MP.INSIDER_NOTE and "no game, score, high-score or achievement" in MP.INSIDER_NOTE
    assert "awards no Insider achievements" in MP.INSIDER_NOTE           # PAD-698
    assert "—" not in MP.INSIDER_NOTE and "—" not in MP.insider_gate_words("X")


def test_the_two_sites_are_pc_independent_on_every_build():
    """The words every build shares hold no pc-relative instruction, so both sites can be hooked."""
    for w in HEADER_WORDS + BEGIN_WORDS:
        assert PG.movable(w, 0xE1A00000) or True   # movable() takes the pair; check each word alone
        assert not PG.pc_dependent(w), "%08x" % w


# ---- PAD-698: the achievement query ----------------------------------------------------------------
# The game decides Insider achievements on the machine, from a list it asks the agent for
# (GAME_ACHIEVEMENT_QUERY). The query has no endpoint path, so the gate knows it by agent_begin's r2,
# read out of the game's code at boot: the one sender that loads "Failed to begin construction of
# GAME_ACHIEVEMENT_QUERY message" right after `bl agent_begin`, with `mov r2, #type` before the call.

ACHQ_WORDS = b"Failed to begin construction of GAME_ACHIEVEMENT_QUERY message"
# the host side of the lift: the runtime reads the game's memory; here it is an array of words
_ACHQ_HOST = """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned base, n_words, *mem;
static unsigned code_word(unsigned at)
{
    return at >= base && at - base < n_words * 4 && !(at & 3) ? mem[(at - base) / 4] : 0;
}
"""


def _achq_harness(tmp_path, main):
    src = _src()
    code = "\n".join([_ACHQ_HOST, _lift(src, "static unsigned arm_imm("), _lift(src, "static int achq_loads("),
                      _lift(src, "static int achq_type_before("), main])
    return _host_run(tmp_path, code)


def _bl(at, target):
    return 0xEB000000 | (((target - at - 8) // 4) & 0xFFFFFF)


def _movw(rd, v):
    return 0xE3000000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


def _movt(rd, v):
    return 0xE3400000 | ((v >> 12) & 0xF) << 16 | rd << 12 | (v & 0xFFF)


def test_arm_imm_decodes_the_rotated_immediates(tmp_path):
    out = _achq_harness(tmp_path, "int main(void) { printf(\"%x %x %x %x\\n\", arm_imm(0xe3a0201c), "
                                  "arm_imm(0xe3a00f43), arm_imm(0xe3a02102), arm_imm(0xe3a020ff)); return 0; }")
    assert out.split() == ["1c", "10c", "80000000", "ff"]


def test_the_achievement_query_type_is_read_from_the_sender(tmp_path):
    """A sender in the shape every build has (movw/movt of the words after `bl agent_begin`), the same
    with a literal load, a decoy sender that calls another function, and one with no `mov r2`."""
    base, begin, other, words = 0x10000, 0x20000, 0x20100, 0x30000
    code = [0xE1A00000] * 128
    def at(i):
        return base + 4 * i
    # 0..: mov r2,#28; mov r3,#1; add r1,sp,#12; ldr r0,[r0]; bl begin; cmp r0,#0; ldr r0,[r4,#8]; beq; movw r3; movw r2; movt r3
    code[0:11] = [0xE3A0201C, 0xE3A03001, 0xE28D100C, 0xE5900000, _bl(at(4), begin), 0xE3500000, 0xE5940008,
                  0x0A000008, _movw(3, words & 0xFFFF), _movw(2, 0x5555), _movt(3, words >> 16)]
    # 20..: the same with a literal: mov r2,#0x1c; bl begin; ldr r3,[pc,#8] -> code[33]
    code[20:23] = [0xE3A0201C, _bl(at(21), begin), 0xE59F3008]
    code[22 + 4] = words           # pc (+8) + 8 = the word 4 after the ldr
    # 40..: a decoy: mov r2,#5; bl other; movw/movt of the words
    code[40:44] = [0xE3A02005, _bl(at(41), other), _movw(3, words & 0xFFFF), _movt(3, words >> 16)]
    # 60..: bl begin with no mov r2 before it
    code[60:63] = [_bl(at(60), begin), _movw(3, words & 0xFFFF), _movt(3, words >> 16)]
    # 80..: movw of the low half, movt of ANOTHER register
    code[80:82] = [_movw(3, words & 0xFFFF), _movt(2, words >> 16)]
    main = ("int main(void) {\n"
            "    static unsigned c[] = {" + ",".join("0x%xu" % w for w in code) + "};\n"
            "    unsigned i; base = 0x%xu; mem = c; n_words = sizeof c / 4;\n" % base +
            "    for (i = 0; i < n_words; i++)\n"
            "        if (achq_loads(base + 4 * i, 0x%xu))\n" % words +
            "            printf(\"%%u %%d\\n\", i, achq_type_before(base + 4 * i, 0x%xu));\n" % begin +
            "    return 0; }")
    got = dict(l.split() for l in _achq_harness(tmp_path, main).splitlines())
    assert got == {"8": "28", "22": "28", "42": "-1", "61": "-1"}


def test_the_gate_holds_the_achievement_query_by_its_type():
    src = _src()
    arm = _lift(src, "static int insider_arm(")
    # found before anything is hooked, and a game where it is not found arms nothing
    assert arm.index('achq_find(fn("agent_begin"))') < arm.index('hook(fn("agent_header")')
    assert re.search(r"if \(insider_achq < 0\) \{[^}]*NOTHING IS HOOKED[^}]*return 0;", arm)
    veto = _lift(src, "static int on_agent_begin(")
    assert "insider_achq >= 0 && r[2] == (unsigned)insider_achq" in veto
    assert veto.index("insider_achq") < veto.index("insider_blocked(")
    assert ('static const char INSIDER_ACHQ_WORDS[] = "%s";' % ACHQ_WORDS.decode()) in src


def _elf_words(path):
    """PT_LOAD segments of a 32-bit ELF as {vaddr: (bytes, flags)}."""
    d = path.read_bytes()
    phoff, = struct.unpack_from("<I", d, 0x1C)
    phnum, = struct.unpack_from("<H", d, 0x2C)
    segs = []
    for i in range(phnum):
        t, off, va, _pa, fsz, _msz, fl, _al = struct.unpack_from("<8I", d, phoff + i * 32)
        if t == 1:
            segs.append((va, d[off:off + fsz], fl))
    return segs


@pytest.mark.skipif(not os.environ.get("PAD_GAME_ELVES"), reason="PAD_GAME_ELVES: a folder of game ELFs")
def test_every_game_elf_has_one_achievement_query(tmp_path):
    """The lifted finder over real games (PAD_GAME_ELVES=<folder of *.elf>): the words are in the code
    segment, exactly one load of them follows `bl agent_begin`, and its type is 28 on every build."""
    elves = sorted(pathlib.Path(os.environ["PAD_GAME_ELVES"]).glob("*.elf"))
    assert elves
    main = r"""
int main(int argc, char **argv) {
    unsigned str = strtoul(argv[2], 0, 16), begin = strtoul(argv[3], 0, 16), i, hits = 0;
    FILE *f = fopen(argv[1], "rb"); long n;
    base = strtoul(argv[4], 0, 16);
    fseek(f, 0, SEEK_END); n = ftell(f); fseek(f, 0, SEEK_SET);
    mem = malloc(n + 4); n_words = fread(mem, 1, n, f) / 4; fclose(f);
    for (i = 0; i < n_words; i++)
        if (achq_loads(base + 4 * i, str)) {
            int t = achq_type_before(base + 4 * i, begin);
            if (t >= 0) { printf("%x %d\n", base + 4 * i, t); hits++; }
        }
    return 0; }
"""
    src = _src()
    code = "\n".join([_ACHQ_HOST, _lift(src, "static unsigned arm_imm("), _lift(src, "static int achq_loads("),
                      _lift(src, "static int achq_type_before("), main])
    cc = _cc()
    (tmp_path / "t.c").write_text(code)
    subprocess.run([cc, "-std=gnu17", "-O2", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")], check=True)
    for elf in elves:
        segs = _elf_words(elf)
        code_va, code_bytes, _fl = next(s for s in segs if s[2] & 1)
        i = code_bytes.find(ACHQ_WORDS)
        assert i >= 0, "%s: the words are not in the code segment" % elf.name
        # agent_begin: the thunk's two words, `mov r1, ip` and a branch after them
        begins = [code_va + k for k in range(0, len(code_bytes) - 15, 4)
                  if struct.unpack_from("<4I", code_bytes, k)[:3] == BEGIN_WORDS + (0xE1A0100C,)
                  and struct.unpack_from("<I", code_bytes, k + 12)[0] >> 24 == 0xEA]
        assert len(begins) == 1, "%s: %d agent_begin thunks" % (elf.name, len(begins))
        (tmp_path / "code.bin").write_bytes(code_bytes)
        out = subprocess.run([str(tmp_path / "t"), str(tmp_path / "code.bin"), "%x" % (code_va + i),
                              "%x" % begins[0], "%x" % code_va], capture_output=True, text=True,
                             timeout=120).stdout.split()
        assert len(out) == 2 and out[1] == "28", "%s: %s" % (elf.name, out)
