"""PAD-1284: a mode's own screen, its words and its clip on a Spike 3 (64-bit ARM) game.

What the work found, held here at the desk (no card, no emulator):
- the 64-bit program's libstdc++ is the C++11 ABI (a std::string is 32 bytes) and it imports no string constructor,
  so the runtime builds the strings it hands the game (std_string); every call that takes one takes a const
  reference and copies it.
- the node finders (find_node, find_text, surface_find) return their shared_ptr through x8 (AAPCS64), not into
  their first argument; the runtime types the call to return a struct of more than 16 bytes, which C returns that way.
- the scene lookup is the game's own: resource_get(manager, &id, 0) at 0x217030 (the same four-way mode switch as
  Spike 2's), the manager at 0x712bf8, __dynamic_cast from 6IScene to 11RadiumScene, the scene at +0x38 of the scene
  player (Spike 2: +0x10; its mutex at +0x48, Spike 2's +0x18); the visibility setter is slot 42 of the Sprite
  vtable on both builds (8 bytes a slot: 0x150; strb w1, [x0, #464]).
- the video surface: set_video 0x4dcc40 (the call before play), position 0x4d77d0 and duration 0x4d7b50 (the game's
  progress read: position, duration, then the state == 2); it has no seek.
- the Spike 3 card's video bank is the Spike 2 build's file; its HUD differs from it in 3 bytes of one texture block.
Emulator proof: docs/plans/spike3_modes.md "Screens, words and clips on Spike 3 (PAD-1284)".
Spike 2's mode.so stays byte-identical (tests/test_stern_mode_runtime.py holds the prebuilt).
"""
import importlib.util
import os
import pathlib
import re
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
S3RUN = ROOT / "tools" / "spike3_emu" / "s3run.sh"
# the two Star Wars ELG 1.10 programs, where a machine keeps them (PAD-1271's scratch): the reader's real-program test
ELG2, ELG3 = r"C:\tmp\PAD-1271\elg2.game", r"C:\tmp\PAD-1271\elg3.game"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    return S


def _func(src, head):
    k = src.index(head)
    return src[k:src.index("\n}\n", k) + 3]


# ---- the runtime ----------------------------------------------------------------------------------------------
def test_a_string_is_the_cxx11_object_on_64_bit_and_the_cow_word_on_spike2():
    src = _src()
    assert "typedef pm_addr pm_str;\n#define PM_STR(s) ((void *)(s))" in src
    assert "typedef unsigned pm_str;\n#define PM_STR(s) ((void *)&(s))" in src
    body = _func(src, "static pm_str std_string(const char *s)")
    assert "o = (unsigned long *)malloc(32);" in body                  # _M_p, length, capacity, the rest
    assert "o[0] = (unsigned long)p;" in body and "o[1] = n;" in body and "o[2] = n;" in body
    # Spike 2's is the game's own constructor, as it always was
    assert '((void (*)(unsigned *, const char *, unsigned *))(unsigned long)fn("string_new"))(&str, s, &alloc);' in src


def test_the_finders_return_through_x8_on_64_bit():
    src = _src()
    assert "struct pm_found { pm_addr node, ctrl, pad; };" in src     # more than 16 bytes: returned through x8
    body = _func(src, "static void *find_with(pm_addr finder, const char *where, const char *path)")
    assert "return str ? (void *)find_x8(finder, sc, str) : 0;" in body
    assert "(out, sc, &str);" in body                                    # Spike 2: the result in r0's memory
    clip = _func(src, "static void *clip2_surface(void)")
    assert 'find_x8(fn("surface_find"), root, str)' in clip


