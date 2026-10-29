"""PAD-827: which clip is which - the playfield window's CLIPS list (each clip the game plays, the
switch made just before it, whether it loops) and the Video tab's When it plays column it fills."""
import json
import os
import sys

import pytest

from pinball_decryptor.plugins.stern import clip_seen as CS
from tests.test_pad444_clip_modes import GIGAN, SOLO, SHARED, OTHER, MAIN, _ready, _stub_reading
from tests.test_webui_video import _project, _row, _scan, _wait
from tests.webui_harness import web_app

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "spike2_emu"))
import clipwatch as CW  # noqa: E402

BANK = "./assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.assets/2.asset/"


def serve(t, n, frames=90, ch=0, fps=30.0):
    """padvidhost.py's serving line, as it writes it since PAD-827."""
    return ("[padvid %7.2f] ch%d serving 1360x768 %d frames (acked 0.9 ms after notice) %s%d.asset"
            "  (%.3f fps)" % (t, ch, frames, BANK, n, fps))


def watch(tmp_path, names=None):
    log = tmp_path / "padvid.log"
    log.write_text("", encoding="utf-8")
    return CW.ClipWatch(str(log), seen_path=str(tmp_path / "seen.jsonl"),
                        names=names or {BANK + "361.asset": ["video/gigan_ghidorah_vs_godzilla56.mp4",
                                                             "gigan_ghidorah_vs_godzilla56"]}), log


def append(log, *lines):
    with open(log, "a", encoding="utf-8") as f:
        f.write("".join(ln + "\n" for ln in lines))


def seen(tmp_path):
    p = tmp_path / "seen.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---- the playfield window's reading ------------------------------------------------------------
def test_a_clip_is_named_as_its_video_tab_row_and_credited_with_the_switch_made_before_it(tmp_path):
    cw, log = watch(tmp_path)
    names = {40: "RIGHT RAMP MADE", 41: "LEFT FLIPPER BUTTON", 42: "TROUGH 1", 43: "Shield Motor Open"}
    cw.feed_switches(bytes(256), names, 10.0)
    on = bytearray(256)
    on[40] = 1
    cw.feed_switches(bytes(on), names, 11.0)
    on[41] = on[42] = on[43] = 1             # a flipper, the trough, a motor: never a clip's trigger
    cw.feed_switches(bytes(on), names, 11.5)
    append(log, serve(50.0, 361))
    assert cw.poll(12.0) is True
    assert cw.dyn() == [{"name": "gigan_ghidorah_vs_godzilla56", "sw": "RIGHT RAMP MADE",
                         "loop": False, "n": 1, "now": True}]
    # the shot is used up: the clip the game plays next on its own is not credited with it
    append(log, serve(53.5, 362))
    cw.poll(13.0)
    assert cw.dyn()[0] == {"name": "2.asset/362.asset", "sw": "", "loop": False, "n": 1, "now": True}
    assert [(e["rel"], e["switch"]) for e in seen(tmp_path)] == [
        ("video/gigan_ghidorah_vs_godzilla56.mp4", "RIGHT RAMP MADE"), (None, "")]


def test_a_switch_made_long_before_a_clip_is_not_its_trigger(tmp_path):
    cw, log = watch(tmp_path)
    names = {40: "RIGHT RAMP MADE"}
    cw.feed_switches(bytes(256), names, 10.0)
    on = bytearray(256)
    on[40] = 1
    cw.feed_switches(bytes(on), names, 10.0)
    append(log, serve(50.0, 361))
    cw.poll(10.0 + CW.TRIGGER_S + 1)
    assert cw.dyn()[0]["sw"] == ""


def test_the_same_file_asked_for_again_as_it_ends_is_a_loop(tmp_path):
    cw, log = watch(tmp_path)
    # 91 frames at 30 fps: the attract loop's 3 s, asked for again and again; the first ask twice
    append(log, serve(14.28, 361, 91), serve(14.29, 361, 91), serve(17.37, 361, 91),
           serve(20.38, 361, 91), serve(23.39, 361, 91))
    cw.poll(1.0)
    assert cw.dyn() == [{"name": "gigan_ghidorah_vs_godzilla56", "sw": "", "loop": True, "n": 1,
                         "now": True}]
    assert [e.get("loop", False) for e in seen(tmp_path)] == [False, True]   # one play, one loop
    # played again later after a shot: the same row, back at the top, with the shot
    names = {40: "Left Spinner"}
    cw.feed_switches(bytes(256), names, 2.0)
    on = bytearray(256)
    on[40] = 1
    cw.feed_switches(bytes(on), names, 2.1)
    append(log, serve(80.0, 362), serve(90.0, 361, 91))
    cw.poll(3.0)
    assert [(r["name"], r["n"], r["sw"], r["loop"]) for r in cw.dyn()] == [
        ("gigan_ghidorah_vs_godzilla56", 2, "", True), ("2.asset/362.asset", 1, "Left Spinner", False)]
    cw.feed_switches(bytes(256), names, 4.0)
    cw.feed_switches(bytes(on), names, 4.1)
    append(log, serve(95.0, 362))
    cw.poll(4.5)
    assert cw.dyn()[0]["sw"] == "Left Spinner" and cw.dyn()[0]["n"] == 2   # one row, not two


