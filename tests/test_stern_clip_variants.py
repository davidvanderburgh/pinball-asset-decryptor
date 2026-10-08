"""PAD-446: clips that play one of several at random (:mod:`.clip_variants`).

The Video tab gives a slot of the in-game video bank more clips than its own; a Write adds
each extra clip to the bank under a name of its own and puts ``clips.cfg`` beside the mode
runtime, which swaps the game's ask for a random one (pad_mode_runtime.c "clip variants").
These pin the module (which slots can vary, the table, the bank), the engine's build of a
project whose only change of that kind is its random clips (no mode, no preview switch) and of
one that has modes as well, and - where a host C compiler is - the runtime's own table reader
and pick, compiled out of pad_mode_runtime.c. Desk only: no card, no emulator.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import video_bank as VB
from tests.test_stern_video_bank import synthetic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
GZ = MP.GODZILLA_PRO_1_15


def _project(tmp_path, variants, rows, prof=GZ):
    """A project folder: video/manifest.txt naming each slot's card path, and the sidecar."""
    project = tmp_path / "project"
    (project / "video").mkdir(parents=True)
    lines = ["# output\tcard path\tbytes"]
    for name, card in rows:
        (project / "video" / name).write_bytes(b"stock " + name.encode())
        lines.append("%s\t/%s\t100" % (name, card))
    (project / "video" / "manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (project / ".staged_changes.json").write_text(json.dumps({CV.STAGED_KEY: variants}),
                                                  encoding="utf-8")
    return str(project)


def _clip_files(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / "mine" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"my clip " + n.encode())
        out.append(str(p))
    return out


def _fake_stage(calls=None):
    def stage(project, rel, files, log=None, cancel=None):
        if calls is not None:
            calls.append((rel, list(files)))
        out = []
        for k, f in enumerate(files, 2):
            p = os.path.join(project, CV.CACHE_DIR, "%s__%d.mov" % (CV._safe(rel), k))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(f, "rb") as a, open(p, "wb") as b:
                b.write(b"staged " + a.read())
            out.append(p)
        return out
    return stage


@pytest.fixture
def gz_proven(monkeypatch):
    """Godzilla Pro 1.15 (the hand-written profile the engine harness builds for) taken as a
    proven title for these tests; the real list is the 1.16 builds."""
    monkeypatch.setattr(CV, "PROVEN", CV.PROVEN | {"godzilla_pro-1.15"})


# ---- the module ----------------------------------------------------------------------------
def test_the_sidecar_is_cleaned_and_cut_to_what_the_runtime_holds():
    raw = {"video/a.mov": ["x.mp4", "", None, "y.mp4"] + ["z%d.mp4" % i for i in range(20)],
           "video/b.mov": [], "video/c.mov": "not a list", 7: ["q.mp4"]}
    got = CV.clean(raw)
    assert list(got) == ["video/a.mov"]
    assert got["video/a.mov"][:2] == ["x.mp4", "y.mp4"] and len(got["video/a.mov"]) == CV.MAX_EXTRA
    assert CV.clean(None) == {} and CV.clean([1, 2]) == {}


def test_the_runtime_table_matches_the_runtime_limits():
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    assert int(re.search(r"#define CLIPV_PICKS\s+(\d+)", src).group(1)) == CV.MAX_EXTRA + 1
    assert int(re.search(r"#define CLIPV_SLOTS\s+(\d+)", src).group(1)) == CV.MAX_SLOTS
    assert '"/usr/local/padmode/%s"' % CV.CFG_NAME in src


def test_clips_cfg_is_one_tab_separated_line_per_slot():
    slots = [CV.Slot(rel="video/a.mov", card="c", stock="Mothra_Intro", files=[],
                     names=["Mothra_Intro__PadVar2", "Mothra_Intro__PadVar3"])]
    text = CV.cfg_text(slots, only=True)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["only", "clip\tMothra_Intro\tMothra_Intro__PadVar2\tMothra_Intro__PadVar3"]
    assert "only" not in CV.cfg_text(slots, only=False).splitlines()


@pytest.mark.parametrize("key", sorted(CV.PROVEN))
def test_every_proven_title_has_a_port_the_runtime_can_hook(key):
    game, version = key.rsplit("-", 1)
    prof = MP.profile_for_card(game, version)
    assert prof is not None and CV.title_key(prof) == key
    assert CV.hook_route(MP.port_path(prof)) == "clip_play"
    assert CV.title_refusal(prof) == ""