def test_every_string_the_game_gets_is_pm_str():
    src = _src()
    a64 = re.sub(r"#else\n.*?#endif", "", src, flags=re.S)              # what the 64-bit build compiles, roughly
    assert not re.search(r"unsigned str\s*[;=]", a64.split("static pm_str std_string")[1])
    for f in ("set_text", "surface_set_video", "resource_get", "layer_video", "attract_video_play"):
        for m in re.finditer(r'\(\*\)\(([^)]*)\)\)\(unsigned long\)fn\("%s"\)\)' % f, src):
            assert "unsigned *" not in m.group(1), (f, m.group(0))
    assert '((void *(*)(void *, pm_addr, pm_addr, int))(unsigned long)fn("dynamic_cast"))' in src


def test_a_vtable_slot_is_a_pointer_wide():
    body = _func(_src(), "void pm_show(void *node, int on)")
    assert "[slot / (long)sizeof(void *)]" in body


def test_screens_and_clips_need_no_string_new_on_64_bit():
    src = _src()
    assert '#define PM_STRING_SITE (PM_A64 ? "resource_get" : "string_new")' in src
    assert 'screen_s[] = { PM_STRING_SITE, "resource_get"' in src
    assert '"surface_state", PM_STRING_SITE, "resource_get", "dynamic_cast", 0 };' in src


def test_the_coop_intro_finder_hook_reads_the_64_bit_registers():
    body = _func(_src(), "static void ci_find_seen(pm_reg *r)\n{")
    assert "r[1 - PM_A64]" in body and "r[2 - PM_A64]" in body
    assert "volatile pm_addr film_root;" in _src()


# ---- the port -------------------------------------------------------------------------------------------------
def _lines(kind):
    return [raw.split() for raw in PORT.read_text(encoding="utf-8").splitlines() if raw.split()[:1] == [kind]]


def test_elg_spike3_port_carries_the_screen_and_clip_entries():
    sites = {t[1]: t[2] for t in _lines("site")}
    assert {k: sites[k] for k in ("dynamic_cast", "resource_get", "find_node", "find_text", "set_text",
                                  "surface_find", "surface_set_video", "surface_play", "surface_stop",
                                  "surface_state", "surface_position", "surface_duration")} == {
        "dynamic_cast": "0x0010d3b0", "resource_get": "0x00217030", "find_node": "0x004e49b0",
        "find_text": "0x004e44a0", "set_text": "0x004ca610", "surface_find": "0x004e4c70",
        "surface_set_video": "0x004dcc40", "surface_play": "0x004d8f10", "surface_stop": "0x004d7430",
        "surface_state": "0x004d6010", "surface_position": "0x004d77d0", "surface_duration": "0x004d7b50"}
    assert "string_new" not in sites and "surface_seek" not in sites
    data = {t[1]: t[2] for t in _lines("data")}
    assert {k: data[k] for k in ("resource_manager", "typeinfo_resource", "typeinfo_scene_player")} == {
        "resource_manager": "0x00712bf8", "typeinfo_resource": "0x0068b850", "typeinfo_scene_player": "0x0068fb48"}
    values = {t[1]: int(t[2], 0) for t in _lines("value")}
    assert {k: values[k] for k in ("scene_player_scene", "node_visible_vfn", "surface_playing")} == {
        "scene_player_scene": 0x38, "node_visible_vfn": 0x150, "surface_playing": 2}
    scenes = {t[1]: t[2] for t in _lines("scene")}
    assert scenes == {"hud": "7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a/835949dafb924a7cfeb0ec0fe2a3a4d8696d4aea",
                      "video_bank": "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"}
    text = PORT.read_text(encoding="utf-8")
    assert "# site surface_seek     NOT PLACED: the 64-bit video surface has no seek" in text
    assert "# site string_new       NOT NEEDED:" in text
    for n in ("award_screen", "display_effect_start", "display_draw", "player_advance"):
        assert re.search(r"# not carried - no feature uses it on the Spike 2 port either \(.*\): site %s " % n, text)


