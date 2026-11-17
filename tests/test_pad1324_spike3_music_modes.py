"""PAD-1324: music modes on Spike 3 cards.

A Spike 3 sound plays as long as its own record says, so each mode file is a record appended to
image.bin and the 64-bit runtime swaps the slot's record key for mode m's at the game's record lookup
(``mswap`` lines in sounds.cfg) while the operator's MUSIC MODE says m. MUSIC MODE goes on the
menu's Audio Content page, found by the page's NAME in the program's page table, in a grown copy of
the program (``game.pad``) that the modes' hook runs in the stock one's place.

The real-program tests read the Spike 3 library cards (skipped where the library is not there).
Emulator proof: docs/plans/spike3_modes.md "Music modes on Spike 3".
"""
import os
import re
import struct
import wave

import pytest

from pinball_decryptor.plugins.stern import menu_settings as M
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from pinball_decryptor.plugins.stern import spike3_music as S3MU
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = r"D:\Pinball\images\Stern\spike3"
CARDS = {
    "star_wars_elg": "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw",
    "fallout_le": "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw",
    "transformers_mtmte_le": "transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw",
    "pokemon_le": "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw",
}
_CACHE = {}


def program(key):
    if key in _CACHE:
        return _CACHE[key]
    path = os.path.join(LIBRARY, CARDS[key])
    if not os.path.isfile(path):
        pytest.skip("no Spike 3 library card for %s" % key)
    from pinball_decryptor.plugins.stern import title_reader as TR
    _CACHE[key] = TR.game_program(path)[2]
    return _CACHE[key]


# ---- the menu page, by its name --------------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["star_wars_elg", "fallout_le", "transformers_mtmte_le"])
def test_every_row_taking_spike3_program_names_its_pages(key):
    t = AdjustmentTable(program(key), wide_ok=True)
    names = M.wide_category_names(t)
    assert names[0] == "INVALID" and names[1] == "Pricing"
    assert (names[11], names[12], names[13], names[14], names[16]) == (
        "LCD/Lamp", "Audio Settings", "Audio Content", "Audio Configuration", "Attract Mode")
    assert M.wide_category(t, M.MUSIC_MODE) == 13 and M.wide_category(t, M.EDITION) == 16


def test_another_table_led_by_invalid_is_not_taken_for_the_pages():
    # ELG's 187 wire colours also start with INVALID: the pages are the run that names our pages
    t = AdjustmentTable(program("star_wars_elg"), wide_ok=True)
    assert len(M.wide_category_names(t)) == 24


def test_a_page_the_program_does_not_have_is_refused():
    t = AdjustmentTable(program("star_wars_elg"), wide_ok=True)
    t._wide_cat_names = {0: "INVALID", 1: "Pricing", 11: "LCD/Lamp"}
    with pytest.raises(M.MenuSettingError, match="no Audio Content page"):
        M.wide_category(t, M.MUSIC_MODE)


@pytest.mark.parametrize("key", ["star_wars_elg", "fallout_le"])
def test_music_mode_reads_back_on_audio_content_from_the_grown_program(key):
    class _Modes:
        count = 3

        def menu_names(self):
            return ["Standard", "Custom A", "Custom B"]
    setting, grown = S3MU.menu_program(program(key), _Modes())
    assert setting.category == 13 and setting.values == 3
    assert setting.where == "Adjustments > Machine Settings > Audio Content"
    assert setting.help == "1 = Standard, 2 = Custom A, 3 = Custom B"
    assert M.check(grown, setting) == []
    assert len(grown) > len(program(key))           # the grown page table's segment


def test_a_program_with_no_spare_setting_is_refused_with_a_sentence():
    class _Modes:
        count = 2

        def menu_names(self):
            return ["Standard", "Custom A"]
    with pytest.raises(S3MU.Spike3MusicError, match="MUSIC MODE cannot be added"):
        S3MU.menu_program(program("pokemon_le"), _Modes())


# ---- the gate -------------------------------------------------------------------------------------------------
def _prof(key):
    from pinball_decryptor.plugins.stern import mode_project as MP
    p = MP.profiles().get(key)
    if p is None:
        pytest.skip("no profile %s" % key)
    return p


def test_the_audio_tab_offers_them_on_the_proven_spike3_builds():
    for key in ("star_wars_elg_1_10_spike3", "fallout_le_0_82_spike3", "transformers_mtmte_le_0_96_spike3"):
        assert SMo.title_refusal(_prof(key)) == ""


def test_a_spike3_build_with_no_spare_setting_says_so():
    why = SMo.title_refusal(_prof("pokemon_le_0_82_spike3"))
    assert "no setting the game stopped using" in why and "MUSIC MODE" in why