def test_the_log_is_read_as_it_grows_and_again_from_the_start_after_a_new_run(tmp_path):
    cw, log = watch(tmp_path)
    with open(log, "a", encoding="utf-8") as f:
        f.write(serve(1.0, 361)[:40])          # half a line: not read until it ends
    assert cw.poll(1.0) is False
    with open(log, "a", encoding="utf-8") as f:
        f.write(serve(1.0, 361)[40:] + "\n")
    assert cw.poll(2.0) is True and len(cw.dyn()) == 1
    log.write_text(serve(0.5, 362) + "\n", encoding="utf-8")      # the next run truncated it
    assert cw.poll(3.0) is True
    assert [r["name"] for r in cw.dyn()] == ["2.asset/362.asset", "gigan_ghidorah_vs_godzilla56"]


def test_the_names_are_another_titles_are_not_used(tmp_path):
    p = tmp_path / "clip_names_0.json"
    p.write_text(json.dumps({"game": "deadpool_pro", "names": {BANK + "0.asset": ["video/a.mov", "a"]}}),
                 encoding="utf-8")
    assert CW.load_names(str(p), "godzilla_le") == {}
    assert CW.load_names(str(p), "deadpool_pro") == {BANK + "0.asset": ["video/a.mov", "a"]}


# ---- the Emulate tab's half and the project's record --------------------------------------------
def _manifest(proj, rows):
    (proj / "video").mkdir(parents=True, exist_ok=True)
    (proj / "video" / "manifest.txt").write_text(
        "# output\tcard path\tbytes\n" + "".join("%s\t%s\t1\n" % r for r in rows), encoding="utf-8")


def test_the_run_map_names_the_projects_clips_by_the_path_the_game_asks_for(tmp_path):
    proj = tmp_path / "proj"
    _manifest(proj, [("gigan_good_intro.mp4", "/godzilla_le" + BANK[1:] + "369.asset"),
                     ("other.mp4", "/godzilla_le/assets/lcd/x/scene.assets/1.asset")])
    names = tmp_path / "clip_names_2.json"
    (tmp_path / "clips_seen_2.jsonl").write_text("{}\n", encoding="utf-8")   # the last run's
    assert CS.write_names(str(names), str(proj)) == 2
    data = json.loads(names.read_text(encoding="utf-8"))
    assert data["game"] == "godzilla_le"
    assert data["names"][BANK + "369.asset"] == ["video/gigan_good_intro.mp4", "gigan_good_intro"]
    assert not (tmp_path / "clips_seen_2.jsonl").exists()
    assert CS.names_file("d", 2).endswith("clip_names_2.json")
    assert CS.seen_file("d", 2).endswith("clips_seen_2.jsonl")


def test_the_sightings_are_folded_into_the_project_as_they_come(tmp_path):
    proj = tmp_path / "proj"
    (proj / "video").mkdir(parents=True)
    path = tmp_path / "clips_seen_0.jsonl"
    m = CS.Merger(str(path), str(proj))
    assert m.poll() == 0                                   # nothing yet
    rel = "video/kotm_gigan_attack2.mp4"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"rel": rel, "switch": "RIGHT RAMP MADE"}) + "\n")
        f.write(json.dumps({"rel": rel, "switch": "RIGHT RAMP MADE"}) + "\n")
        f.write(json.dumps({"rel": None, "switch": ""}) + "\n")      # a clip no row names
        f.write('{"rel": "video/x.mp4", "sw')                          # half a line
    assert m.poll() == 3
    with open(path, "a", encoding="utf-8") as f:
        f.write('itch": "LEFT ORBIT"}\n')
        f.write(json.dumps({"rel": rel, "switch": "LEFT ORBIT"}) + "\n")
        f.write(json.dumps({"rel": rel, "loop": True}) + "\n")
    assert m.poll() == 3
    got = CS.load(str(proj))
    assert got[rel] == {"plays": 3, "after": {"RIGHT RAMP MADE": 2, "LEFT ORBIT": 1}, "loops": True}
    assert got["video/x.mp4"] == {"plays": 1, "after": {"LEFT ORBIT": 1}, "loops": False}
    assert CS.cell(got[rel]) == "After RIGHT RAMP MADE +1 · loops"
    assert CS.lines(got[rel]) == [
        "Played 3 times in the emulator.", "After RIGHT RAMP MADE: 2 times", "After LEFT ORBIT: once",
        "Plays as a loop: the game starts it again each time it ends."]
    assert CS.cell({"plays": 2, "after": {}, "loops": False}) == "No switch just before it"
    assert CS.cell({"plays": 1, "after": {}, "loops": True}) == "Loops"
    assert CS.cell(None) == "" and CS.lines(None) == []


