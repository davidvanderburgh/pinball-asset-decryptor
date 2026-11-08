"""PAD-1063: the game's own expression light shows (BEN: "does the existing Stern expression lighting patterns show
up? Or is it just for user added ones?"; David: bring them in).

Led Zeppelin and Rush keep a show for each song in the game program as 40-a-second frames of the 96 blade pixels,
the speaker lights averaged from them (cab_stock). A step ``game`` of a card's show plays one of them from the game's
own memory (cabshow.cfg ``songs`` / ``songspk``); the page plays them from their frames (cabfx.js gameColour).

Emulator-proven on Led Zeppelin LE 1.22 (C:/tmp/PAD-1063/verify_game.py): the game's own show is these frames at
its 90% brightness, blades and speakers exactly, in three snapshots; a card's show stepping request 66 REMIX from 60 s
over song request 70 painted that show's frame exactly at the song's place, blades and speakers, through the song held,
stopped and played again.

What is worth failing on:
  * THE READER FINDS THE TABLE, ITS FRAMES AND THE SPEAKER GROUPS on the real program, and the frames are what the
    machine showed;
  * A GAME STEP NORMALIZES AND REACHES THE RUNTIME'S FILE with the table it needs, and a show that needs a table the
    build has not is left out;
  * THE PREVIEW PAINTS A LIGHT AS THE RUNTIME DOES: the blade's pixel, the speaker's average, dark past the end.
"""
import json
import os

import pytest

from pinball_decryptor.plugins.stern import cab_shows as CS, cab_stock as ST
from tests.test_pad646_light_shows import _node_run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
JS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "cabfx.js")
IMG_DIRS = [d for d in (os.environ.get("PAD_SPIKE2_IMG_DIR"), r"D:\Pinball\images\Stern\spike2",
                         "/mnt/d/Pinball/images/Stern/spike2") if d]
#: Led Zeppelin's speaker groups, off its ExpressionLights code (the left ring the left blade's pixel pairs, the right
#: the right's; speaker 12 the four corners)
LZ_SPEAKERS = [[2 * j, 2 * j + 1, 2 * j + 24, 2 * j + 25] for j in range(11)] + [[22, 23, 46, 47, 70, 71, 94, 95]] + \
              [[2 * j, 2 * j + 1, 2 * j + 24, 2 * j + 25] for j in range(34, 23, -1)]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _card(name):
    for d in IMG_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    pytest.skip("the card %s is not here" % name)


# ---- the model and the runtime's file ----------------------------------------------------------------------------
def test_a_game_step_keeps_its_song_its_set_and_where_it_starts():
    st = CS.norm_step({"fx": "game", "ms": 5000, "req": "66", "set": "remix", "from": -4, "blend": 99999})
    assert st["fx"] == "game" and (st["req"], st["set"], st["from"], st["blend"]) == (66, "remix", 0, 5000)
    assert CS.norm_step({"fx": "game", "set": "nonsense"})["set"] == "original"
    assert "req" not in CS.norm_step({"fx": "solid", "req": 3})          # only a game step carries them
    assert CS.game_step(63, 150000) == CS.norm_step({"fx": "game", "ms": 150000, "req": 63})
    assert CS.uses_game({"blades": [], "speakers": [CS.game_step(63, 1000)]})
    assert not CS.uses_game(CS.preset("rock"))


STOCK = {"table": 0x56952c, "pixels": 96, "speakers": [[0, 1, 24, 25], [22, 23, 46, 47, 70, 71, 94, 95]],
         "rows": [{"row": 0, "request": 67}, {"row": 1, "request": 63}]}