def test_a_title_not_proven_or_unknown_is_refused_in_words():
    assert CV.title_refusal(None) == CV.NO_TITLE
    other = MP.profile_for_card("jaws_le", "1.02")
    if other is not None:
        assert "have not been tried on" in CV.title_refusal(other)


def test_only_a_clip_in_the_bank_scene_can_vary():
    bank = CV.bank_assets(GZ)
    assert bank.startswith("godzilla_pro/assets/lcd/auto_loaded/%s/scene.assets/" % GZ.bank_scene)
    assert CV.slot_refusal(GZ, bank + "2.asset/7.asset") == ""
    assert CV.slot_refusal(GZ, "/" + bank + "2.asset/7.asset") == ""
    assert CV.slot_refusal(GZ, "godzilla_pro/assets/lcd/auto_loaded/abc/scene.assets/1.asset") \
        == CV.NOT_BANK
    assert CV.slot_refusal(GZ, "") == CV.NO_MANIFEST


def test_the_offer_says_why_per_slot(tmp_path, monkeypatch, gz_proven):
    bank = CV.bank_assets(GZ)
    project = _project(tmp_path, {}, [("Intro.mov", bank + "2.asset/0.asset"),
                                      ("Attract.mov", "godzilla_pro/assets/lcd/auto_loaded/x/"
                                                      "scene.assets/1.asset")])
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: GZ)
    why, per = CV.offer(project, ["video/Intro.mov", "video/Attract.mov", "video/Gone.mov"])
    assert why == ""
    assert per == {"video/Intro.mov": "", "video/Attract.mov": CV.NOT_BANK,
                   "video/Gone.mov": CV.NO_MANIFEST}
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: None)
    assert CV.offer(project, ["video/Intro.mov"]) == (CV.NO_TITLE, {})
    monkeypatch.setenv(CV.GATE_ENV, "0")
    assert CV.GATE_ENV in CV.offer(project, ["video/Intro.mov"])[0]


def test_the_build_adds_each_clip_and_moves_no_stock_clip(tmp_path, gz_proven):
    bank_dir = CV.bank_assets(GZ)
    stock = synthetic(("Alpha", "Delta", "zeta"))
    mine = _clip_files(tmp_path, "b.mp4", "c.mp4", "d.mp4")
    project = _project(
        tmp_path, {"video/Delta.mov": mine[:2], "video/zeta.mov": mine[2:],
                   "video/Attract.mov": mine[:1]},
        [("Alpha.mov", bank_dir + "2.asset/0.asset"), ("Delta.mov", bank_dir + "2.asset/1.asset"),
         ("zeta.mov", bank_dir + "2.asset/2.asset"),
         ("Attract.mov", "godzilla_pro/assets/lcd/auto_loaded/x/scene.assets/1.asset")])
    msgs = []
    calls = []
    vb = CV.build(project, GZ, stock, str(tmp_path / "out"), only=True,
                  log=lambda m, lvl="info": msgs.append((lvl, m)), stage_fn=_fake_stage(calls))
    assert [s.rel for s in vb.slots] == ["video/Delta.mov", "video/zeta.mov"]
    assert calls == [("video/Delta.mov", mine[:2]), ("video/zeta.mov", mine[2:])]
    assert vb.slots[0].names == ["Delta__PadVar2", "Delta__PadVar3"]
    assert vb.slots[1].names == ["zeta__PadVar2"]
    # the attract clip is not the bank's, so it is left out with the reason
    assert any(lvl == "warning" and "video/Attract.mov is left out" in m for lvl, m in msgs)
    before, after = VB.parse(stock), VB.parse(vb.bank)
    assert len(after.library.entries) == len(before.library.entries) + 3
    old = {c.name: (c.clip_id, c.path, c.size) for c in before.library.entries}
    new = {c.name: (c.clip_id, c.path, c.size) for c in after.library.entries}
    assert all(new[n] == v for n, v in old.items())
    # each added clip is a new file at the path its bank entry names, with its own size
    for card, dst in vb.new:
        name = next(n for n, (_i, path, _z) in new.items() if bank_dir + path == card)
        assert new[name][2] == os.path.getsize(dst)
        assert open(dst, "rb").read().startswith(b"staged my clip")
    assert len({c for c, _d in vb.new}) == 3
    cfg = open(vb.cfg, encoding="utf-8").read().splitlines()
    assert cfg[1:] == ["only", "clip\tDelta\tDelta__PadVar2\tDelta__PadVar3", "clip\tzeta\tzeta__PadVar2"]
    assert vb.lines[0].startswith("video/Delta.mov plays one of 3 clips at random (b.mp4, c.mp4)")