def test_the_spike2_build_of_the_same_game_keeps_its_own_gate():
    # the Spike 3 ELG shares its <game>-<version> key with the Spike 2 build: the arch decides
    assert SMo.title_refusal(_prof("star_wars_elg_1_10")) == ""
    assert S3MU.is_spike3(_prof("star_wars_elg_1_10_spike3"))
    assert not S3MU.is_spike3(_prof("star_wars_elg_1_10"))


def test_sounds_in_turn_say_they_are_spike2s():
    assert "only the music modes" in SMo.title_refusal(_prof("star_wars_elg_1_10_spike3"), turns=True)


# ---- the records and sounds.cfg -------------------------------------------------------------------------------
class _Rec:
    def __init__(self, flags_lo, param, param2, channels=2):
        self.flags_lo, self.param, self.param2, self.channels = flags_lo, param, param2, channels


class _Img:
    def __init__(self, n):
        self.records = [_Rec(0x44000220, 0x02002060 ^ (1 << (20 + i)), 1000 + i) for i in range(n)]
        self.count = n


def _wav(path, secs=0.2, ch=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x01\x00" * ch * int(44100 * secs))
    return str(path)


def test_records_dedupe_one_file_per_slot_and_key_beside_the_slot(tmp_path, monkeypatch):
    a, b = _wav(tmp_path / "a.wav"), _wav(tmp_path / "b.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    modes = SMo.Modes(names=["Std", "A", "B"],
                      slots={"audio/idx0003.wav": {2: a, 3: a}, "audio/idx0005.wav": {2: b}})
    img = _Img(8)
    mswaps, news, used = S3MU.records(str(tmp_path), modes, img, taken=[(1, 2)], first_idx=10)
    assert len(news) == 2                              # a in modes 2 and 3 of slot 3 is one record
    assert [(m, s.hex()) for m, s, _o in mswaps] == [
        (2, struct.pack("<II", img.records[3].flags_lo, img.records[3].param).hex()),
        (3, struct.pack("<II", img.records[3].flags_lo, img.records[3].param).hex()),
        (2, struct.pack("<II", img.records[5].flags_lo, img.records[5].param).hex())]
    assert mswaps[0][2] == mswaps[1][2] != mswaps[2][2]
    keys = {(r.flags_lo, r.param) for r in img.records}
    for nr in news:
        assert (nr.flags_lo, nr.param) not in keys and nr.flags_lo == img.records[3].flags_lo
    assert [u["host"] for u in used] == [10, 10, 11]


def test_a_mode_files_loudness_moves_its_record(tmp_path, monkeypatch):
    a = _wav(tmp_path / "a.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    modes = SMo.Modes(names=[], slots={"audio/idx0001.wav": {2: a}}, levels={"audio/idx0001.wav": {2: -6.0}})
    _m, news, used = S3MU.records(str(tmp_path), modes, _Img(4))
    assert news[0].wav.endswith(".db-6.0.wav") and used[0]["db"] == -6.0


def test_a_slot_past_the_container_is_left_out_with_a_sentence(tmp_path, monkeypatch):
    a = _wav(tmp_path / "a.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    said = []
    modes = SMo.Modes(names=[], slots={"audio/idx0009.wav": {2: a}})
    mswaps, news, _u = S3MU.records(str(tmp_path), modes, _Img(4), log=lambda m, k="info": said.append(m))
    assert not mswaps and not news and "only 4 sounds" in said[0]


def test_sounds_cfg_has_the_setting_and_a_swap_line_per_slot_and_mode():
    modes = SMo.Modes(names=["Standard", "Custom A"], slots={"audio/idx0003.wav": {2: "x"}})
    setting = type("S", (), {"live": 0x70aff8})()
    text = S3MU.cfg_text(setting, modes, [(2, b"\x4c\x04\x02\x00\x00\x00\x10\x00", b"\x4c\x04\x02\x00\x00\x00\x00\x00")],
                         [{"rel": "audio/idx0003.wav", "slot": 3, "mode": 2, "host": 1038, "db": 0.0, "lines": 1}],
                         only=True)
    lines = text.splitlines()
    assert "only" in lines
    i = lines.index("setting\t0x0070aff8\t2")
    assert lines[i + 1] == "mswap\t2\t4c04020000001000\t4c04020000000000"
    assert not any(l.startswith("sound\t") for l in lines)      # no Spike 2 descriptors


# ---- the card: game.pad and the hook ---------------------------------------------------------------------------
def test_the_hook_runs_game_pad_in_the_stock_programs_place():
    h = S3M.HOOK_SCRIPT
    assert h.index('if [ -x "$D/game.pad" ]; then') < h.rindex('exec "$G" "$@"')
    assert 'G=$D/game.pad' in h


def test_the_plan_puts_game_pad_beside_the_runtime(tmp_path):
    so = tmp_path / "mode.so"
    so.write_bytes(b"so")
    port = tmp_path / "game.port"
    port.write_text("x")
    prog = tmp_path / S3MU.PROGRAM_NAME
    prog.write_bytes(b"\x7fELF")
    plan = S3M.Spike3ModePlan(type("R", (), {"replaced": [], "new": []})(),
                              {"so": str(so), "cfgs": [], "port": str(port)}, [], [], program=str(prog),
                              target="star_wars_elg/game")
    files = plan.files()
    assert ("game.pad", str(prog), 0o755) in files
    body = "\n".join(S3M.install_body(files, lambda p: p))
    assert "game.pad" in body                         # under pad/padmode, wiped with it on remove


def test_try_it_puts_the_program_over_the_stock_one_in_the_rig(tmp_path):
    prog = tmp_path / "game.pad"
    prog.write_bytes(b"\x7fELFgrown")
    plan = type("P", (), {"jobs": [], "program": str(prog), "target": "star_wars_elg/game"})()
    assert S3M.stage_try_it_scenes(plan, str(tmp_path / "files")) == 1
    lines = (tmp_path / "files" / S3M.GAMES_PATCH / "patches").read_text().split()
    assert lines == ["star_wars_elg/game|whole|w0|"]


def test_s3run_runs_game_pad_when_it_does_the_hooks_steps():
    src = open(os.path.join(ROOT, "tools", "spike3_emu", "s3run.sh"), encoding="utf-8").read()
    assert '[ -x "$R/games/pad/padmode/game.pad" ] && PROG=/games/pad/padmode/game.pad' in src


def test_the_engine_leaves_spike3_music_modes_to_spike3_modes():
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "engine.py"), encoding="utf-8").read()
    assert re.search(r'_sm_off = "music_modes" in _left or _is_spike3\(disk_f\)', src)
    assert "music modes" not in S3M.FAMILY_LEFT_OUT


# ---- the runtime ------------------------------------------------------------------------------------------------
def _runtime():
    return open(os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c"),
                encoding="utf-8").read()


def test_the_64_bit_runtime_swaps_the_record_while_the_setting_says_the_mode():
    src = _runtime()
    i = src.index("static int msw_lookup(pm_reg *r)\n{")
    body = src[i:src.index("\n}\n", i)]
    assert "m = sndm_mode()" in body and "msw[i].mode == m && key_is(k, msw[i].stock)" in body
    assert "LOOKUP_TAKE(r, msw[i].ours);" in body
    look = src[src.index("static void on_sound_lookup(pm_reg *r)"):]
    assert look.index("msw_lookup(r)") < look.index("sndt_lookup(r)")


def test_the_setting_moves_with_the_pies_load_address_on_64_bit_only():
    src = _runtime()
    i = src.index('str_eq(f[0], "setting")')
    blk = src[i:src.index("return;", i)]
    # PAD-1382: moved by the load address through setting_addr (a shared MORE SETTINGS value is not moved)
    assert "sndm_live = setting_addr(sndm_live);" in blk
    assert "return a + (pm_addr)game_base;" in src


def test_mswap_lines_are_read_on_64_bit_only():
    src = _runtime()
    i = src.index('str_eq(f[0], "mswap")')
    assert src.rindex("#if PM_A64", 0, i) > src.rindex("#endif", 0, i)


def test_each_slot_goes_into_its_own_folders_image_bin(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import spike3_write as W
    a = _wav(tmp_path / "a.wav")
    monkeypatch.setattr(SMo, "convert", lambda project, rel, m, src, log=None: src)
    monkeypatch.setattr(S3MU, "title_refusal", lambda prof, turns=False: "")
    monkeypatch.setattr(S3MU, "menu_program", lambda raw, modes, extra=(): (type("S", (), {"live": 0x10})(), b"prog"))
    imgs = {"game": _Img(6), "menu": _Img(4)}
    monkeypatch.setattr(W, "project_sound_dirs", lambda reader: [
        ("/fallout_le/image.bin", "game", "audio", None), ("/fallout_le/music_cat01.bin", "bank", "audio", "music_cat01"),
        ("/spike3/menu/image.bin", "menu", "audio_spike_menu", None)])
    monkeypatch.setattr(W, "read_container", lambda reader, node: (b"", imgs[node]))
    modes = SMo.Modes(names=[], slots={"audio/idx0002 - A SONG.wav": {2: a}, "audio_spike_menu/idx0001.wav": {2: a}})
    mus = S3MU.plan(str(tmp_path), modes, object(), None, b"raw", adds={"/fallout_le/image.bin": [
        W.NewRecord(a, 2, 0x44000220, 0x12345, 7)]})
    assert sorted(mus.news) == ["/fallout_le/image.bin", "/spike3/menu/image.bin"]
    assert all(len(v) == 1 for v in mus.news.values())
    assert "music_cat" not in " ".join(mus.news)
    hosts = [l.split("\t") for l in mus.cfg.splitlines() if l.startswith("mswap")]
    assert len(hosts) == 2