# ---- the drafter ----------------------------------------------------------------------------------------------
@pytest.mark.skipif(not (os.path.isfile(ELG2) and os.path.isfile(ELG3)), reason="the Star Wars ELG programs are not here")
def test_scene_engine_reads_the_elg_program():
    S = _s3port()
    ref, tgt = S.Elf(ELG2), S.Elf(ELG3)
    S.scan(ref)
    S.scan(tgt)
    lines = S.read_port(str(SDK / "ports" / "star_wars_elg-1.10.port"))
    at = dict(find_node=0x4e49b0, find_text=0x4e44a0, set_text=0x4ca610, surface_find=0x4e4c70,
              surface_state=0x4d6010, surface_play=0x4d8f10, surface_stop=0x4d7430)
    o = S.scene_engine(ref, lines, tgt, at)
    assert o["why"] == [] and o["screens"] and o["clips"]
    assert o["site"] == {"dynamic_cast": 0x10d3b0, "resource_get": 0x217030, "surface_set_video": 0x4dcc40,
                         "surface_position": 0x4d77d0, "surface_duration": 0x4d7b50}
    assert o["data"] == {"typeinfo_resource": 0x68b850, "typeinfo_scene_player": 0x68fb48,
                         "resource_manager": 0x712bf8}
    assert o["value"] == {"scene_player_scene": 0x38, "node_visible_vfn": 0x150, "surface_playing": 2}
    assert [l.split()[1] for l in o["scene"]] == ["hud", "video_bank"]
    # without the matcher's surface sites the clips are not read, and say so
    o = S.scene_engine(ref, lines, tgt, {k: v for k, v in at.items() if k != "surface_play"})
    assert o["screens"] and not o["clips"] and "surface_play" in o["why"][-1]


def test_s3port_decodes_the_scene_words():
    S = _s3port()
    assert S._mov_reg(0xAA1903E0) == (0, 25)                      # mov x0, x25 (the manager into resource_get)
    assert S._mov_reg(0x91000000) is None
    assert S.SPRITE_TYPE == b"N6Radium6SpriteE"
    assert set(S.SCREEN_SITES) == {"find_node", "find_text", "set_text"}


# ---- the Modes tab, the Write and Try it ----------------------------------------------------------------------
def test_the_spike3_build_offers_a_screen_and_a_clip():
    from pinball_decryptor.plugins.stern import mode_project as MP, mode_write as MW
    s3 = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert s3.can("screen") and s3.can("clip"), (s3.why_not("screen"), s3.why_not("clip"))
    hud, bank = MW.scene_rels(s3)
    assert hud.endswith("7b4db7ef1fa23cfb5e115a2a2c89d46a6a2ebc4a/835949dafb924a7cfeb0ec0fe2a3a4d8696d4aea/scene.radium")
    assert bank.endswith("60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.radium")
    s = MP.TITLE_SCENES["star_wars_elg-1.10/spike3"]
    assert s["bank"] == MP.TITLE_SCENES["star_wars_elg-1.10"]["bank"]       # the same file on both cards
    assert s["screen_proven"] and s["clip_proven"]


def test_the_spike3_hud_has_its_own_profile_of_the_spike2_shape():
    from pinball_decryptor.plugins.stern import scene_write as SW
    a, b = SW.PROFILES["354935f6d901c89105d1a97edd4a559e"], SW.PROFILES["be374b87996e190f23897bd33dffbf23"]
    shape = lambda p: {k: v for k, v in p.__dict__.items() if k not in ("label", "md5")}
    assert shape(a) == shape(b)
    assert b.md5 == "be374b87996e190f23897bd33dffbf23" and "Spike 3" in b.label


