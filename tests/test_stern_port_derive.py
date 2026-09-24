"""Ports for any Spike 2 game build: drafted from recipes, derived per build, found by every lookup.

- portgen: a recipe (the reference half of a draft) is current for every shipped port and holds
  hashes, masks and offsets, not the reference's code; a draft of a reference from another
  reference is byte-identical to the committed one, drafted from the recipe with the target
  alone AND with both programs (port_tool.py's way); the core takes either scoring pair; a
  32-bit score function is told from a 64-bit one.
- port_derive.merge: only entries the references agree on are kept; a fallback placement gives
  way to a reference's own; the same title decides a role another title fills differently.
- The lookups (mode_runtime.port_file/ports/port_paths, mode_project.profiles,
  mode_write.find_port) read the ports derived on this machine after the shipped ones.
- With the game programs present (folders in PAD_PORT_ELFS or PAD_GAME_ELFS, joined with
  os.pathsep; skipped
  otherwise): ensure_port finds a shipped port, derives and caches one, refuses one that lacks a
  core entry, and stops when asked; leave-one-out on Godzilla LE 1.16 reproduces its proven
  port; the shot readers find the census-proven bits.
Desk only; nothing here runs the emulator.
"""
import dataclasses
import json
import os
import pathlib
import re
import struct
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
PORTS = SDK / "ports"
FIXTURES = REPO / "tests" / "fixtures" / "ports"

from pinball_decryptor.plugins.stern import mode_project as MP  # noqa: E402
from pinball_decryptor.plugins.stern import mode_runtime as MR  # noqa: E402
from pinball_decryptor.plugins.stern import mode_write as MW  # noqa: E402
from pinball_decryptor.plugins.stern import port_derive as D  # noqa: E402
from pinball_decryptor.plugins.stern import portgen as G  # noqa: E402

#: folders of <game>-<version>.elf game programs (PAD_PORT_ELFS, else PAD_GAME_ELFS; several
#: joined with os.pathsep); the tests that need one skip without it
ELF_DIRS = [d for v in ("PAD_PORT_ELFS", "PAD_GAME_ELFS")
            for d in (os.environ.get(v) or "").split(os.pathsep) if d]


def _elf_path(name):
    for d in ELF_DIRS:
        p = os.path.join(d, name) if d else ""
        if p and os.path.isfile(p):
            return p
    pytest.skip("game program not present: %s" % name)


def _elf_bytes(name):
    with open(_elf_path(name), "rb") as f:
        return f.read()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "titles"))
    return tmp_path / "titles" / "ports"