# ---- the Video tab -------------------------------------------------------------------------------
def test_the_video_tab_shows_when_each_clip_plays_and_sorts_by_it(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER, MAIN))
    _stub_reading(monkeypatch, tmp_path, proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _ready(w)
        assert _row(st, SOLO)["seen"] == "" and _row(st, SOLO)["seen_tip"] == []
        # an Emulate run saw two of them; the tab shows it the next time it is shown
        CS.save(str(proj), {SOLO: {"plays": 2, "after": {"RIGHT RAMP MADE": 2}, "loops": False},
                            MAIN: {"plays": 1, "after": {}, "loops": True}})
        w.call("ui.select_tab", "audio")
        w.call("ui.select_tab", "video")
        st = _ready(w, lambda st: _row(st, SOLO)["seen"])
        assert _row(st, SOLO)["seen"] == "After RIGHT RAMP MADE"
        assert _row(st, SOLO)["seen_tip"][0] == "Played 2 times in the emulator."
        assert _row(st, MAIN)["seen"] == "Loops"
        assert _row(st, OTHER)["seen"] == ""
        # the callout says it in full for the row on show, and nothing for a clip not seen
        w.call("video.select", SOLO)
        st = _wait(w, lambda st: ((st.get("preview") or {}).get("seen") or {}).get("rel") == SOLO)
        assert st["preview"]["seen"]["lines"] == ["Played 2 times in the emulator.",
                                                  "After RIGHT RAMP MADE: 2 times"]
        w.call("video.select", OTHER)
        _wait(w, lambda st: (st.get("preview") or {}).get("rel") == OTHER
              and not (st.get("preview") or {}).get("seen"))
        assert w.call("video.sort", "seen") is True
        st = w.state("video")
        order = [st["rows"][i]["rel"] for i in st["view"]]
        assert order.index(SOLO) < order.index(OTHER) and order.index(MAIN) < order.index(OTHER)


def test_the_page_draws_the_column_beside_played_in():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(here, "pinball_decryptor", "webui", "static", "js", "tabs", "video.js"),
              encoding="utf-8").read()
    assert 'key: "seen", label: "When it plays"' in js and "vid-seen-cell" in js
    pf = open(os.path.join(here, "tools", "spike2_emu", "pfpage", "pf.js"), encoding="utf-8").read()
    assert 'on("clips"' in pf and "function clipsPanel" in pf


@pytest.mark.parametrize("line,want", [
    (serve(1.0, 7, 300, 1, 29.97), (1, 300, BANK + "7.asset")),
    # a log written before PAD-827: no rate, read at 30 fps
    ("[padvid   10.69] ch0 serving 1360x768 240 frames (acked 0.8 ms after notice) %s55.asset" % BANK,
     (0, 240, BANK + "55.asset")),
])
def test_the_serving_line_is_read_with_or_without_its_rate(line, want):
    m = CW.LINE.search(line)
    assert (int(m.group(2)), int(m.group(3)), m.group(4)) == want