def test_the_runtimes_file_carries_the_table_a_game_step_needs():
    shows = CS.norm({"shows": [
        {"name": "Mine", "slot": 291, "blades": [CS.game_step(63, 9000, "remix", 1500)],
         "speakers": [{"fx": "pulse", "ms": 500}]},
        {"name": "Plain", "slot": 13, "blades": [{"fx": "solid", "ms": 500}]}]})["shows"]
    text, skipped = CS.cfg_text(shows, {291: [89], 13: [68]}, only=True, stock=STOCK)
    lines = text.splitlines()
    assert not skipped
    assert lines[1:4] == ["only", "songs 0x56952c 2 96", "songspk 0,1,24,25 22,23,46,47,70,71,94,95"]
    assert lines[4:7] == ["show 89 0 Mine", "blades game 9000 63 1 1500 0", "speakers pulse 500 0xffffff 0x000000 0 0"]
    # no game step: no table lines
    plain, _ = CS.cfg_text(shows[1:], {13: [68]}, only=False, stock=STOCK)
    assert "songs" not in plain
    # a build without the game's shows, or without that song's: the show is left out, the others stay
    for stock in (None, dict(STOCK, rows=[{"row": 0, "request": 67}])):
        text, skipped = CS.cfg_text(shows, {291: [89], 13: [68]}, only=False, stock=stock)
        assert skipped == ["Mine"] and "songs" not in text and "show 68 0 Plain" in text


def test_the_page_says_when_a_game_step_has_no_show_to_play():
    s = CS.norm_show({"name": "x", "slot": 1, "blades": [CS.game_step(99, 1000)]})
    assert CS.problems(s, {1}, None) == []                               # not read yet: nothing said
    assert any("does not have" in p for p in CS.problems(s, {1}, {63, 67}))
    assert any("keeps none" in p for p in CS.problems(s, {1}, set()))
    assert CS.problems(s, {1}, {99}) == []