def _entries(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^(site|data|scene)\s+(\S+)\s+(\S+)", line)
        if m:
            out[(m.group(1), m.group(2))] = m.group(3).lower()
    return out


# ---- a synthetic program ---------------------------------------------------------------------------
def _program(words, base=0x10000):
    """A 32-bit ELF with one executable PT_LOAD holding `words` from `base`."""
    body = struct.pack("<%dI" % len(words), *words)
    hdr = bytearray(0x34 + 32)
    hdr[:4] = b"\x7fELF"
    hdr[4] = 1
    struct.pack_into("<I", hdr, 0x1C, 0x34)
    struct.pack_into("<HH", hdr, 0x2A, 32, 1)
    struct.pack_into("<8I", hdr, 0x34, 1, len(hdr), base, base, len(body), len(body), 5, 0x1000)
    return bytes(hdr) + body


PUSH, POP, NOP = 0xE92D4010, 0xE8BD8010, 0xE1A00000


# ---- recipes -----------------------------------------------------------------------------------------
def _shipped():
    return sorted(p.name for p in PORTS.glob("*.port"))


@pytest.mark.parametrize("name", _shipped())
def test_every_shipped_port_has_a_current_recipe(name):
    """A port whose recipe is missing or stale is never a reference: rebuild it with
    `port_tool.py recipe <its program> ports/<port>` when a port's entries change."""
    recipe = PORTS / "recipes" / (name[:-len(".port")] + ".recipe.gz")
    assert recipe.is_file(), "no recipe for %s" % name
    r = G.load_recipe(str(recipe))
    assert r["entries_sha1"] == G.entries_sha1(PORTS.joinpath(name).read_text(encoding="utf-8"))
    assert r["port"] == name and r["generation"] in ("A", "B")


def test_a_recipe_holds_hashes_masks_and_offsets_not_code():
    r = G.load_recipe(str(PORTS / "recipes" / "godzilla_pro-1.15.recipe.gz"))
    for v0, v1, masks, hashes in r["chains"]:
        assert set(masks) <= set("fbpw")
        assert all(isinstance(h, int) for h in hashes.values())
    assert set(r) >= {"chains", "ladders", "sites", "data", "scenes", "bus", "bus_bound"}


def test_the_core_takes_either_scoring_pair():
    core = {"tick", "shot_dispatch", "ball_end"}
    assert G.core_missing(core | {"score_add"}, {"cur_player", "scores"}) == []
    assert G.core_missing(core | {"score_add32"}, {"cur_player", "scores32"}) == []
    assert G.core_missing(core | {"score_add32"}, {"cur_player"}) == ["scores32"]
    assert G.core_missing(core, {"cur_player", "scores"}) == ["score_add"]
    assert G.core_missing({"tick"}, set()) == ["shot_dispatch", "ball_end", "score_add", "cur_player", "scores"]
    # a u32 score slot and a u64 one are never mixed
    assert G.core_missing(core | {"score_add"}, {"cur_player", "scores32"}) == ["scores"]


def test_a_32_bit_score_function_is_told_from_a_64_bit_one():
    umull = 0xE0832594          # umull r2, r3, r4, r5
    mul = 0xE0010593            # mul r1, r3, r5
    wide = G.Elf(_program([0xE30435DE, PUSH, umull, NOP, POP]))
    narrow = G.Elf(_program([0xE30435DE, PUSH, mul, NOP, POP]))
    assert G.score_width(wide, 0x10000) == 64
    assert G.score_width(narrow, 0x10000) == 32
    assert G.score_width(G.Elf(_program([PUSH, NOP, POP])), 0x10000) == 0


def test_the_event_bus_and_its_subscribers_are_read_from_the_program():
    words = [0xE35000CF, PUSH, POP,                      # 0x10000 dispatch: cmp r0, #0xcf; push
             0xE35100CF, PUSH, POP,                      # 0x1000c subscribe: cmp r1, #0xcf; push
             PUSH, 0xE3A01034,                           # 0x10018: mov r1, #0x34
             0xE3002100, 0xE3402001,                     # movw r2, #0x100; movt r2, #0x1 -> 0x10100
             0xEBFFFFF7, POP]                            # bl 0x1000c
    words += [NOP] * (64 - len(words)) + [PUSH, POP]     # 0x10100: the handler
    e = G.Elf(_program(words))
    assert G.bus_bound(e) == 0xCF and G.generation(G.bus_bound(e)) == "B"
    assert G.subscriptions(e) == {0x34: [0x10100]}
    assert G.generation(191) == "A" and G.generation(0) == ""


# ---- merging drafts --------------------------------------------------------------------------------
class _Tgt:
    def word(self, va):
        return 0xE92D4010


def _ref(name, game, version):
    return types.SimpleNamespace(name=name, game=game, version=version, label="%s %s" % (game, version))


def _draft(ref, placed, how=None, shots=("0x1 Left ramp",)):
    lines = ["game x", "version 1"]
    for (kind, name), v in placed.items():
        lines.append("site %-16s 0x%08x 0x1 0x2" % (name, v) if kind == "site" else "data %-22s 0x%08x" % (name, v))
    lines += ["shot %s" % s for s in shots]
    return dict(ref=ref, lines=lines, placed=dict(placed), how=how or {k: "located (strict)" for k in placed},
                missing=[], seconds=0.1)


def test_the_merge_keeps_what_the_references_agree_on():
    refs = [_ref("a-1.0", "godzilla_pro", "1.15"), _ref("b-1.0", "godzilla_le", "1.16"), _ref("c-1.0", "jaws_le", "1.02")]
    core = {("site", "tick"): 0x100, ("site", "shot_dispatch"): 0x200, ("site", "ball_end"): 0x300,
            ("site", "score_add"): 0x400, ("data", "cur_player"): 0x9000, ("data", "scores"): 0x9100}
    a = _draft("a-1.0", {**core, ("site", "callout"): 0x500, ("data", "mode_mask"): 0x9200})
    b = _draft("b-1.0", {**core, ("site", "callout"): 0x500, ("data", "mode_mask"): 0x9300})
    c = _draft("c-1.0", {**core, ("site", "callout"): 0x600})
    body, prov, missing, _notes = D.merge({"a-1.0": a, "b-1.0": b, "c-1.0": c}, refs, _Tgt(), "godzilla_pro",
                                          "1.16.0", "cmode")
    text = "\n".join(body)
    assert missing == []
    assert "site tick             0x00000100" in text and prov["site tick"]["refs"] == ["a-1.0", "b-1.0", "c-1.0"]
    # the same title decides a role another title fills differently
    assert "site callout          0x00000500" in text and "other titles' ports place 0x600" in prov["site callout"]["how"]
    # two same-title references that disagree leave it out, saying so
    assert "data mode_mask" not in text.replace("# data mode_mask", "")
    assert re.search(r"# data mode_mask\s+NOT PLACED: the references disagree", text)
    assert "shot 0x1 Left ramp" in text and "version        1.16" in text


def test_a_fallback_placement_gives_way_to_a_references_own(monkeypatch):
    monkeypatch.setattr(D, "framework_core", lambda *a: dict(values=[], mapped=[], switch_lines=[], example="", notes=[]))
    refs = [_ref("a-1.0", "godzilla_pro", "1.15"), _ref("b-1.0", "godzilla_pro", "1.14")]
    k = ("site", "ball_end")
    a = _draft("a-1.0", {k: 0x300}, how={k: "the handler of event 0x34 (the end of ball) ..."})
    b = _draft("b-1.0", {k: 0x310}, how={k: "through the handler of hook 0x34, as in the reference"})
    body, prov, _missing, _notes = D.merge({"a-1.0": a, "b-1.0": b}, refs, _Tgt(), "godzilla_pro", "1.16", "cmode")
    assert prov["site ball_end"]["value"] == "0x310" and prov["site ball_end"]["refs"] == ["b-1.0"]


def test_a_draft_that_lacks_a_core_entry_says_so(monkeypatch):
    monkeypatch.setattr(D, "framework_core", lambda *a: dict(values=[], mapped=[], switch_lines=[], example="", notes=[]))
    refs = [_ref("a-1.0", "godzilla_pro", "1.15")]
    a = _draft("a-1.0", {("site", "tick"): 0x100, ("data", "cur_player"): 0x9000})
    _body, _prov, missing, _notes = D.merge({"a-1.0": a}, refs, _Tgt(), "godzilla_pro", "1.16", "cmode")
    assert missing == ["shot_dispatch", "ball_end", "score_add", "scores"]


def test_a_port_version_is_spelled_as_the_card_spells_it():
    assert [D.port_version(v) for v in ("1.29.0", "1_02_0", "1.09", "1.15.1", "0.97.0")] == \
        ["1.29", "1.02", "1.09", "1.15.1", "0.97"]


# ---- every lookup reads the derived folder --------------------------------------------------------
PORT_TEXT = """# zzz_test 1.00 - port DERIVED on this machine. NOT RUN: drafted and never run.
game           zzz_test
version        1.00
site tick             0x00010000 0xe92d4010 0xe1a00000
site shot_dispatch    0x00010008 0xe8bd8010 0xe92d4010
site ball_end         0x00010000 0xe92d4010 0xe1a00000
site score_add        0x00010000 0xe92d4010 0xe1a00000
data cur_player             0x00020000
data scores                 0x00020010
shot 0x1         Left ramp
"""


def _put_derived(name, text, key=None, ok=True):
    """A port in the derived folder with the sidecar ensure_port writes (current by default)."""
    derived = D.user_ports_dir()
    path = os.path.join(derived, name + ".port")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if key is not False:
        side = dict(key=key if key is not None else dict(elf_sha1="0" * 40, revision=G.REVISION, refs={}), ok=ok)
        with open(os.path.join(derived, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(side, f)
    return path


def test_a_derived_port_is_found_by_every_lookup(cache):
    derived = D.user_ports_dir()
    assert pathlib.Path(derived) == cache and derived in MR.port_dirs() and MR.port_dirs()[0] == str(PORTS)
    path = _put_derived("zzz_test-1.00", PORT_TEXT)
    assert MR.port_file("zzz_test", "1.00.0") == path
    assert ("zzz_test", "1.00") in MR.ports()
    p = MP.profiles()["zzz_test_1_00"]
    assert p.proven is False and p.port == path and MP.port_path(p) == path
    assert MP.profile_for_card("zzz_test", "1_00_0").key == "zzz_test_1_00"
    elf = _program([PUSH, NOP, POP, PUSH])
    assert MW.find_port(p, elf) == path


def _gone(path):
    return (MR.port_file("zzz_test", "1.00") is None and ("zzz_test", "1.00") not in MR.ports()
            and "zzz_test_1_00" not in MP.profiles() and path not in [p for _g, _v, p in MR.port_paths()])


def test_a_derived_port_that_is_no_longer_current_is_left_out(cache):
    """A portgen fix or a corrected shipped reference reaches a port a person already has: every
    lookup skips a derived port whose sidecar is missing, failed, of another drafting revision or
    names a reference port or recipe that has changed, until the card is read again."""
    ref = "godzilla_pro-1.15"
    real = [G.entries_sha1((PORTS / (ref + ".port")).read_text(encoding="utf-8")),
            D._sha1_file(str(PORTS / "recipes" / (ref + ".recipe.gz")))]
    good = dict(elf_sha1="0" * 40, revision=G.REVISION, refs={ref: real})
    path = _put_derived("zzz_test-1.00", PORT_TEXT, key=good)
    assert D.derived_current(path) and MR.port_file("zzz_test", "1.00") == path
    for key, ok in ((False, True),                                        # no sidecar
                    (good, False),                                        # a failed derivation
                    (dict(good, revision=G.REVISION - 1), True),          # another drafting revision
                    (dict(good, refs={ref: [real[0], "0" * 40]}), True),  # the recipe changed
                    (dict(good, refs={ref: ["0" * 40, real[1]]}), True),  # the reference port changed
                    (dict(good, refs={"gone-1.00": real}), True)):        # the reference is gone
        side = os.path.join(D.user_ports_dir(), "zzz_test-1.00.json")
        if os.path.exists(side):
            os.remove(side)
        _put_derived("zzz_test-1.00", PORT_TEXT, key=key, ok=ok)
        assert not D.derived_current(path) and _gone(path), (key, ok)


def test_a_proven_profile_is_never_written_with_a_port_that_never_ran(cache):
    """A project made on one build, written to a card of a build whose only port was derived on
    this machine, is refused (naming the build to make it for), not written quietly."""
    path = _put_derived("zzz_test-1.00", PORT_TEXT)
    own = MP.profiles()["zzz_test_1_00"]
    other = dataclasses.replace(own, key="zzz_test_0_99", label="Zzz Test 0.99", version="0.99",
                                port="zzz_test-0.99.port", proven=True, proven_note="")
    elf = _program([PUSH, NOP, POP, PUSH])
    with pytest.raises(MW.ModeWriteError, match="never run in the emulator"):
        MW.find_port(other, elf)
    assert MW.find_port(own, elf) == path
    assert MW.port_unproven(path) and not MW.port_unproven(str(PORTS / "godzilla_le-1.16.port"))


def test_a_shipped_port_wins_over_a_derived_one(cache):
    _put_derived("godzilla_pro-1.15", PORT_TEXT.replace("zzz_test", "godzilla_pro").replace("1.00", "1.15"))
    assert MR.port_file("godzilla_pro", "1.15") == str(PORTS / "godzilla_pro-1.15.port")
    assert MP.profiles()["godzilla_pro_1_15"] is MP.GODZILLA_PRO_1_15
    paths = [p for g, v, p in MR.port_paths() if (g, v) == ("godzilla_pro", "1.15")]
    assert paths[0] == str(PORTS / "godzilla_pro-1.15.port") and len(paths) == 2


def _card_project(tmp_path, image_name):
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(proj / image_name), "input_name": image_name}), encoding="utf-8")
    return str(proj)


