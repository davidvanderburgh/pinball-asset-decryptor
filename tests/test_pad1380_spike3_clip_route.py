"""PAD-1380: the clip route on the drafted Spike 3 ports (Walking Dead Remastered LE, Star Wars 2025 LE / Pro,
Pokemon LE, and the same gap on Fallout LE and Transformers LE).

The ports placed every clip site but wrote them as comments, and named no video bank. Each port now carries the clip
lines and names the bank its play screen draws, proven on the Spike 3 rig (a mode's clip on the glass): Walking Dead
Remastered 71e39c43, Star Wars 2025 LE 3a9d7db5 (the framework's 60ed7e50 is not drawn in play on either: a clip there
played unseen), Star Wars 2025 Pro as its LE, and Pokemon, Fallout and Transformers 60ed7e50 (their only bank).
Pokemon's {test, page, float seconds} table is a timed slideshow, not its attract (its pages come from a director):
s3port.attract_lines leaves such a table out. The rig runs wedged on a build without pad_nosync.so: s3run.sh now
rebuilds a stale build. docs/plans/spike3_modes.md "PAD-1380".
"""
import importlib.util
import pathlib

from pinball_decryptor.plugins.stern import attract_items as AI
from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORTS = ROOT / "tools" / "spike2_emu" / "modes" / "sdk" / "ports" / "spike3"
CLIP_LINES = ("site dynamic_cast", "site resource_get", "site surface_state", "site surface_find",
              "site surface_set_video", "site surface_play", "site surface_stop", "site surface_duration",
              "site surface_position", "data resource_manager", "data typeinfo_resource",
              "data typeinfo_scene_player", "value scene_player_scene", "value surface_playing")
#: name -> (profile key, the bank scene, its file's md5 on the card)
PROVEN = {
    "walking_dead_remastered_le-0.92": ("walking_dead_remastered_le_0_92_spike3",
                                        "71e39c438cff72938ff0dd6dddecd582fb133415", "537bf7815a04a655b5388f11c4762664"),
    "star_wars_2025_le-0.96": ("star_wars_2025_le_0_96_spike3",
                               "3a9d7db5e2d79236f3339bf7ff6cacf80499535a", "f4eba4baa564300f00bd2a6c0b484ce7"),
    "star_wars_2025_pro-0.84": ("star_wars_2025_pro_0_84_spike3",
                               "3a9d7db5e2d79236f3339bf7ff6cacf80499535a", "4b0834ccf5aac497528a805d5f6b35a4"),
    "fallout_le-0.82": ("fallout_le_0_82_spike3",
                        "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97", "4ccd1a8c8814e7db01666271105f6cc7"),
    "transformers_mtmte_le-0.96": ("transformers_mtmte_le_0_96_spike3",
                                   "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97", "26d398bdc2be14090caf149bb4d34210"),
    "pokemon_le-0.82": ("pokemon_le_0_82_spike3",
                        "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97", "8b0ceb32002a4c661217be7019bdbb11"),
}


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _lines(name):
    return (PORTS / (name + ".port")).read_text(encoding="utf-8").splitlines()


def _carried(lines, head):
    return any(l.split()[:2] == head.split() for l in lines if not l.startswith("#"))


def test_every_drafted_port_carries_the_clip_route_lines():
    for name in PROVEN:
        lines = _lines(name)
        missing = [h for h in CLIP_LINES if not _carried(lines, h)]
        assert not missing, (name, missing)
        # the screen finders stay a comment: they need the title's HUD measured (and co-op hooks find_node)
        for h in ("site find_node", "site find_text", "site set_text", "value node_visible_vfn"):
            assert not _carried(lines, h), (name, h)


def test_fallout_set_video_is_read_off_its_own_code():
    assert "site surface_set_video 0x009c3440 0xf0007ac3 0xf9474463" in _lines("fallout_le-0.82")


def test_proven_titles_name_their_play_bank_and_offer_clips():
    for name, (key, scene, md5) in PROVEN.items():
        lines = _lines(name)
        assert "scene video_bank           %s" % scene in lines, name
        p = MP.profiles()[key]
        assert CV.route_of(p) == "surface", name
        assert p.can("clip"), (name, p.why_not("clip"))
        assert MP.TITLE_SCENES["%s/spike3" % name] == dict(bank=md5, clip_proven=True), name


def test_attract_items_where_the_rig_put_them_on_the_glass():
    for key in ("star_wars_2025_le_0_96_spike3", "star_wars_2025_pro_0_84_spike3"):
        assert AI.title_refusal(MP.profiles()[key]) == "", key          # 47% of the glass on both
    wdr = MP.profiles()["walking_dead_remastered_le_0_92_spike3"]
    assert AI.title_refusal(wdr) == AI.NO_GLASS % wdr.label      # on its play bank an item drew in a mid-screen box
    poke = MP.profiles()["pokemon_le_0_82_spike3"]
    assert AI.port_table(poke) is None                           # a director starts its attract pages
    assert "starts its attract screens in a way" in AI.title_refusal(poke)


def test_a_timed_table_is_not_taken_for_the_attract_sequence(monkeypatch):
    S = _s3port()
    seq = {"entry": 0x3198290, "size": 24, "page_at": 8, "count": 10, "create": 0x691ea0, "sleep": 0x691f70,
           "at": 0x4c7250, "stamp": 0x110, "seconds_at": 16}
    monkeypatch.setattr(S, "attract_sequencer", lambda t, ps: seq)
    assert S.attract_lines(object(), {"proc_sleep": 0x691f70}) == []
    monkeypatch.setattr(S, "attract_sequencer", lambda t, ps: dict(seq, size=16, seconds_at=None))
    monkeypatch.setattr(S, "attract_show", lambda t, s: None)

    class _T:
        def u32(self, va):
            return 0
    assert "data  attract_table       0x03198290" in "\n".join(S.attract_lines(_T(), {"proc_sleep": 0x691f70}))


def test_s3run_rebuilds_a_stale_rig_build_and_never_runs_without_the_sync_guard():
    src = (ROOT / "tools" / "spike3_emu" / "s3run.sh").read_text(encoding="utf-8")
    body = src[src.index("# A BUILD FROM THESE SOURCES (PAD-1380)"):src.index('if [ "$BRIDGE" = 1 ]; then\n    for f in')]
    assert '"$(bash "$S/s3build.sh" --sum)"' in body and 'cat "$B/.srcsum"' in body
    assert "flock 9" in body and 'bash "$S/s3build.sh" "$B"' in body
    assert '[ -e "$B/pad_nosync.so" ] || {' in body and "exit 1" in body