def test_the_build_reads_the_table_off_the_cards_own_program(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(CS, "title_refusal", lambda prof: "")
    monkeypatch.setattr(ST, "read", lambda elf: STOCK if elf == b"ELF" else None)
    shows = [CS.norm_show({"name": "Mine", "slot": 291, "blades": [CS.game_step(63, 9000)]})]
    said = []
    result = SimpleNamespace(profile=object(), cabshow_file="", lines=[])
    MW.cabs_into(result, str(tmp_path), shows, {291: [89]}, only=True, log=lambda *a: said.append(a[0]),
                 game_elf=b"ELF")
    assert "songs 0x56952c 2 96" in _read(result.cabshow_file) and not said
    result = SimpleNamespace(profile=object(), cabshow_file="", lines=[])
    MW.cabs_into(result, str(tmp_path / "b"), shows, {291: [89]}, only=True, log=lambda *a: said.append(a[0]),
                 game_elf=b"OTHER")
    assert not result.cabshow_file and any("Mine" in w for w in said)


def test_the_runtime_paints_a_game_step_from_the_games_memory():
    rt = _read(os.path.join(SDK, "pad_mode_runtime.c"))
    assert '"meter", "game" };' in rt and "case CX_GAME: break;" in rt
    for frag in ('str_starts(s, "songs ")', 'str_starts(s, "songspk ")', "cab_src[k] = cab_src_of(x->name);",
                 "frames = *(const unsigned *)(row + (st->b ? 16 : 12));", "f = (st->rate + t) / per;",
                 "if (!maps_has((unsigned long)fr, cab_songs_px * 3u, MAP_R)) return 0;"):
        assert frag in rt, frag
    tick = rt[rt.index("static void cabs_tick(void)"):]
    assert "cab_blend(st, i ? &c->st[L][i - 1] : 0, k, t[L])" in tick[:tick.index("\n}\n")]


# ---- the preview paints as the runtime ---------------------------------------------------------------------------
def test_the_preview_paints_a_game_step_as_the_runtime_does(tmp_path):
    names = ["EXPRESSIVE LIGHTING L 1", "EXPRESSIVE LIGHTING R 96", "EXPRESSIVE LIGHTING 50", "SPEAKER 1",
             "LEFT SPEAKER 2", "SPEAKER 33", "LEFT RAMP"]
    frames = bytes((f * 7 + p * 3 + c) % 256 for f in range(4) for p in range(96) for c in range(3))
    meta = {"pixels": 96, "speakers": STOCK["speakers"], "rows": {"63": {"period": 25, "frames": 4}}}
    want_src = [0, 95, 49, -2, -3, -1, -1]
    want = []
    for t in (0, 30, 74, 99, 100):
        f = (1000 + t) // 25 - 40                      # from 1000 ms: frame 40 on; the buffer holds frames 0-3 as 40-43
        for src in want_src:
            if src == -1 or f >= 4 or (src <= -2 and -2 - src >= len(meta["speakers"])):
                want.append(0)
            elif src >= 0:
                o = f * 288 + 3 * src
                want.append(frames[o] << 16 | frames[o + 1] << 8 | frames[o + 2])
            else:
                r, g, b = ST.speaker_colour(frames[f * 288:(f + 1) * 288], meta["speakers"][-2 - src])
                want.append(r << 16 | g << 8 | b)
    js = "\n".join([
        _read(JS).replace("export ", ""),
        "const names = %s, meta = %s;" % (json.dumps(names), json.dumps(dict(meta, rows={"63": {"period": 25,
                                                                                                 "frames": 44}}))),
        "const buf = new Uint8Array(44 * 288); buf.set(Uint8Array.from(%s), 40 * 288);" % json.dumps(list(frames)),
        "const st = compileStep({ fx: 'game', ms: 5000, req: 63, set: 'remix', from: 1000, blend: 0 });",
        "const out = [names.map(srcOf).join(' ')];",
        "for (const t of [0, 30, 74, 99, 100]) for (const n of names) out.push(gameColour(st, srcOf(n), t, meta, buf));",
        "console.log(out.join('\\n'));", ""])
    got = [int(x) for x in _node_run(tmp_path, js)]
    assert got[:len(names)] == want_src
    assert got[len(names):] == want and any(want)


def test_the_page_offers_the_games_shows_and_makes_one_a_show_of_mine():
    page = _read(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs", "lights.js"))
    assert "The game's own" in page and 'call("lights.from_stock", stockPick.req, stockPick.set)' in page
    from pinball_decryptor.webui.tabs import lights as LT
    assert callable(LT.project_stock) and hasattr(LT.LightsTab, "from_stock")


# ---- the real program ---------------------------------------------------------------------------------------------
def test_led_zeppelins_own_shows_are_read_off_its_program():
    from pinball_decryptor.plugins.stern import title_reader as TR
    elf = TR.game_program(_card("led_zeppelin_le-1_22_0.Release.8G.sdcard.raw"))[2]
    got = ST.read(elf)
    assert got and got["table"] == 0x56952c and got["pixels"] == 96 and len(got["rows"]) == 20
    assert sorted(r["request"] for r in got["rows"]) == list(range(62, 82))
    assert {r["period"] for r in got["rows"]} == {25}
    assert got["speakers"] == LZ_SPEAKERS
    songs = ST.songs(got)
    assert len(songs) == 10 and max(x["ms"] for x in songs) == 20469 * 25          # one show a song, the longest 8:31
    row = {r["request"]: r["row"] for r in got["rows"]}
    # the machine's own show of request 63 at 12.125 s (emulator snapshot, at the game's 90%: 90,90,0 / 160 / 157)
    fr = ST.frames(elf, got, row[63], "original")[485 * 288:486 * 288]
    assert (fr[0:3], fr[30:33], fr[180:183]) == (bytes((101, 101, 0)), bytes((178, 178, 0)), bytes((175, 175, 0)))
    assert ST.frames(elf, got, row[73], "original") == ST.frames(elf, got, row[63], "original")   # one song, 2 requests
    assert ST.frames(elf, got, row[63], "remix") != ST.frames(elf, got, row[63], "original")


def test_a_title_without_its_own_shows_reads_none():
    from pinball_decryptor.plugins.stern import title_reader as TR
    elf = TR.game_program(_card("elvira3-1_13_0.Release.16G.sdcard.raw"))[2]
    assert ST.read(elf) is None