def test_a_stale_derived_port_is_gone_from_every_lookup_at_once(cache, tmp_path):
    """One source list (review M3): a derived port whose sidecar went stale (an app update
    raised portgen.REVISION) is left out by the tab's lookups (profiles, profile,
    profile_for_card, a profile a read remembered), by Try it's (port_file) and by Write's
    (find_port, card_refusal) alike, so Write leaves the modes out with the reason instead of
    failing the whole build after card_refusal said yes."""
    good = dict(elf_sha1="0" * 40, revision=G.REVISION, refs={})
    path = _put_derived("zzz_test-1.00", PORT_TEXT, key=good)
    prof = MP.remember_profile(MP.profile_from_port(path))
    proj = _card_project(tmp_path, "zzz_test-1_00_0.raw")
    assert MP.profile_for_card("zzz_test", "1.00.0").key == "zzz_test_1_00"
    assert MP.profile("zzz_test_1_00").port == path
    assert MW.card_refusal(proj) == ""
    _put_derived("zzz_test-1.00", PORT_TEXT, key=dict(good, revision=G.REVISION - 1))
    assert not D.derived_current(path) and _gone(path)
    assert MP.profile_for_card("zzz_test", "1.00.0") is None
    with pytest.raises(MP.ModeProjectError):
        MP.profile("zzz_test_1_00")                      # the remembered one is dropped too
    assert MW.card_refusal(proj).startswith("Modes of your own can't be made for ZZZ Test 1.00")
    with pytest.raises(MW.ModeWriteError):
        MW.find_port(prof, _program([PUSH, NOP, POP, PUSH]))
    # derived again (current): back in every lookup
    _put_derived("zzz_test-1.00", PORT_TEXT, key=good)
    assert MP.profile_for_card("zzz_test", "1.00.0").key == "zzz_test_1_00"
    assert MR.port_file("zzz_test", "1.00") == path