def test_a_card_that_already_has_random_clips_is_refused(tmp_path, gz_proven):
    bank_dir = CV.bank_assets(GZ)
    stock, _info = VB.add_clip(synthetic(("Alpha", "Delta")), "Delta__PadVar2", 10)
    project = _project(tmp_path, {"video/Delta.mov": _clip_files(tmp_path, "b.mp4")},
                       [("Delta.mov", bank_dir + "2.asset/1.asset")])
    with pytest.raises(CV.VariantError, match="already has random clips from an earlier build"):
        CV.build(project, GZ, stock, str(tmp_path / "out"), only=True, stage_fn=_fake_stage())


def test_relink_repoints_the_random_clips_too(tmp_path):
    """A project moved to another PC (Project > Relink moved files...): the random clips are paths on
    the old PC too, and are found and re-pointed with the replacements."""
    from pinball_decryptor.core import relink
    new = tmp_path / "here" / "takes"
    new.mkdir(parents=True)
    for n in ("take2.mp4", "take3.mp4"):
        (new / n).write_bytes(b"x")
    staged = {"video": {"video/A.mov": r"Z:\old\takes\take2.mp4"},
              CV.STAGED_KEY: {"video/B.mov": [r"Z:\old\takes\take2.mp4", r"Z:\old\takes\take3.mp4"]}}
    assert set(relink.missing_sources(staged)) == {r"Z:\old\takes\take2.mp4", r"Z:\old\takes\take3.mp4"}
    result = relink.plan(staged, str(tmp_path / "here"))
    data, n_slots, n_files = relink.apply_plan(staged, result["found"])
    assert data[CV.STAGED_KEY]["video/B.mov"] == [str(new / "take2.mp4"), str(new / "take3.mp4")]
    assert data["video"]["video/A.mov"] == str(new / "take2.mp4")
    assert (n_slots, n_files) == (2, 2)


def test_a_random_clip_that_is_gone_is_left_out_not_the_build(tmp_path, gz_proven):
    bank_dir = CV.bank_assets(GZ)
    here = _clip_files(tmp_path, "b.mp4")
    project = _project(tmp_path, {"video/Delta.mov": [str(tmp_path / "gone.mp4")] + here,
                                  "video/zeta.mov": [str(tmp_path / "gone.mp4")]},
                       [("Delta.mov", bank_dir + "2.asset/1.asset"),
                        ("zeta.mov", bank_dir + "2.asset/2.asset")])
    msgs = []
    vb = CV.build(project, GZ, synthetic(("Alpha", "Delta", "zeta")), str(tmp_path / "out"), only=True,
                  log=lambda m, lvl="info": msgs.append((lvl, m)), stage_fn=_fake_stage())
    assert [(s.rel, s.files) for s in vb.slots] == [("video/Delta.mov", here)]
    assert ("warning", "Random clips: %s is not there any more, so video/Delta.mov plays without it"
            % (tmp_path / "gone.mp4")) in msgs
    assert any(lvl == "warning" and "video/zeta.mov is left out: none of its random clips is on this PC"
               in m for lvl, m in msgs)


def test_no_variants_builds_nothing(tmp_path, gz_proven):
    project = _project(tmp_path, {}, [])
    assert CV.build(project, GZ, synthetic(), str(tmp_path / "out"), only=True) is None