# ---- the Emulate tab and the playfield window agree on the files ---------------------------------
def test_a_start_writes_the_map_where_the_window_reads_it_and_the_poll_folds_what_it_saw(
        tmp_path, monkeypatch):
    from tests.test_webui_emulate import _svc
    monkeypatch.setenv("PAD_SLOT", "3")
    proj = tmp_path / "proj"
    _manifest(proj, [("ebirah_vs_godzilla22.mp4", "/godzilla_le" + BANK[1:] + "120.asset")])
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor.webui.tabs import emulate as emod
        svc = _svc(w)
        monkeypatch.setattr(svc, "_assets", lambda: str(proj))
        w.run(svc._clip_names_for_run)
        ctl = emod.audio_ctl_file()
        names = os.path.join(os.path.dirname(ctl), "clip_names_3.json")
        got = CW.load_names(names, "godzilla_le")
        assert got == {BANK + "120.asset": ["video/ebirah_vs_godzilla22.mp4", "ebirah_vs_godzilla22"]}
        # the window's own reader, as playfield.clip_watch() builds it for this rig
        cw = CW.ClipWatch(str(tmp_path / "padvid.log"), names,
                          os.path.join(os.path.dirname(ctl), "clips_seen_3.jsonl"), game="godzilla_le")
        append(tmp_path / "padvid.log", serve(5.0, 120))
        cw.poll(1.0)
        assert cw.dyn()[0]["name"] == "ebirah_vs_godzilla22"
        assert svc._clip_merger.poll() == 1
        assert CS.load(str(proj)) == {"video/ebirah_vs_godzilla22.mp4":
                                      {"plays": 1, "after": {}, "loops": False}}


def test_the_playfield_window_builds_its_reader_beside_the_volume_file(monkeypatch, tmp_path):
    try:
        import playfield as pf
    except Exception:                                        # noqa: BLE001
        pytest.skip("playfield not importable")
    monkeypatch.setattr(pf, "AUDIO_CTL", str(tmp_path / "audio_ctl.json"))
    monkeypatch.setattr(pf.padpath, "logdir", lambda: str(tmp_path / "logs"))
    monkeypatch.setattr(pf.padpath, "slot", lambda: 4)
    cw = pf.clip_watch()
    assert cw.log_path == str(tmp_path / "logs" / "padvid.log")
    assert cw.names_path == str(tmp_path / "clip_names_4.json")
    assert cw.seen_path == str(tmp_path / "clips_seen_4.jsonl")
    assert cw.names_path == CS.names_file(str(tmp_path), 4) and cw.seen_path == CS.seen_file(str(tmp_path), 4)


# ---- what the game program says (clip_static) ------------------------------------------------------
from pinball_decryptor.plugins.stern import clip_static as ST  # noqa: E402


def test_a_record_table_names_each_clip_once_and_a_catalogue_is_no_table():
    recs = [(0x5000 + 8 * k, "saucer_lands_long") for k in range(6)] + [(0x5030, "Xilien_2")]
    assert [t.names for t in ST.tables(recs)] == [["saucer_lands_long", "Xilien_2"]]
    catalogue = [(0x6000 + 4 * k, "film_%d" % k) for k in range(ST.TABLE_MAX + 1)]
    assert ST.tables(catalogue) == []


def test_a_run_of_clip_name_pointers_is_a_table_and_a_second_tables_start_splits_it():
    words = [(0x1000, "fight_loop"), (0x1004, "fight_loop2"), (0x1008, "fight_loop3"),
             (0x100c, "bg1"), (0x1010, "bg2"),                       # the next mode's table
             (0x2000, "lock1"), (0x2010, "lock2"), (0x2020, "lock3"),  # records, 16 bytes each
             (0x3000, "alone")]
    got = ST.tables(words, starts=lambda va, stride: va == 0x100c)
    assert [(t.at, t.stride, t.names) for t in got] == [
        (0x1000, 4, ["fight_loop", "fight_loop2", "fight_loop3"]), (0x100c, 4, ["bg1", "bg2"]),
        (0x2000, 16, ["lock1", "lock2", "lock3"])]


def test_the_program_words_for_a_clip():
    turn = {"group": ["a", "b", "c"], "turn": True}
    assert ST.words("b", turn) == ("In turn with 2 others", [
        "The game plays it in turn with a, c: each time it comes, the next one."])
    pick = {"group": ["a", "b"], "turn": False, "loop": True}
    cell, lines = ST.words("a", pick)
    assert cell == "1 of 2 · loops" and lines[0].startswith("The game keeps it in a table with b")
    assert lines[1] == "The game asks for it as a loop: it plays again each time it ends."
    assert ST.words("x", None) == ("", [])


class _Prog:
    """Words of a made-up ARM function, for :func:`clip_static.steps_in_turn`."""
    def __init__(self, start, words):
        self.start, self.words = start, words

    def word(self, va):
        i = (va - self.start) // 4
        return self.words[i] if 0 <= i < len(self.words) else None