def test_a_derived_port_goes_on_a_real_card_only_after_a_live_try_it(cache, tmp_path):
    """Review M6 (the Write half): a port derived on this machine that no Try it has run
    live is emulator-only. A Write to a card or an image leaves the modes out and says to
    press Try it once first; Try it's own set (real_card=False) is not refused. The live run
    is recorded beside the port and tied to its text: a port derived again with other
    entries needs another Try it."""
    path = _put_derived("zzz_test-1.00", PORT_TEXT)
    proj = _card_project(tmp_path, "zzz_test-1_00_0.raw")
    prof = MP.profile_for_card("zzz_test", "1.00.0")
    assert D.is_derived(path) and not D.is_derived(str(PORTS / "godzilla_le-1.16.port"))
    assert MW.derived_not_run(prof) and not D.ran_live(path)
    why = MW.card_refusal(proj, real_card=True)
    assert "Press Try it once first" in why and "port" not in why
    assert MW.card_refusal(proj) == "" and MW.card_refusal(proj, real_card=False) == ""
    MP.new_mode(proj, "HELP", MP.blank_spec(prof))
    lines = MW.pending_lines(proj)
    assert lines and all("not put on the card" in ln and "Press Try it once first" in ln
                         for ln in lines)
    # a Try it reached live with the runtime's hooks: recorded, and Write carries the modes
    assert D.record_live_run(path, "armed: 1 mode(s); can callout")
    assert D.ran_live(path) and not MW.derived_not_run(prof)
    assert MW.card_refusal(proj, real_card=True) == ""
    # the port derived again with another entry: its live run no longer counts
    with open(path, "a", encoding="utf-8") as f:
        f.write("shot 0x2         Right ramp\n")
    assert not D.ran_live(path) and "Try it once" in MW.card_refusal(proj, real_card=True)
    # a shipped port never needs one
    assert not D.record_live_run(str(PORTS / "godzilla_le-1.16.port"))
    gz = MP.profile("godzilla_le_1_16")
    assert not MW.derived_not_run(gz)