def test_stage_converts_each_clip_against_the_slots_pristine_clip(tmp_path, monkeypatch):
    """The slot's own length and conversion choices go to every extra clip, and a clip made
    from the same file with the same settings is kept."""
    from pinball_decryptor.core import video_slots as VS
    from pinball_decryptor.core import video as V
    project = tmp_path / "project"
    (project / "video").mkdir(parents=True)
    (project / "video" / "Delta.mov").write_bytes(b"x" * 50)
    (project / ".staged_changes.json").write_text(json.dumps({
        "video_length_slots": {"video/Delta.mov": "full"}, "video_no_conversion": True,
        "video_asis_slots": {"video/Delta.mov": False}, "video_best_quality": True}))
    info = V.VideoInfo("Delta.mov", duration=6.0, width=1360, height=768, fps=30.0, vcodec="h264")
    monkeypatch.setattr(V, "detect_video_info", lambda p: info)
    monkeypatch.setattr(VS, "_clip_bitrate", lambda p: 4e6)
    seen = []

    def fake_stage(slot, src, trim_to_length=False, no_conversion=False, cancel_cb=None,
                   match_bitrate=None, best_quality=False, **k):
        seen.append((slot.rel_path, src, trim_to_length, no_conversion, match_bitrate, best_quality))
        with open(slot.abs_path, "wb") as f:
            f.write(b"made from " + os.path.basename(src).encode())
        return True, "re-encoded"
    monkeypatch.setattr(VS, "stage_replacement", fake_stage)
    mine = _clip_files(tmp_path, "b.mp4", "c.mp4")
    out = CV.stage(str(project), "video/Delta.mov", mine)
    assert [os.path.basename(p) for p in out] == ["video__Delta.mov__2.mov", "video__Delta.mov__3.mov"]
    assert seen == [("video/Delta.mov#2", mine[0], False, False, 4e6, True),
                    ("video/Delta.mov#3", mine[1], False, False, 4e6, True)]
    assert open(out[1], "rb").read() == b"made from c.mp4"
    again = CV.stage(str(project), "video/Delta.mov", mine)
    assert again == out and len(seen) == 2                # kept, not made again
    os.utime(mine[0], ns=(1, 1))
    CV.stage(str(project), "video/Delta.mov", mine)
    assert len(seen) == 3 and seen[-1][1] == mine[0]       # a changed file is made again


def test_stage_names_the_clip_that_could_not_be_made(tmp_path, monkeypatch):
    from pinball_decryptor.core import video_slots as VS
    from pinball_decryptor.core import video as V
    project = tmp_path / "project"
    (project / "video").mkdir(parents=True)
    (project / "video" / "Delta.mov").write_bytes(b"x")
    monkeypatch.setattr(V, "detect_video_info", lambda p: V.VideoInfo(p, duration=1.0))
    monkeypatch.setattr(VS, "_clip_bitrate", lambda p: None)
    monkeypatch.setattr(VS, "stage_replacement", lambda *a, **k: (False, "ffmpeg said no"))
    with pytest.raises(CV.VariantError, match=r"random clip 2 \(b.mp4\).*ffmpeg said no"):
        CV.stage(str(project), "video/Delta.mov", _clip_files(tmp_path, "b.mp4"))
    with pytest.raises(CV.VariantError, match="is not there any more"):
        CV.stage(str(project), "video/Delta.mov", [str(tmp_path / "gone.mp4")])


def test_the_space_preflight_counts_each_random_clip_at_its_bound(tmp_path):
    """Each extra clip whole at the larger of its own size and its length at the slot's stock
    rate (Best quality's peak when it is on), plus its container - before anything is made."""
    from pinball_decryptor.core import video as V
    from pinball_decryptor.plugins.stern import engine
    mine = _clip_files(tmp_path, "b.mp4", "c.mp4")
    with open(mine[1], "wb") as f:
        f.write(b"x" * 3_000_000)                      # a big file: its own size wins
    project = _project(tmp_path, {"video/Delta.mov": mine}, [("Delta.mov", "c")])
    info = {mine[0]: V.VideoInfo(mine[0], duration=8.0), mine[1]: V.VideoInfo(mine[1], duration=1.0),
            os.path.join(project, "video", "Delta.mov"):
                V.VideoInfo("Delta.mov", width=1360, height=768, fps=30.0, duration=8.0)}
    probe = lambda p: info.get(p)                      # noqa: E731
    got = CV.size_bound(project, probe=probe, rate=lambda p: 4e6)
    assert got == 8 * 4_000_000 // 8 + 3_000_000 + 2 * CV.CONTAINER_BYTES
    side = json.loads(open(os.path.join(project, ".staged_changes.json")).read())
    side["video_best_quality"] = True
    with open(os.path.join(project, ".staged_changes.json"), "w") as f:
        json.dump(side, f)
    peak = CV.BEST_PEAK_BPP * 1360 * 768 * 30
    got = CV.size_bound(project, probe=probe, rate=lambda p: 4e6)
    assert got == int(8 * peak / 8) + 3_000_000 + 2 * CV.CONTAINER_BYTES
    assert CV.size_bound(project, variants={}, probe=probe) == 0
    # the engine's pre-flight adds it to what it counts for the files made after the encode
    real = CV.size_bound
    try:
        CV.size_bound = lambda project, variants=None, **k: 12345
        assert engine._unsized_bytes(project, [], [], (), variants={"video/Delta.mov": mine}) == 12345
        assert engine._unsized_bytes(project, [], [], ()) == 0
    finally:
        CV.size_bound = real