def test_a_loader_that_keeps_its_index_in_an_object_and_moves_it_on_steps_in_turn(monkeypatch):
    from pinball_decryptor.plugins.stern import stock_scan as S
    ebirah = [0xE92D4030,             # push {r4, r5, lr}
              0xE590107C,             # ldr r1, [r0, #0x7c]   the index
              0xE7925101,             # ldr r5, [r2, r1, lsl #2]  the table's entry
              0xE0810093,             # umull r0, r1, r3, r0  the compiler's mod 3
              0xE584307C,             # str r3, [r4, #0x7c]   moved on
              0xE8BD8030]             # pop {r4, r5, pc}
    monkeypatch.setattr(S, "function_extent", lambda prog, start, cap=0: (start + 24, set()))
    assert ST.steps_in_turn(_Prog(0x8000, ebirah), 0x8000, 3) is True
    picked = list(ebirah)
    picked[4] = 0xE5843080              # str to another field: no index kept
    assert ST.steps_in_turn(_Prog(0x8000, picked), 0x8000, 3) is False
    counted = list(ebirah)
    counted[3] = 0xE2833001             # add r3, r3, #1 and no wrap: a count (JP's amber mines)
    assert ST.steps_in_turn(_Prog(0x8000, counted), 0x8000, 3) is False
    capped = list(counted)
    capped[3] = 0xE3530003              # cmp r3, #3: wrapped at the table's length
    assert ST.steps_in_turn(_Prog(0x8000, capped), 0x8000, 3) is True


GZLE = os.path.join(os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2"),
                    "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def test_godzilla_le_ebirahs_fight_loops_take_turns_and_its_tank_clips_are_picked():
    """Against the emulator (PAD-827, stock LE 1.16, battle vs Ebirah): the fight loops played
    24 of 24 changes in table order; Advance_Tanks1, 7, 6, 9, 16 played out of order."""
    if not os.path.isfile(GZLE):
        pytest.skip("no Godzilla LE 1.16 card on this machine")
    from pinball_decryptor.plugins.stern import clip_modes as CM, video_bank as VB
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, version, part = card_title(GZLE)
    with CardImage(GZLE) as img:
        elf = img.preview(part, "/%s/game" % game, cap=256 << 20)
        bank = img.preview(part, "/%s/assets/lcd/auto_loaded/%s/scene.radium"
                           % (game, VB.GODZILLA_PRO_BANK), cap=64 << 20)
    names = [c.name for c in VB.parse(bank).library.entries]
    ctx = {}
    reading = CM.analyse(elf, names, ctx=ctx)
    facts = ST.analyse(ctx["prog"], reading.refs, game, version).facts()
    fight = facts["ebirah_vs_godzilla_fight_loop2"]
    assert fight["turn"] is True and fight["group"] == [
        "ebirah_vs_godzilla_fight_loop", "ebirah_vs_godzilla_fight_loop2", "ebirah_vs_godzilla_fight_loop3"]
    assert facts["Advance_Tanks7"]["turn"] is False and len(facts["Advance_Tanks7"]["group"]) > 2
    assert facts["EndOfBallBonus_BackgroundLoop"].get("loop") is True     # re-asked in the run too


def test_the_video_tab_shows_what_the_program_says_beside_what_the_emulator_saw(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import clip_modes as CM
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER, MAIN))
    _stub_reading(monkeypatch, tmp_path, proj)
    fake = CM.read_card

    def with_static(card, rows, cancel=None):
        got = fake(card, rows, cancel)
        got.static = {"solo": {"group": ["solo", "main"], "turn": True},
                      "main": {"group": ["solo", "main"], "turn": True, "loop": True}}
        return got
    monkeypatch.setattr(CM, "read_card", with_static)
    CS.save(str(proj), {SOLO: {"plays": 2, "after": {"RIGHT RAMP MADE": 2}, "loops": False}})
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _ready(w, lambda st: _row(st, MAIN)["seen"])
        assert _row(st, SOLO)["seen"] == "After RIGHT RAMP MADE · In turn with 1 other"
        assert _row(st, SOLO)["seen_tip"][-2:] == [
            "From the game program:", "The game plays it in turn with main: each time it comes, the next one."]
        assert _row(st, MAIN)["seen"] == "In turn with 1 other · loops"      # no emulator run saw it
        assert _row(st, MAIN)["seen_head"] == "From the game program"
        w.call("video.select", MAIN)
        st = _wait(w, lambda st: ((st.get("preview") or {}).get("seen") or {}).get("rel") == MAIN)
        pv = st["preview"]["seen"]
        assert pv["head"] == "" and pv["prog_head"] == "From the game program:" and len(pv["prog_lines"]) == 2