# ---- with the game programs ------------------------------------------------------------------------
DRAFTS = [("turtles_pro-1.59", "turtles_pro-1.59.0.elf", "turtles_pro-1.58.0.elf", "turtles_pro", "1.58"),
          ("beatles-1.29", "beatles-1.29.0.elf", "star_wars_elg-1.10.0.elf", "star_wars_elg", "1.10")]


@pytest.mark.slow
@pytest.mark.parametrize("ref,ref_elf,tgt_elf,game,version", DRAFTS)
def test_a_draft_is_byte_identical_to_the_committed_one(ref, ref_elf, tgt_elf, game, version):
    want = (FIXTURES / ("%s-%s__from__%s.port" % (game, version, ref))).read_text(encoding="utf-8")
    text = (PORTS / (ref + ".port")).read_text(encoding="utf-8")
    tgt = G.Elf(_elf_path(tgt_elf))
    recipe = G.load_recipe(str(PORTS / "recipes" / (ref + ".recipe.gz")))
    from_recipe = G.apply_recipe(recipe, text, tgt, game, version, port_name=ref + ".port", target_name=tgt_elf)
    assert from_recipe.text == want
    both = G.draft(G.Elf(_elf_path(ref_elf)), text, tgt, game, version, port_name=ref + ".port", target_name=tgt_elf)
    assert both.text == want


@pytest.mark.slow
def test_tmnt_158_drafted_from_159_is_its_proven_port():
    """The current-player byte TMNT 1.58 loads in 400 places: the first 60 all changed, the
    shortest of the rest line up."""
    want = _entries((PORTS / "turtles_pro-1.58.port").read_text(encoding="utf-8"))
    got = _entries((FIXTURES / "turtles_pro-1.58__from__turtles_pro-1.59.port").read_text(encoding="utf-8"))
    _elf_path("turtles_pro-1.58.0.elf")
    assert got == want


@pytest.mark.slow
def test_ensure_port_finds_a_shipped_port(cache):
    r = D.ensure_port(_elf_bytes("godzilla_le-1.16.0.elf"), "godzilla_le", "1.16.0", workers=1)
    assert r.origin == "shipped" and r.path == str(PORTS / "godzilla_le-1.16.port") and r.proven


@pytest.mark.slow
def test_ensure_port_derives_caches_and_rederives(cache):
    elf = _elf_bytes("godzilla_pro-1.16.0.elf")
    seen = []
    r = D.ensure_port(elf, "godzilla_pro", "1.16.0", progress=lambda f, s: seen.append(f), workers=1)
    assert r.origin == "derived" and not r.proven and not r.missing
    assert pathlib.Path(r.path) == cache / "godzilla_pro-1.16.port"
    text = pathlib.Path(r.path).read_text(encoding="utf-8")
    assert "NOT RUN" in text.splitlines()[1] and G.check_port(text, G.Elf(elf)) == []
    assert seen[0] == 0.0 and seen[-1] == 1.0 and seen == sorted(seen)
    side = json.loads((cache / "godzilla_pro-1.16.json").read_text(encoding="utf-8"))
    assert side["ok"] and side["key"]["elf_sha1"] == G.Elf(elf).sha1 and "godzilla_pro-1.15" in side["key"]["refs"]
    assert side["entries"]["site shot_dispatch"]["value"] == "0xd1a9c"
    # the app sees it: a profile marked as never run
    p = MP.profile_for_card("godzilla_pro", "1.16.0")
    assert p is not None and p.proven is False and p.shots
    # a second look is the cached port; a stale key derives it again
    mtime = os.path.getmtime(r.path)
    assert D.ensure_port(elf, "godzilla_pro", "1.16.0", workers=1).path == r.path
    assert os.path.getmtime(r.path) == mtime
    side["key"]["revision"] = -1
    (cache / "godzilla_pro-1.16.json").write_text(json.dumps(side), encoding="utf-8")
    assert D.ensure_port(elf, "godzilla_pro", "1.16.0", workers=1).origin == "derived"
    assert json.loads((cache / "godzilla_pro-1.16.json").read_text(encoding="utf-8"))["key"]["revision"] == G.REVISION


