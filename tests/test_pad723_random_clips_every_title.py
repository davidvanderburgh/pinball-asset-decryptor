"""PAD-723: random clips on every Spike 2 title.

PAD-446 offered them on Godzilla 1.16 alone. The sweep (docs/plans/pad-723-random-clips-every-title.md)
found the game asking for its clips by name in more places than the port's video bank: other bank
scenes of the card (Venom Pro, Stranger Things Pro, The Munsters, Rush, Metallica and Iron Maiden
name the HUD as their bank), Batman 1.14's 4x3 scene whose library goes on past its Video, and
Deadpool's full-screen video layer. These pin the reader of such a scene and the routes; the bank
scene choice and the build are in tests/test_stern_clip_variants.py. Desk only.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import video_bank as VB
from tests.test_stern_video_bank import synthetic


def _scene(names=("Alpha", "Delta", "zeta")):
    """A scene like Batman's a59b98f2: its library opens with the bank's Video and goes on (here
    the count says two entries; the rest is not walked), its VideoSurface names the same clips."""
    raw = bytearray(synthetic(names))
    struct.pack_into("<Q", raw, 1, 2)
    return bytes(raw)


def test_a_scene_whose_library_goes_on_past_its_video_reads_as_a_bank():
    data = _scene()
    with pytest.raises(VB.VideoBankError, match="exactly one Video"):
        VB.parse(data)
    bank = VB.parse_scene(data)
    assert [c.name for c in bank.library.entries] == ["Alpha", "Delta", "zeta"]
    assert [c.clip_id for c in bank.surface.entries] == [c.clip_id for c in bank.library.entries]
    assert all(c.path is None for c in bank.surface.entries)
    # a stock bank still reads exactly as parse reads it
    stock = synthetic()
    assert VB.parse_scene(stock) == VB.parse(stock)


def test_a_clip_added_to_such_a_scene_goes_into_both_maps_with_a_new_id():
    data = _scene()
    grown, info = VB.add_clip(data, "Delta__PadVar2", 1234)
    again, info2 = VB.add_clip(grown, "Delta__PadVar3", 99)
    bank = VB.parse_scene(again)
    lib = {c.name: c for c in bank.library.entries}
    assert [c.name for c in bank.library.entries] == [c.name for c in bank.surface.entries] == \
        ["Alpha", "Delta", "Delta__PadVar2", "Delta__PadVar3", "zeta"]
    assert lib["Delta__PadVar2"].size == 1234 and lib["Delta__PadVar3"].size == 99
    ids = [c.clip_id for c in bank.library.entries]
    assert len(set(ids)) == len(ids) and info2["clip_id"] > info["clip_id"]
    # an id is never one the file could already hold: past every flagged u32 below the cap
    assert info["clip_id"] >= max(c.clip_id for c in VB.parse_scene(data).library.entries) + 1


def test_a_scene_naming_its_clips_twice_outside_the_library_is_refused():
    data = _scene()
    bank = VB.parse_scene(data)
    s = bank.surface
    body_at = s.count_at - (4 + 4 + 4 + 1) - (8 + len(bank.video_name)) - 4
    body_end = s.entries[-1].end + 8                      # the surface Video's marked list (empty)
    twice = data + data[body_at:body_end]
    with pytest.raises(VB.VideoBankError, match="2 VideoSurface maps"):
        VB.parse_scene(twice)


def test_every_shipped_build_but_turtles_pro_158_has_a_route():
    routes = {CV.title_key(p): CV.route_of(p) for p in MP.profiles().values()}
    assert {k for k, r in routes.items() if not r} == {"turtles_pro-1.58"}
    assert {routes[k] for k in ("deadpool_le-1.14", "deadpool_le-1.16", "deadpool_pro-1.16")} == {"layer"}
    assert routes["batman-1.14"] == routes["venom_pro-1.07"] == "surface"
    assert routes["godzilla_le-1.16"] == routes["jaws_pro-1.02"] == "clip_play"


def test_the_layer_route_varies_the_ports_bank_only():
    dp = MP.profile_for_card("deadpool_pro", "1.16")
    own = CV.bank_assets(dp) + "2.asset/3.asset"
    other = "deadpool_pro/assets/lcd/auto_loaded/x/scene.assets/1.asset"
    assert CV.slot_refusal(dp, own) == ""
    assert CV.other_scenes(dp, [other]) == set()
    assert CV.slot_refusal(dp, other, {"deadpool_pro/assets/lcd/auto_loaded/x/scene.radium":
                                       {other: "A"}}) == CV.NOT_BANK


def test_the_runtime_hooks_the_layer_and_names_the_scene_of_an_sclip():
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools",
                            "spike2_emu", "modes", "sdk", "pad_mode_runtime.c"), encoding="utf-8").read()
    arm = src[src.index("static void clipv_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'hook(fn("layer_video"), on_clipv_layer)' in arm
    assert arm.index('hook(fn("clip_play")') < arm.index("sv_hook()") < arm.index('fn("layer_video")')
    sv = src[src.index("static void on_clipv_set_video(unsigned *r)\n{"):]
    assert "v && v->scene ? clipv_scene_surface(v->scene) : clip2_surface()" in sv[:sv.index("\n}\n")]


def _clip(tmp_path, name):
    p = tmp_path / "mine" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"my clip")
    return str(p)


def test_a_demand_loaded_banks_clip_named_nowhere_else_is_marked_for_any_surface(tmp_path):
    """Iron Maiden 1.18's 60ed7e50 is demand-loaded: the runtime cannot look it up by id, so a clip
    whose name no other scene of the card has is written `*<id>` (any surface asking is its scene's);
    one that another scene names too keeps the bare id (no swap while the scene cannot be found)."""
    from tests.test_stern_clip_variants import _fake_stage, _project
    im = MP.profile_for_card("iron_maiden_le", "1.18")
    d = "iron_maiden_le/assets/lcd/demand_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.assets/"
    project = _project(tmp_path, {"video/Tunnel.mov": [_clip(tmp_path, "a.mp4")],
                                  "video/Door.mov": [_clip(tmp_path, "b.mp4")]},
                       [("Tunnel.mov", d + "2.asset/0.asset"), ("Door.mov", d + "2.asset/1.asset")])
    asked = []

    def scan(names):
        asked.append(list(names))
        return {"CyborgTunnel": 1, "EddieDoor": 2}
    vb = CV.build(project, im, b"", str(tmp_path / "out"), only=True, stage_fn=_fake_stage(),
                  read_card=lambda sc: synthetic(("CyborgTunnel", "EddieDoor")), scan_card=scan)
    assert asked == [["CyborgTunnel", "EddieDoor"]]
    cfg = [l for l in open(vb.cfg, encoding="utf-8").read().splitlines() if l.startswith("sclip")]
    assert cfg == ["sclip\t60ed7e5036b8ce09d35a3e101ea6fc1380b37d97\tEddieDoor\tEddieDoor__PadVar2",
                   "sclip\t*60ed7e5036b8ce09d35a3e101ea6fc1380b37d97\tCyborgTunnel\tCyborgTunnel__PadVar2"]
    # an auto-loaded bank is looked up by id: never scanned, never marked
    v = MP.profile_for_card("venom_pro", "1.07")
    a = "venom_pro/assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.assets/2.asset/0.asset"
    p2 = _project(tmp_path / "v", {"video/T.mov": [_clip(tmp_path, "c.mp4")]}, [("T.mov", a)])
    asked.clear()
    vb = CV.build(p2, v, b"", str(tmp_path / "out2"), only=True, stage_fn=_fake_stage(),
                  read_card=lambda sc: synthetic(("CyborgTunnel",)), scan_card=scan)
    assert asked == [] and "\tCyborgTunnel\t" in open(vb.cfg, encoding="utf-8").read()


def test_scene_counts_reads_every_scene_of_the_game():
    class Reader:
        files = {"/im/assets/lcd/a/x/scene.radium": b"..." + struct.pack("<Q", 3) + b"Cat",
                 "/im/assets/lcd/b/y/scene.radium": struct.pack("<Q", 3) + b"Cat" + struct.pack("<Q", 3) + b"Dog",
                 "/im/assets/lcd/b/y/scene.assets/1.asset": struct.pack("<Q", 3) + b"Dog",
                 "/other/assets/lcd/z/scene.radium": struct.pack("<Q", 3) + b"Dog"}

        def iter_regular_files(self, max_depth=9):
            return [(p, 0, p) for p in self.files]

        def read_file_bytes(self, node):
            return self.files[node]
    assert CV.scene_counts(Reader(), "im", ["Cat", "Dog", "Eel"]) == {"Cat": 2, "Dog": 1, "Eel": 0}


def test_a_clip_whose_game_name_has_spaces_can_vary(tmp_path):
    """Metallica 1.04's bank has "Metallica Moth into Flame v1": its random clips keep the spaces
    (clips.cfg is TAB-separated), where a mode's own clip name still has none."""
    from tests.test_stern_clip_variants import _fake_stage, _project
    with pytest.raises(VB.VideoBankError, match="no spaces"):
        VB.add_clip(synthetic(("A",)), "my clip", 10)
    with pytest.raises(VB.VideoBankError, match="no spaces"):
        VB.add_clip(synthetic(("A",)), " lead", 10, spaces=True)
    m = MP.profile_for_card("metallica_spike", "1.04")
    d = "metallica_spike/assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.assets/"
    name = "Metallica Moth into Flame v1"
    project = _project(tmp_path, {"video/Moth.mov": [_clip(tmp_path, "a.mp4")]}, [("Moth.mov", d + "2.asset/0.asset")])
    vb = CV.build(project, m, b"", str(tmp_path / "out"), only=True, stage_fn=_fake_stage(),
                  read_card=lambda sc: synthetic((name, "Road")))
    assert vb.slots[0].names == [name + "__PadVar2"]
    assert "\t%s\t%s__PadVar2" % (name, name) in open(vb.cfg, encoding="utf-8").read()
