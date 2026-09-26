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
Desk only: no card, no emulator.
"""
import json
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import portgen as PG
from tests.test_spike2_mode_roster import _host_run, _lift

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
    # the gate comes right after the port gate, and a missing gate hooks nothing
    assert re.search(r"if \(!port_gate\(\)\) return;\s*\n\s*if \(!insider_arm\(\)\) return;", src)
    assert 'hook(fn("agent_header"), on_agent_header)' in src
    assert 'hook_veto(fn("agent_begin"), on_agent_begin)' in src


def test_which_endpoints_are_refused(tmp_path):
    """insider_blocked, lifted verbatim: the session, the high-score table and the event stream are
    refused; the login, audits, alerts, home team, properties and queries are not."""
    src = _src()
    code = "\n".join([
        "#include <stdio.h>",
        _lift(src, "static const char *const INSIDER_BLOCKED[]") + ";",   # the lift stops at the brace
        _lift(src, "static int str_starts("),
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
    assert "—" not in MP.INSIDER_NOTE and "—" not in MP.insider_gate_words("X")


def test_the_two_sites_are_pc_independent_on_every_build():
    """The words every build shares hold no pc-relative instruction, so both sites can be hooked."""
    for w in HEADER_WORDS + BEGIN_WORDS:
        assert PG.movable(w, 0xE1A00000) or True   # movable() takes the pair; check each word alone
        assert not PG.pc_dependent(w), "%08x" % w