@pytest.mark.slow
def test_a_build_whose_rules_place_no_core_gets_the_frameworks(cache):
    """Star Wars ELG 1.10: no reference places its shot dispatch; the framework's switch drain gives its
    shots (its own switch names), and no other title's struct values come across."""
    elf = _elf_bytes("star_wars_elg-1.10.0.elf")
    r = D.ensure_port(elf, "star_wars_elg", "1.10.0", workers=1)
    assert r.origin == "derived" and not r.missing and not r.proven
    text = pathlib.Path(r.path).read_text(encoding="utf-8")
    assert G.check_port(text, G.Elf(elf)) == []
    assert re.search(r"^site switch_edge\s+0x", text, re.M) and re.search(r"^site hook_dispatch\s+0x", text, re.M)
    # its end of ball: the references' bus-0x34 handler, never a copied bus id
    assert re.search(r"^site ball_end\s+0x", text, re.M) and not re.search(r"^value ball_end_event", text, re.M)
    assert re.search(r"^site score_add32\s+0x00287078", text, re.M)          # the 32-bit pair from The Beatles
    assert len(re.findall(r"^switch \d+", text, re.M)) == 30 and "TROUGH" not in text.upper().split("# ----")[-1]
    for gone in ("award_message_at", "display_at", "lamp_slot_size"):     # The Beatles' struct offsets
        assert "value %s" % gone not in text
    p = MP.profile_for_card("star_wars_elg", "1.10.0")
    assert p is not None and len(p.switch_shots) == 30 and p.example_start_shot in p.switch_shots
    assert "award-screen" not in p.runtime_can and "messages" not in p.runtime_can


@pytest.mark.slow
def test_a_build_without_its_core_gets_no_port(cache, monkeypatch):
    """With no switch drain to fall back on (a build of a framework the app does not know), a build
    whose rules place no shot dispatch gets no port."""
    from pinball_decryptor.plugins.stern import portswitch
    monkeypatch.setattr(portswitch, "drain", lambda elf, *a: None)
    elf = _elf_bytes("star_wars_elg-1.10.0.elf")
    r = D.ensure_port(elf, "star_wars_elg", "1.10.0", workers=1)
    assert r.path == "" and r.origin == "" and "its shot dispatch" in r.missing
    assert not (cache / "star_wars_elg-1.10.port").exists() and (cache / "star_wars_elg-1.10.draft").exists()
    assert ("star_wars_elg", "1.10") not in MR.ports()
    # the draft still carries what was found: the 32-bit scoring pair from The Beatles
    draft = (cache / "star_wars_elg-1.10.draft").read_text(encoding="utf-8")
    assert re.search(r"^site score_add32\s+0x00287078", draft, re.M)
    assert D.ensure_port(elf, "star_wars_elg", "1.10.0", workers=1).missing == r.missing


@pytest.mark.slow
def test_a_derivation_stops_when_asked(cache):
    from pinball_decryptor.plugins.stern.title_reader import Cancelled
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 2
    with pytest.raises(Cancelled):
        D.ensure_port(_elf_bytes("uncanny_xmen_le-0.98.0.elf"), "uncanny_xmen_le", "0.98.0", cancel=cancel, workers=1)
    assert not (cache / "uncanny_xmen_le-0.98.port").exists()


@pytest.mark.slow
def test_leave_one_out_reproduces_godzilla_le_116(cache):
    elf = _elf_bytes("godzilla_le-1.16.0.elf")
    refs, _notes = D.references()
    others = [r for r in refs if r.name != "godzilla_le-1.16" and r.generation == "B"]
    d = D.derive(elf, "godzilla_le", "1.16.0", others, workers=1)
    want = _entries((PORTS / "godzilla_le-1.16.port").read_text(encoding="utf-8"))
    got = _entries(d["text"])
    assert d["ok"] and {k: got.get(k) for k in want} == want