def test_the_write_tab_lists_each_slot_with_random_clips(tmp_path):
    from pinball_decryptor.webui import write_scan
    project = _project(tmp_path, {"video/Delta.mov": ["a.mp4", "b.mp4"]}, [])

    class Stern:
        key = "stern"

    class Jjp:
        key = "jjp"
    assert write_scan.variant_rows(Stern(), project) == [
        ("video/Delta.mov  —  one of 3 clips at random", "mov", "Pending (random clips)",
         "pending")]
    assert write_scan.variant_rows(Jjp(), project) == []


# ---- the engine ----------------------------------------------------------------------------
pytest.importorskip("numpy")


def _variant_card(monkeypatch, tmp_path, keep_modes=False):
    """test_stern_mode_write_engine's card with a REAL (synthetic) bank, its project's modes
    taken away unless *keep_modes*, and one bank slot set to three random clips."""
    from tests.test_stern_mode_write_engine import _mode_card
    card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path, with_sound=False)
    card.data["bank"] = synthetic(("Alpha", "Delta", "zeta"))
    from tests.test_stern_sidx_append import _build as _manifest
    card.data["sidx"] = _manifest([(card.rel[k], len(card.data[k]))
                                   for k in ("img", "fw", "hud", "bank")])
    for k in ("bank", "sidx"):
        card.nodes[k].update(size=len(card.data[k]), _data=card.data[k])
    if not keep_modes:
        shutil.rmtree(MP.modes_dir(project))
    bank_dir = CV.bank_assets(GZ)
    os.makedirs(os.path.join(project, "video"), exist_ok=True)
    with open(os.path.join(project, "video", "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\nDelta.mov\t/%s2.asset/1.asset\t100\n" % bank_dir)
    with open(os.path.join(project, "video", "Delta.mov"), "wb") as f:
        f.write(b"stock")
    # the clip as extracted: the slot itself is not replaced, only given random clips
    import hashlib
    with open(os.path.join(project, ".checksums.md5"), "a", encoding="utf-8") as f:
        f.write("video/Delta.mov\t%s\n" % hashlib.md5(b"stock").hexdigest())
    mine = _clip_files(tmp_path, "b.mp4", "c.mp4")
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump({CV.STAGED_KEY: {"video/Delta.mov": mine}}, f)
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: GZ)
    monkeypatch.setattr(CV, "stage", _fake_stage())
    monkeypatch.delenv(CV.GATE_ENV, raising=False)
    from pinball_decryptor.core import ext4_grow
    monkeypatch.setattr(ext4_grow, "available", lambda: (True, ""))
    return card, str(project)


def _compute(project, log, device=False):
    from pinball_decryptor.plugins.stern import engine
    return engine._compute_patches(io.BytesIO(b""), [], project, log=log, progress=None,
                                   cancel=lambda: False, dest_is_device=device)


def test_a_project_of_random_clips_only_builds_bank_clips_manifest_and_p2(monkeypatch, tmp_path,
                                                                          gz_proven):
    """No mode and the mode maker's switch OFF: the bank is rewritten, each random clip is a
    new file with a manifest record, and p2 gets the runtime, the port and clips.cfg - which
    says ``only`` - and no mode file."""
    from pinball_decryptor.plugins.stern import engine, sidx, sidx_append
    from tests.test_stern_audio_grow import SIDX_PATH, _capture, _said
    card, project = _variant_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    _w, _counts, plan, _mode, _vp = _compute(project, log)
    bank_dir = CV.bank_assets(GZ)
    rels = [r for r, _s in plan["jobs"]]
    assert rels == [card.rel["bank"], bank_dir + "2.asset/3.asset", bank_dir + "2.asset/4.asset",
                    SIDX_PATH.lstrip("/")]
    bank = VB.parse(open(plan["jobs"][0][1], "rb").read())
    assert sorted(c.name for c in bank.library.entries) == [
        "Alpha", "Delta", "Delta__PadVar2", "Delta__PadVar3", "zeta"]
    man = open(plan["jobs"][-1][1], "rb").read()
    assert sidx_append.verify(man, expect_paths=rels[:-1]) == []
    files = sidx.manifest_files(man)
    for rel, src in plan["jobs"][:-1]:
        assert files[rel] == (os.path.getsize(src), sidx.digests_file(src)[1].hex()), rel
    modes = plan["modes"]
    assert modes["names"] == [] and modes["variants"] == ["video/Delta.mov"]
    assert modes["p2"] == ["mode.so", "clips.cfg", "game.port"]
    pay = modes["payload"]
    assert pay["cfgs"] == [] and [os.path.basename(e) for e in pay["extras"]] == ["clips.cfg"]
    cfg = open(pay["extras"][0], encoding="utf-8").read().splitlines()
    assert cfg[1:] == ["only", "clip\tDelta\tDelta__PadVar2\tDelta__PadVar3"]
    assert _said(msgs, "Found 1 clip(s) that play one of several at random: video/Delta.mov")
    assert _said(msgs, "Random clips: video/Delta.mov plays one of 3 clips at random")
    assert _said(msgs, "Random clips: the SD-validation manifest gains 2 record(s)")
    assert not _said(msgs, "Found 2 mode(s)")
    engine._rmtree_grow_plan(plan)