def test_try_it_stages_the_scenes_and_the_clip_whole(tmp_path):
    from pinball_decryptor.plugins.stern import spike3_modes as S3M
    src = []
    for k, data in enumerate((b"hud", b"bank", b"clip")):
        p = tmp_path / ("s%d" % k)
        p.write_bytes(data)
        src.append(str(p))
    mplan = SimpleNamespace(jobs=[("/star_wars_elg/a/hud/scene.radium", src[0]), ("star_wars_elg/a/bank/scene.radium", src[1]),
                                  ("star_wars_elg/a/bank/scene.assets/2.asset/655.asset", src[2])])
    files = tmp_path / "files"
    gp = files / S3M.GAMES_PATCH
    gp.mkdir(parents=True)
    (gp / "patches").write_text("star_wars_elg/image.bin|100|h0|t0\n", encoding="utf-8")   # a sound container first
    assert S3M.stage_try_it_scenes(mplan, str(files)) == 3
    assert (gp / "patches").read_text(encoding="utf-8").splitlines() == [
        "star_wars_elg/image.bin|100|h0|t0",
        "star_wars_elg/a/hud/scene.radium|whole|w0|", "star_wars_elg/a/bank/scene.radium|whole|w1|",
        "star_wars_elg/a/bank/scene.assets/2.asset/655.asset|whole|w2|"]
    assert (gp / "w2").read_bytes() == b"clip"
    assert S3M.stage_try_it_scenes(SimpleNamespace(jobs=[]), str(tmp_path / "none")) == 0


@pytest.mark.parametrize("fmt", ["FI64", "FINF"])
def test_a_new_file_on_a_spike3_card_gets_a_manifest_record(tmp_path, monkeypatch, fmt):
    from tests.test_stern_sidx_append import _build
    from pinball_decryptor.plugins.stern import sidx, sidx_append, spike3_write as W
    stock = _build([("g/game", 100), ("g/hud/scene.radium", 50), ("g/bank/scene.radium", 40)], fmt=fmt)
    monkeypatch.setattr(sidx, "find_sidx", lambda reader: ("/spk/index/g-1_10_0.sidx", {"inode": 1}))
    reader = SimpleNamespace(read_file_bytes=lambda node: stock)
    hud, clip = tmp_path / "hud", tmp_path / "clip"
    hud.write_bytes(b"h" * 80)
    clip.write_bytes(b"c" * 30)
    said = []
    jobs = [("g/hud/scene.radium", str(hud)), ("/g/bank/scene.assets/2.asset/655.asset", str(clip))]
    new, job = W._sidx_new_files(reader, jobs, str(tmp_path / "work"), lambda m, k="info": said.append(m))
    assert new == ["g/bank/scene.assets/2.asset/655.asset"]            # the HUD has a record: refreshed in place
    assert job[0] == "spk/index/g-1_10_0.sidx"
    man = open(job[1], "rb").read()
    assert "g/bank/scene.assets/2.asset/655.asset" in sidx.parse_records(man)[0]
    assert sidx_append.verify(man, expect_paths=["g/game", "g/bank/scene.assets/2.asset/655.asset"]) == []
    assert said == ["Added 1 new file(s) to the SD-validation manifest: 655.asset."]
    # every file has a record: nothing to add, no job
    assert W._sidx_new_files(reader, jobs[:1], str(tmp_path / "w2"), None) == ([], None)


def test_s3run_puts_a_whole_file_in_the_slot_and_takes_it_away_next_run():
    sh = S3RUN.read_text(encoding="utf-8")
    k = sh.index('if [ "$cut" = whole ]; then')
    block = sh[k:sh.index("        fi\n", sh.index("continue", k)) + 11]
    assert 'cp "$GPATCH/$head" "$dst"' in block and 'echo "$rel" >> "$SD/games.patched"' in block
    assert 'case "$head" in ""|/*|*..*) continue ;; esac' in block       # nothing outside the patch folder
    assert sh.index('if [ "$cut" = whole ]; then') < sh.index('case "$cut" in ""|*[!0-9]*) continue ;; esac')


def test_try_it_says_the_screens_show():
    tryit = (ROOT / "pinball_decryptor" / "webui" / "modes_tryit.py").read_text(encoding="utf-8")
    assert "shown = S3M.stage_try_it_scenes(mplan, files)" in tryit
    assert "Their screens and clips show from the card's scenes in this run." in tryit
    assert "are not shown in Try it on a Spike 3 card" not in tryit