@pytest.mark.slow
def test_the_shot_objects_hold_the_census_proven_bits():
    from pinball_decryptor.plugins.stern import portshots
    for elf, port in (("turtles_pro-1.59.0.elf", "turtles_pro-1.59.port"),
                      ("deadpool_pro-1.16.0.elf", "deadpool_pro-1.16.port")):
        bits, how = portshots.cpp_shots(G.Elf(_elf_path(elf)))
        proven = {mask for _name, mask in MP.read_port(str(PORTS / port))["shot"]}
        assert proven <= set(bits), (elf, how)


@pytest.mark.slow
def test_a_plain_c_title_s_shots_come_from_its_switch_handlers():
    from pinball_decryptor.plugins.stern import lampmap, portshots
    e = G.Elf(_elf_path("uncanny_xmen_le-0.98.0.elf"))
    found = portshots.c_shots(e)
    assert found["site"] == 0x116924 and found["bits"] == 64 and len(found["shots"]) >= 30
    names = portshots.c_shot_names(e, found, lampmap.find_tables(lampmap.Elf(e.b))["dev_tab"])
    assert names[0x2] == "X mansion tgt"
    beatles = portshots.c_shots(G.Elf(_elf_path("beatles-1.29.0.elf")))
    proven = {mask for _name, mask in MP.read_port(str(PORTS / "beatles-1.29.port"))["shot"]}
    assert beatles["site"] == 0x3e314 and set(beatles["shots"]) <= proven


def test_a_program_that_is_not_one_gets_no_port(cache):
    r = D.ensure_port(b"not a program", "zzz_test", "1.00.0", workers=1)
    assert r.path == "" and r.missing == ("a game program that can be read",)


def test_a_build_of_no_known_generation_is_refused_and_remembered(cache):
    r = D.ensure_port(_program([PUSH, NOP, POP]), "zzz_test", "1.00.0", workers=1)
    assert r.path == "" and "framework generation" in r.missing[0]
    side = json.loads((cache / "zzz_test-1.00.json").read_text(encoding="utf-8"))
    assert side["ok"] is False and D.ensure_port(_program([PUSH, NOP, POP]), "zzz_test", "1.00.0").missing == r.missing


# ---- odd programs, failing references, the pool, two threads ----------------------------------------
def _gen_b(extra=()):
    """A tiny generation-B program: the event bus's id bound and one end-of-ball subscriber."""
    words = [0xE35000CF, PUSH, POP, 0xE35100CF, PUSH, POP, PUSH, 0xE3A01034,
             0xE3002100, 0xE3402001, 0xEBFFFFF7, POP]
    words += [NOP] * (64 - len(words)) + [PUSH, POP] + list(extra)
    return _program(words)


def _cut(prog, **kw):
    b = bytearray(prog)
    if "phnum" in kw:
        struct.pack_into("<H", b, 0x2C, kw["phnum"])
    if "tsz" in kw:
        struct.pack_into("<I", b, 0x34 + 16, kw["tsz"])
    if "phoff" in kw:
        struct.pack_into("<I", b, 0x1C, kw["phoff"])
    return bytes(b)


@pytest.mark.parametrize("prog", [
    _gen_b()[:0x40], _gen_b()[:0x60], _gen_b()[:5], b"\x7fELF\x01",
    _cut(_gen_b(), phnum=500), _cut(_gen_b(), tsz=0x100000), _cut(_gen_b(), phoff=0xFFFFFF00)],
    ids=["cut-0x40", "cut-0x60", "cut-5", "magic-only", "phnum", "text-past-end", "phoff"])
def test_an_odd_or_cut_off_program_gets_no_port_not_an_error(cache, prog):
    with pytest.raises(G.PortgenError):
        G.Elf(prog)
    r = D.ensure_port(prog, "zzz_test", "1.00.0", workers=1)
    assert r.path == "" and r.missing == ("a game program that can be read",)


def test_the_pool_drafts_what_this_process_drafts(cache):
    refs = [r for r in D.references()[0] if r.generation == "B"]
    assert len(refs) > 1
    here = D.derive(_gen_b(), "zzz_test", "1.00.0", refs, workers=1)
    pool = D.derive(_gen_b(), "zzz_test", "1.00.0", refs, workers=2)
    assert here["ran"] == "in-process" and pool["ran"] == "pool"
    assert pool["text"] == here["text"] and pool["errors"] == here["errors"] == {}
    r = D.ensure_port(_gen_b(), "zzz_test", "1.00.0", workers=2)
    assert r.path == "" and "its tick" in r.missing
    assert json.loads((cache / "zzz_test-1.00.json").read_text(encoding="utf-8"))["ran"] == "pool"