def test_modes_and_random_clips_share_one_bank_and_one_runtime(monkeypatch, tmp_path, gz_proven,
                                                               preview_modes_on):
    from pinball_decryptor.plugins.stern import engine
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from tests.test_stern_audio_grow import SIDX_PATH, _capture

    def build(project, hud, bank, out_dir, ffmpeg=None, only=None, **_code):
        # the modes' two clips into the REAL bank, as mode_assets.build adds them
        res = MA.ModeBuild(out_dir=out_dir)
        hud_rel = "%s/%s/scene.radium" % (MA.LCD, GZ.hud_scene)
        bank_rel = "%s/%s/scene.radium" % (MA.LCD, GZ.bank_scene)
        for name in ("PadMode_kaiju_rush_Clip", "PadMode_monster_mash_Clip"):
            bank, info = VB.add_clip(bank, name, 4)
            rel = "%s/%s/scene.assets/%s" % (MA.LCD, GZ.bank_scene, info["path"])
            p = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(b"clip")
            res.files.append(rel)
            res.new_files.append(rel)
        for rel, data in ((hud_rel, hud + b"+screens"), (bank_rel, bank)):
            p = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data)
            res.files.insert(0, rel)
        for slot, (slug, spec) in enumerate(MP.list_modes(project)[0]):
            name = MA.mode_file_name(slot)
            p = os.path.join(out_dir, "padmode", name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(MP.runtime_cfg(spec, slug))
            res.mode_files.append(name)
            res.slots.append((slot, slug, spec.name))
        return res

    card, project = _variant_card(monkeypatch, tmp_path, keep_modes=True)
    monkeypatch.setattr(MA, "build", build)
    msgs, log = _capture()
    _w, _counts, plan, _mode, _vp = _compute(project, log)
    bank_dir = CV.bank_assets(GZ)
    rels = [r for r, _s in plan["jobs"]]
    assert rels.count(card.rel["bank"]) == 1
    assert rels[-1] == SIDX_PATH.lstrip("/")
    added = [r for r in rels if r.startswith(bank_dir)]
    assert added == [bank_dir + "2.asset/%d.asset" % n for n in (3, 4, 5, 6)]
    bank = VB.parse(open(dict(plan["jobs"])[card.rel["bank"]], "rb").read())
    names = {c.name for c in bank.library.entries}
    assert {"PadMode_kaiju_rush_Clip", "Delta__PadVar2", "Delta__PadVar3"} <= names
    modes = plan["modes"]
    assert len(modes["names"]) == 2 and modes["variants"] == ["video/Delta.mov"]
    assert modes["p2"] == ["mode.so", "mode.cfg", "mode1.cfg", "clips.cfg", "game.port"]
    cfg = open(modes["payload"]["extras"][0], encoding="utf-8").read().splitlines()
    assert "only" not in cfg                     # a card WITH modes keeps the score gate
    engine._rmtree_grow_plan(plan)


def test_random_clips_are_left_out_of_a_direct_sd_write_with_the_reason(monkeypatch, tmp_path,
                                                                       gz_proven):
    from pinball_decryptor.plugins.stern import engine
    from tests.test_stern_audio_grow import _capture, _said
    _card, project = _variant_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    with pytest.raises(engine.NothingToWrite):
        _compute(project, log, device=True)
    assert _said(msgs, "Random clips: 1 clip(s) set to play one of several at random are left "
                       "out of this build: a direct-SD write cannot add files")


def test_the_install_says_random_clips_not_modes(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_audio_grow import _capture, _said
    monkeypatch.setattr(MW, "install_p2", lambda *a, **k: "ok")
    msgs, log = _capture()
    info = {"names": [], "variants": ["video/Delta.mov"], "added": ["a/2.asset/3.asset"],
            "rewritten": ["a/scene.radium"], "port": "godzilla_pro-1.16.port",
            "p2": ["mode.so", "clips.cfg", "game.port"], "payload": {}, "p2_epoch": 0}
    rec, ok = engine._install_modes(str(tmp_path / "card.raw"), info, 3, 3, log)
    assert ok and rec["variants"] == ["video/Delta.mov"]
    assert _said(msgs, "Random clips: added a/2.asset/3.asset")
    assert _said(msgs, "Random clips: 1 clip(s) on the card play one of several at random")
    assert not _said(msgs, "mode(s) on the card")
    msgs2, log2 = _capture()
    engine._install_modes(str(tmp_path / "card.raw"), info, 2, 3, log2)
    assert _said(msgs2, "Random clips: not every file reached the card")


def test_a_card_of_random_clips_only_keeps_insider_connected_out_of_the_log(tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MPj
    from pinball_decryptor.plugins.stern import mode_write as MW

    class Ex:
        def to_exec_path(self, p):
            return "/x/" + os.path.basename(p)

        def run(self, cmd, timeout=0):
            return "[mode] installed clips.cfg, game.port, mode.so into /usr/local/padmode\n"
    pay = {"so": "a/mode.so", "cfgs": [], "port": "a/game.port", "extras": ["a/clips.cfg"]}
    said = []
    MW.install_p2("C:/b/card.raw", pay, 1, lambda m, lvl="info": said.append(m), executor=Ex(),
                  modes=False)
    assert said == ["Random clips: [mode] installed clips.cfg, game.port, mode.so into "
                    "/usr/local/padmode"]
    said.clear()
    MW.install_p2("C:/b/card.raw", pay, 1, lambda m, lvl="info": said.append(m), executor=Ex())
    assert said[-1] == "Modes: %s" % MPj.INSIDER_NOTE


def test_the_completion_summary_names_the_random_clips():
    from pinball_decryptor.plugins.stern import pipeline
    one = {"names": [], "variants": ["video/a.mov"]}
    assert pipeline._write_summary_with_modes((0, 0, 0, 0), one) == \
        "1 clip(s) that play one of several at random"
    assert pipeline._write_summary_with_modes((0, 2, 0, 0), one) == \
        "2 video(s) and 1 clip(s) that play one of several at random"
    both = {"names": ["KAIJU RUSH"], "variants": ["video/a.mov", "video/b.mov"]}
    assert pipeline._write_summary_with_modes((0, 0, 0, 0), both) == \
        "1 mode(s) (KAIJU RUSH) and 2 clip(s) that play one of several at random"


# ---- the runtime's own reader and pick, compiled out of pad_mode_runtime.c ------------------
_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#define CLOCK_MONOTONIC 1
static void say(const char *fmt, ...) { (void)fmt; }
static int str_eq(const char *a, const char *b) { return a && b && !strcmp(a, b); }
long pm_read_file(const char *path, char *buf, unsigned long cap)
{
    long n, tot = 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    while ((unsigned long)tot < cap && (n = read(fd, buf + tot, cap - (unsigned long)tot)) > 0) tot += n;
    close(fd);
    return tot;
}
@DEFINES@
@FUNCS@
int main(int argc, char **argv)
{
    unsigned i, k, n = (unsigned)atoi(argv[2]);
    CLIPV_FILES_0 = argv[1];
    if (!clipv_read()) { printf("none\n"); return 0; }
    printf("only=%d slots=%u dropped=%d\n", clipv_only, n_clipv, clipv_dropped);
    for (i = 0; i < n_clipv; i++) {
        printf("slot %s", clipv[i].name[0]);
        for (k = 1; k < clipv[i].n; k++) printf(" %s", clipv[i].name[k]);
        printf("\n");
    }
    if (n_clipv && n) {
        struct clipv *v = clipv_find(clipv[0].name[0]);
        printf("picks");
        for (i = 0; i < n; i++) { k = clipv_pick(v); v->last = k; printf(" %u", k); }
        printf("\n");
    }
    return 0;
}
"""


def _c_function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


@pytest.fixture(scope="module")
def clipv_reader(tmp_path_factory):
    if os.name == "nt" or sys.platform == "darwin":
        pytest.skip("the harness needs a host ELF C toolchain")
    cc = next((c for c in ("gcc", "cc", "clang") if shutil.which(c)), None)
    if not cc:
        pytest.skip("no host C compiler")
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    sec = src[src.index("/* ---- clip variants (PAD-446)"):src.index("static int clipv_read(void)")]
    defines = "\n".join(l for l in sec.splitlines() if l.startswith("#define CLIPV_"))
    struct = sec[sec.index("struct clipv {"):sec.index("};", sec.index("struct clipv {")) + 2]
    state = ("#include <stdlib.h>\n" + struct + "\nstatic const char *CLIPV_FILES_0;\n"
             "static char clipv_raw[CLIPV_FILE_MAX + 1];\nstatic struct clipv clipv[CLIPV_SLOTS];\n"
             "static unsigned n_clipv, clipv_rng;\nstatic int clipv_only, clipv_dropped;\n")
    funcs = [_c_function(src, r) for r in (r"static void clipv_line\(", r"static int clipv_read\(void\)",
                                            r"static struct clipv \*clipv_find\(",
                                            r"static unsigned clipv_rand\(void\)",
                                            r"static unsigned clipv_pick\(")]
    funcs[1] = funcs[1].replace("sizeof CLIPV_FILES / sizeof CLIPV_FILES[0]", "1") \
                       .replace("CLIPV_FILES[k]", "CLIPV_FILES_0")
    d = tmp_path_factory.mktemp("clipv")
    (d / "h.c").write_text(_HARNESS.replace("@DEFINES@", defines + "\n" + state)
                           .replace("@FUNCS@", "\n".join(funcs)))
    exe = d / "h"
    r = subprocess.run([cc, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", "-o", str(exe),
                        str(d / "h.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(text, picks=0):
        p = d / "clips.cfg"
        p.write_bytes(text.encode())
        return subprocess.run([str(exe), str(p), str(picks)], capture_output=True, text=True,
                              check=True).stdout.splitlines()
    return run


def test_the_runtime_reads_the_table_the_build_writes(clipv_reader):
    slots = [CV.Slot(rel="video/a.mov", card="c", stock="Mothra_Intro", files=[],
                     names=["Mothra_Intro__PadVar2", "Mothra_Intro__PadVar3"]),
             CV.Slot(rel="video/b.mov", card="c", stock="Gigan_Win", files=[],
                     names=["Gigan_Win__PadVar2"])]
    out = clipv_reader(CV.cfg_text(slots, only=True))
    assert out == ["only=1 slots=2 dropped=0",
                   "slot Mothra_Intro Mothra_Intro__PadVar2 Mothra_Intro__PadVar3",
                   "slot Gigan_Win Gigan_Win__PadVar2"]
    assert clipv_reader(CV.cfg_text(slots, only=False))[0] == "only=0 slots=2 dropped=0"
    # CRLF, a comment, a line with no extra clip and a stray word are all harmless
    out = clipv_reader("# x\r\nclip\tLonely\r\nhello\r\nclip\tA\tA__PadVar2\r\n")
    assert out == ["only=0 slots=1 dropped=0", "slot A A__PadVar2"]


def test_the_runtime_never_plays_the_same_clip_twice_in_a_row(clipv_reader):
    out = clipv_reader("clip\tA\tA__PadVar2\tA__PadVar3\n", picks=600)
    picks = [int(x) for x in out[-1].split()[1:]]
    assert len(picks) == 600 and set(picks) == {0, 1, 2}
    assert all(a != b for a, b in zip(picks, picks[1:]))
    two = [int(x) for x in clipv_reader("clip\tA\tA__PadVar2\n", picks=50)[-1].split()[1:]]
    assert all(a != b for a, b in zip(two, two[1:]))


def test_the_runtime_takes_no_more_than_its_table_holds(clipv_reader):
    names = "\t".join("A__PadVar%d" % k for k in range(2, 30))
    out = clipv_reader("clip\tA\t%s\n" % names)
    assert out[1].split()[1:] == ["A"] + ["A__PadVar%d" % k for k in range(2, CV.MAX_EXTRA + 2)]
    many = "".join("clip\tS%d\tS%d__PadVar2\n" % (i, i) for i in range(CV.MAX_SLOTS + 3))
    assert clipv_reader(many)[0] == "only=0 slots=%d dropped=3" % CV.MAX_SLOTS