def test_a_pool_that_cannot_start_drafts_here(cache, monkeypatch):
    import concurrent.futures

    def broken(*a, **k):
        raise OSError("no processes here")
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", broken)
    refs = [r for r in D.references()[0] if r.generation == "B"]
    d = D.derive(_gen_b(), "zzz_test", "1.00.0", refs, workers=2)
    assert d["ran"] == "in-process" and len(d["drafts"]) == len(refs)


def test_a_pool_derivation_stops_when_asked(cache):
    from pinball_decryptor.plugins.stern.title_reader import Cancelled
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 2           # the two checks before drafting pass; the first draft stops it
    with pytest.raises(Cancelled):
        D.ensure_port(_gen_b(), "zzz_test", "1.00.0", cancel=cancel, workers=2)
    assert not (cache / "zzz_test-1.00.json").exists() and not (cache / "zzz_test-1.00.port").exists()


def test_a_reference_that_fails_is_left_out_and_nothing_is_remembered(cache, monkeypatch):
    real = G.apply_recipe

    def flaky(recipe, text, tgt, *a, **k):
        if k.get("port_name") == "jaws_le-1.02.port":
            raise TypeError("%x format: an integer is required, not NoneType")
        return real(recipe, text, tgt, *a, **k)
    monkeypatch.setattr(G, "apply_recipe", flaky)
    refs = [r for r in D.references()[0] if r.generation == "B"]
    d = D.derive(_gen_b(), "zzz_test", "1.00.0", refs, workers=1)
    assert list(d["errors"]) == ["jaws_le-1.02"] and "jaws_le-1.02" not in d["drafts"]
    assert len(d["drafts"]) == len(refs) - 1 and any("Jaws" in n and "left out" in n for n in d["notes"])
    # a failure that may be the reference's is not remembered for the build: the next read tries again
    r = D.ensure_port(_gen_b(), "zzz_test", "1.00.0", workers=1)
    assert r.path == "" and not (cache / "zzz_test-1.00.json").exists()


def test_a_derivation_that_cannot_write_is_no_port_not_an_error(cache, monkeypatch):
    def full(path, text):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(D, "_write", full)
    r = D.ensure_port(_gen_b(), "zzz_test", "1.00.0", workers=1)
    assert r.path == "" and r.missing == ("a port that could be derived",) and "No space" in r.notes[0]


def test_an_in_process_draft_never_shares_its_program(cache):
    """Two derivations on two threads each draft their own program: the in-process path hands
    the program to each draft and never puts it in the worker global."""
    import threading
    refs = [r for r in D.references()[0] if r.generation == "B"]
    out, errs = {}, []

    def run(name, prog):
        try:
            out[name] = D.derive(prog, name, "1.00.0", refs, workers=1)
        except Exception as e:          # noqa: BLE001
            errs.append(e)
    progs = {"zzz_a": _gen_b(), "zzz_b": _gen_b(extra=[PUSH, NOP, POP] * 50)}
    ts = [threading.Thread(target=run, args=kv) for kv in progs.items()]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs and D._WORKER == {}
    for name, prog in progs.items():
        assert out[name]["errors"] == {} and ("program sha1 %s" % G.Elf(prog).sha1) in out[name]["text"]


@pytest.mark.slow
def test_two_threads_derive_two_builds_each_from_its_own_program(cache):
    import threading
    builds = [("godzilla_pro", "1.16.0", _elf_bytes("godzilla_pro-1.16.0.elf")),
              ("king_kong_le", "0.97.0", _elf_bytes("king_kong_le-0.97.0.elf"))]
    got, errs = {}, []

    def run(game, ver, elf):
        try:
            got[game] = D.ensure_port(elf, game, ver, workers=1)
        except Exception as e:          # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=run, args=b) for b in builds]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    for game, _ver, elf in builds:
        r = got[game]
        assert r.origin == "derived" and not r.missing, (game, r)
        assert G.check_port(pathlib.Path(r.path).read_text(encoding="utf-8"), G.Elf(elf)) == []


@pytest.mark.slow
def test_a_real_program_cut_short_gets_no_port_not_an_error(cache):
    real = _elf_bytes("godzilla_le-1.16.0.elf")
    for prog in (real[:0x40], real[:0x100], real[:len(real) // 3]):
        r = D.ensure_port(prog, "zzz_test", "1.00.0", workers=1)
        assert r.path == "" and r.missing == ("a game program that can be read",)
    # the bus stub followed by half of a real program's code: every reference drafts it (the
    # sites a caller's branch points past the code at are refused) without an error
    e = G.Elf(real)
    half = _gen_b(extra=e.words[:len(e.words) // 2])
    d = D.derive(half, "zzz_test", "1.00.0", [r for r in D.references()[0] if r.generation == "B"], workers=1)
    assert d["errors"] == {}
    r = D.ensure_port(half, "zzz_test", "1.00.0", workers=1)
    assert r.origin in ("", "derived")
