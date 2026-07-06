"""Tests for core.mod_transfer — moving a user's pending mods from an old
extract folder onto a new-version extract, reconciling layout changes."""

import os

from pinball_decryptor.core import mod_transfer, staged_changes, text_manifest


def _wav(path, payload):
    """Write a fake WAV-ish file (content signature only cares about bytes)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)


def _mk_extract(root, sounds, images=None, strings=()):
    """sounds: {rel: bytes stock content}; images: {rel: bytes};
    strings: list of (path, original, replacement)."""
    images = images or {}
    for rel, data in sounds.items():
        _wav(os.path.join(root, rel.replace("/", os.sep)), data)
    for rel, data in images.items():
        _wav(os.path.join(root, rel.replace("/", os.sep)), data)
    if strings:
        text_manifest.save(root, [{"path": p, "original": o, "replacement": r}
                                  for p, o, r in strings])


def test_audio_same_index_matches(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"SOUND-A" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"SOUND-A" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["matched"]) == 1
    assert plan["audio"]["matched"][0]["tgt_rel"] == "audio/idx0001.wav"
    assert plan["totals"]["transfer"] == 1

    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)
    assert saved["audio"]["audio/idx0001.wav"] == r"C:\r\a.mp3"


def test_audio_shifted_index_is_remapped(tmp_path):
    # The sound the user modded moved from idx0001 to idx0005 in the new build.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"THE-SONG" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"a-new-intro" * 50,
                      "audio/idx0005.wav": b"THE-SONG" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\song.mp3"},
                              "audio_loop": {"audio/idx0001.wav": True}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["remapped"]) == 1
    assert plan["audio"]["remapped"][0]["tgt_rel"] == "audio/idx0005.wav"

    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)
    assert saved["audio"]["audio/idx0005.wav"] == r"C:\r\song.mp3"
    # The per-slot Loop flag follows the remapped index.
    assert saved["audio_loop"]["audio/idx0005.wav"] is True
    assert "audio/idx0001.wav" not in saved["audio"]


def test_audio_reused_index_is_flagged_not_applied(tmp_path):
    # idx0001 exists in both, but now holds a DIFFERENT sound -> must flag, not
    # silently mis-apply.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"OLD-SOUND" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"DIFFERENT" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["flagged"]) == 1
    assert not plan["audio"]["matched"] and not plan["audio"]["remapped"]

    res = mod_transfer.apply_transfer(src, tgt, plan)
    assert res["audio"] == 0
    assert staged_changes.load(tgt).get("audio") in (None, {})

    # ...unless the user opts in.
    res2 = mod_transfer.apply_transfer(src, tgt, plan, include_flagged=True)
    assert res2["audio"] == 1
    assert staged_changes.load(tgt)["audio"]["audio/idx0001.wav"] == r"C:\r\a.mp3"


def test_audio_missing_sound_is_dropped(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0009.wav": b"GONE" * 100})
    _mk_extract(tgt, {"audio/idx0001.wav": b"stays" * 100})
    staged_changes.save(src, {"audio": {"audio/idx0009.wav": r"C:\r\g.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["audio"]["dropped"]) == 1
    assert plan["totals"]["transfer"] == 0


def test_image_matches_by_relpath(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"images/logo.png": b"PNGDATA"})
    _mk_extract(tgt, {}, images={"images/logo.png": b"PNGDATA-v2"})
    staged_changes.save(src, {"image": {"images/logo.png": r"C:\r\logo.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["image"]["matched"]) == 1
    # Same name, different stock art -> flagged as content_changed (still moves).
    assert plan["image"]["matched"][0]["content_changed"] is True

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["image"]["images/logo.png"] == r"C:\r\logo.png"


def test_image_gone_is_dropped(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"images/old.png": b"X"})
    _mk_extract(tgt, {}, images={"images/other.png": b"Y"})
    staged_changes.save(src, {"image": {"images/old.png": r"C:\r\old.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert not plan["image"]["matched"]
    assert len(plan["image"]["dropped"]) == 1


def test_text_transfers_by_original(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, strings=[
        ("a/scene.radium", "HELLO", "GOODBYE"),   # edited
        ("b/scene.radium", "UNCHANGED", ""),      # not edited
        ("c/scene.radium", "REMOVED", "NEW"),     # edited, but original gone in tgt
    ])
    _mk_extract(tgt, {}, strings=[
        ("a/scene.radium", "HELLO", ""),
        ("d/scene.radium", "HELLO", ""),          # same original in a 2nd scene
        ("b/scene.radium", "UNCHANGED", ""),
    ])
    plan = mod_transfer.plan_transfer(src, tgt)
    assert len(plan["text"]["matched"]) == 1
    assert plan["text"]["matched"][0]["targets"] == 2   # applies to both scenes
    assert len(plan["text"]["dropped"]) == 1

    mod_transfer.apply_transfer(src, tgt, plan)
    rows = {(r["path"], r["original"]): r["replacement"]
            for r in text_manifest.load(tgt)}
    assert rows[("a/scene.radium", "HELLO")] == "GOODBYE"
    assert rows[("d/scene.radium", "HELLO")] == "GOODBYE"
    assert rows[("b/scene.radium", "UNCHANGED")] == ""


def test_diff_baked_mods_pairs_audio_across_naming_settings(tmp_path):
    # The modded extract used plain idx names; the stock one has the duration
    # prefix + a transcribe rename.  The idx token pairs them regardless.
    mod, stk = str(tmp_path / "modded"), str(tmp_path / "stock")
    _mk_extract(mod, {"audio/idx0001.wav": b"1987-SONG" * 100,
                      "audio/idx0002.wav": b"SAME" * 100})
    _mk_extract(stk, {"audio/00m01s000 - idx0001 - Theme.wav": b"STOCK" * 100,
                      "audio/00m02s000 - idx0002 - Hit.wav": b"SAME" * 100})

    diff = mod_transfer.diff_baked_mods(mod, stk)
    assert diff["notes"]["paired_audio"] == 2
    assert list(diff["saved"]["audio"]) == [
        "audio/00m01s000 - idx0001 - Theme.wav"]
    repl = diff["saved"]["audio"]["audio/00m01s000 - idx0001 - Theme.wav"]
    assert os.path.isabs(repl) and repl.endswith("idx0001.wav")
    assert not diff["saved"]["video"] and not diff["saved"]["image"]


def test_diff_baked_mods_music_image_and_unpaired(tmp_path):
    mod, stk = str(tmp_path / "modded"), str(tmp_path / "stock")
    _mk_extract(mod,
                {"audio/music_cat01_0001 - Battery.wav": b"NEW-MUSIC" * 100,
                 "audio/idx0031.wav": b"only-in-modded" * 10},
                images={"images/scene_textures/logo.dds": b"1987-ART",
                        "images/same.png": b"SAME"})
    _mk_extract(stk,
                {"audio/music_cat01_0001.wav": b"OLD-MUSIC" * 100},
                images={"images/scene_textures/logo.dds": b"STOCK-ART",
                        "images/same.png": b"SAME"})

    diff = mod_transfer.diff_baked_mods(mod, stk)
    assert list(diff["saved"]["audio"]) == ["audio/music_cat01_0001.wav"]
    assert diff["notes"]["paired_audio"] == 1
    assert diff["notes"]["unpaired_audio"] == 1          # idx0031 only in modded
    assert list(diff["saved"]["image"]) == ["images/scene_textures/logo.dds"]


def test_diff_baked_mods_text_positional_pairing(tmp_path):
    mod, stk = str(tmp_path / "modded"), str(tmp_path / "stock")
    # The modded extract's manifest shows the MODDED strings as "original".
    _mk_extract(mod, {}, strings=[
        ("a/scene.radium", "COWABUNGA", ""),
        ("a/scene.radium", "SAME LINE", ""),
        ("b/scene.radium", "UNTOUCHED", ""),
    ])
    _mk_extract(stk, {}, strings=[
        ("a/scene.radium", "WELL DONE", ""),
        ("a/scene.radium", "SAME LINE", ""),
        ("b/scene.radium", "UNTOUCHED", ""),
    ])
    diff = mod_transfer.diff_baked_mods(mod, stk)
    assert diff["text_rows"] == [{"path": "a/scene.radium",
                                  "original": "WELL DONE",
                                  "replacement": "COWABUNGA"}]
    assert diff["notes"]["skipped_text_assets"] == 0


def test_baked_mods_end_to_end_transfer(tmp_path):
    # Full flow: modded old extract + stock old extract -> plan onto a new
    # version whose sound moved to a different index -> the new extract's
    # sidecar points the moved slot at the modded extract's WAV.
    mod, stk, tgt = (str(tmp_path / "modded"), str(tmp_path / "stock"),
                     str(tmp_path / "new"))
    _mk_extract(mod, {"audio/idx0003.wav": b"1987-THEME" * 100},
                strings=[("a/scene.radium", "COWABUNGA", "")])
    _mk_extract(stk, {"audio/idx0003.wav": b"STOCK-THEME" * 100},
                strings=[("a/scene.radium", "WELL DONE", "")])
    _mk_extract(tgt, {"audio/idx0007.wav": b"STOCK-THEME" * 100},
                strings=[("a/scene.radium", "WELL DONE", "")])

    diff = mod_transfer.diff_baked_mods(mod, stk)
    plan = mod_transfer.plan_transfer(stk, tgt, saved=diff["saved"],
                                      src_text_rows=diff["text_rows"])
    assert len(plan["audio"]["remapped"]) == 1
    assert plan["audio"]["remapped"][0]["tgt_rel"] == "audio/idx0007.wav"
    assert len(plan["text"]["matched"]) == 1

    mod_transfer.apply_transfer(stk, tgt, plan, src_saved=diff["saved"])
    saved = staged_changes.load(tgt)
    assert saved["audio"]["audio/idx0007.wav"] == os.path.abspath(
        os.path.join(mod, "audio", "idx0003.wav"))
    rows = {r["original"]: r["replacement"] for r in text_manifest.load(tgt)}
    assert rows["WELL DONE"] == "COWABUNGA"


def test_plan_direct_diff_images_videos_no_baseline(tmp_path):
    # No stock old-version extract: diff the modded old extract directly
    # against the new one.  Same-named differing image/video = staged;
    # manifest.txt (extractor metadata, always differs) is never a slot.
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {},
                images={"images/backglass.png": b"1987-ART",
                        "images/same.png": b"SAME",
                        "video/intro.mp4": b"1987-VIDEO",
                        "video/manifest.txt": b"old manifest",
                        "video/gone_in_159.mp4": b"ORPHAN"})
    _mk_extract(tgt, {},
                images={"images/backglass.png": b"STOCK-ART-159",
                        "images/same.png": b"SAME",
                        "video/intro.mp4": b"STOCK-VIDEO-159",
                        "video/manifest.txt": b"new manifest"})

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    assert [e["rel"] for e in plan["video"]["matched"]] == ["video/intro.mp4"]
    assert [e["rel"] for e in plan["image"]["matched"]] == [
        "images/backglass.png"]
    assert plan["notes"]["video_old_only"] == 1    # gone_in_159.mp4
    assert plan["notes"]["image_old_only"] == 0
    assert plan["totals"] == {"transfer": 2, "flagged": 0, "dropped": 0}
    assert not plan["audio"]["matched"] and not plan["text"]["matched"]

    mod_transfer.apply_transfer(mod, tgt, plan, src_saved={})
    saved = staged_changes.load(tgt)
    assert saved["video"]["video/intro.mp4"] == os.path.abspath(
        os.path.join(mod, "video", "intro.mp4"))
    assert saved["image"]["images/backglass.png"] == os.path.abspath(
        os.path.join(mod, "images", "backglass.png"))


def test_baseline_excludes_vendor_rebake_that_direct_diff_carries(tmp_path):
    """A file the VENDOR re-baked between versions but the user never modded:

    ``system_font`` is byte-identical in the modded old extract and the stock
    OLD extract (the user didn't touch it) but differs in the new version (the
    factory re-baked it).  ``game_art`` is a genuine user mod.

    * ``diff_baked_mods`` (stock same-version baseline) stages ONLY the genuine
      mod — the re-bake is ``modded == old-stock`` so it is correctly left out.
    * ``plan_direct_diff`` (no baseline) has nothing to compare the old bytes
      against but the NEW stock, so it wrongly stages the re-bake too.

    On a real card the no-baseline route therefore writes old-version bytes over
    an asset the new firmware re-baked, and the new firmware's per-asset content
    check counts every one as a mismatch (the TMNT ``#5`` second counter).  The
    baseline flow is the fix; this locks that contrast in."""
    mod = str(tmp_path / "modded158")
    old_stock = str(tmp_path / "stock158")
    new_stock = str(tmp_path / "stock159")
    _mk_extract(mod, {}, images={
        "images/system_font.png": b"FONT-158",     # untouched (== old stock)
        "images/game_art.png": b"1987-ART",        # a genuine user mod
    })
    _mk_extract(old_stock, {}, images={
        "images/system_font.png": b"FONT-158",
        "images/game_art.png": b"STOCK-ART-158",
    })
    _mk_extract(new_stock, {}, images={
        "images/system_font.png": b"FONT-159",     # vendor re-baked it
        "images/game_art.png": b"STOCK-ART-159",
    })

    # Baseline flow: only the genuine mod; the vendor re-bake is excluded.
    diff = mod_transfer.diff_baked_mods(mod, old_stock)
    assert list(diff["saved"]["image"]) == ["images/game_art.png"]

    # No-baseline flow: carries the vendor re-bake as if it were a mod.
    plan = mod_transfer.plan_direct_diff(mod, new_stock)
    assert sorted(e["rel"] for e in plan["image"]["matched"]) == [
        "images/game_art.png", "images/system_font.png"]


def _write_manifest(root, rows):
    """rows: list of (output filename, on-card path)."""
    d = os.path.join(root, "video")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n")
        for out, card in rows:
            f.write("%s\t%s\t0\n" % (out, card))


def test_plan_direct_diff_pairs_videos_by_card_path(tmp_path):
    # Video output filenames are scene-title-derived and shift across
    # versions (dup suffixes renumber, video_NNNN fallbacks reorder).  The
    # extract manifest's on-card path is the stable identity: a renamed but
    # same-clip video must pair (and diff), not land in "old only".
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {}, images={"video/intro_2.mp4": b"1987-VIDEO",
                                 "video/video_0007.mp4": b"SAME-CLIP"})
    _mk_extract(tgt, {}, images={"video/intro_3.mp4": b"STOCK-VIDEO-159",
                                 "video/video_0009.mp4": b"SAME-CLIP"})
    _write_manifest(mod, [("intro_2.mp4", "/videos/intro.mp4"),
                          ("video_0007.mp4", "/videos/attract.mp4")])
    _write_manifest(tgt, [("intro_3.mp4", "/videos/intro.mp4"),
                          ("video_0009.mp4", "/videos/attract.mp4")])

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    # The modded intro pairs across the rename and lands on the TARGET's rel.
    assert [e["rel"] for e in plan["video"]["matched"]] == [
        "video/intro_3.mp4"]
    assert plan["video"]["matched"][0]["repl"] == os.path.abspath(
        os.path.join(mod, "video", "intro_2.mp4"))
    # The identical (also-renamed) clip pairs and compares equal — no diff,
    # and nothing lands in old-only.
    assert plan["notes"]["video_old_only"] == 0


def test_plan_transfer_video_remaps_by_card_path(tmp_path):
    # The shipped pending-edits transfer has the same rename hazard: a video
    # assignment must follow its clip's on-card path onto the new version's
    # (renamed) rel instead of being dropped.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"video/battle_2.mp4": b"OLD-STOCK"})
    _mk_extract(tgt, {}, images={"video/battle_4.mp4": b"NEW-STOCK"})
    _write_manifest(src, [("battle_2.mp4", "/videos/battle.mp4")])
    _write_manifest(tgt, [("battle_4.mp4", "/videos/battle.mp4")])
    staged_changes.save(src, {"video": {"video/battle_2.mp4": r"C:\r\b.mp4"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert [e["rel"] for e in plan["video"]["matched"]] == [
        "video/battle_4.mp4"]
    assert not plan["video"]["dropped"]

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["video"]["video/battle_4.mp4"] == \
        r"C:\r\b.mp4"


def _write_texture_manifest(root, rows):
    """rows: list of (out_rel under images/, asset card path)."""
    d = os.path.join(root, "images", "scene_textures")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\twidth\theight\tformat\n")
        for out, card in rows:
            f.write("%s\t%s\t0\t64\t64\t5\n" % (out, card))


def _write_radium_manifest(root, rows):
    """rows: list of (out_rel under images/, radium card path) — one row per
    on-card occurrence, in offset order."""
    d = os.path.join(root, "images", "scene_textures")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "radium_images.txt"), "w",
              encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength\tpad_w"
                "\tpad_h\tfmt\n")
        for out, card in rows:
            f.write("%s\t%s\t0\t0\t64\t64\t5\n" % (out, card))


def test_plan_direct_diff_pairs_scene_textures_by_card_path(tmp_path):
    # Scene-texture filenames (<scene8>_<ref>_<WxH> + dedup suffix) shift
    # across versions; the manifest's on-card asset path is the identity.
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {}, images={
        "images/scene_textures/Bonus_3_64x64.png": b"1987-ART",
        "images/scene_textures/Bonus_3_64x64_2.png": b"SAME"})
    _mk_extract(tgt, {}, images={
        "images/scene_textures/Bonus_4_64x64.png": b"STOCK-159",
        "images/scene_textures/Bonus_3_64x64.png": b"SAME"})
    _write_texture_manifest(mod, [
        ("scene_textures/Bonus_3_64x64.png", "/scenes/Bonus/scene.assets/3"),
        ("scene_textures/Bonus_3_64x64_2.png", "/scenes/Bonus/scene.assets/7"),
    ])
    _write_texture_manifest(tgt, [
        ("scene_textures/Bonus_4_64x64.png", "/scenes/Bonus/scene.assets/3"),
        ("scene_textures/Bonus_3_64x64.png", "/scenes/Bonus/scene.assets/7"),
    ])

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    # The modded texture follows its asset card path onto the RENAMED target
    # rel; the identical one pairs (also renamed) and compares equal.
    assert [e["rel"] for e in plan["image"]["matched"]] == [
        "images/scene_textures/Bonus_4_64x64.png"]
    assert plan["image"]["matched"][0]["repl"] == os.path.abspath(os.path.join(
        mod, "images", "scene_textures", "Bonus_3_64x64.png"))
    assert plan["notes"]["image_old_only"] == 0


def test_plan_direct_diff_pairs_radium_images_by_occurrence(tmp_path):
    # Radium-image filenames embed a CONTENT hash, so a modded image can
    # never pair by name — pairing is (radium card path, occurrence ordinal).
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {}, images={
        "images/scene_textures/radimg_Title_64x64_aaaaaaaa.png": b"1987-GLYPH",
        "images/scene_textures/radimg_Score_64x64_bbbbbbbb.png": b"SAME"})
    _mk_extract(tgt, {}, images={
        "images/scene_textures/radimg_Title_64x64_cccccccc.png": b"STOCK-GLYPH",
        "images/scene_textures/radimg_Score_64x64_bbbbbbbb.png": b"SAME"})
    _write_radium_manifest(mod, [
        ("scene_textures/radimg_Title_64x64_aaaaaaaa.png",
         "/scenes/Title/scene.radium"),
        ("scene_textures/radimg_Score_64x64_bbbbbbbb.png",
         "/scenes/Title/scene.radium"),
    ])
    _write_radium_manifest(tgt, [
        ("scene_textures/radimg_Title_64x64_cccccccc.png",
         "/scenes/Title/scene.radium"),
        ("scene_textures/radimg_Score_64x64_bbbbbbbb.png",
         "/scenes/Title/scene.radium"),
    ])

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    assert [e["rel"] for e in plan["image"]["matched"]] == [
        "images/scene_textures/radimg_Title_64x64_cccccccc.png"]
    assert plan["image"]["matched"][0]["repl"] == os.path.abspath(os.path.join(
        mod, "images", "scene_textures",
        "radimg_Title_64x64_aaaaaaaa.png"))
    # The hash-renamed old file must NOT be counted as old-only — it paired.
    assert plan["notes"]["image_old_only"] == 0


def test_diff_baked_mods_pairs_modded_radium_images(tmp_path):
    # Same-version stock-baseline route: a modded radium image's NAME differs
    # from stock (content hash) — without ordinal pairing it was silently
    # invisible to the diff.
    mod, stk = str(tmp_path / "modded"), str(tmp_path / "stock")
    _mk_extract(mod, {}, images={
        "images/scene_textures/radimg_Title_64x64_aaaaaaaa.png": b"1987-GLYPH"})
    _mk_extract(stk, {}, images={
        "images/scene_textures/radimg_Title_64x64_cccccccc.png": b"STOCK-GLYPH"})
    _write_radium_manifest(mod, [
        ("scene_textures/radimg_Title_64x64_aaaaaaaa.png",
         "/scenes/Title/scene.radium")])
    _write_radium_manifest(stk, [
        ("scene_textures/radimg_Title_64x64_cccccccc.png",
         "/scenes/Title/scene.radium")])

    diff = mod_transfer.diff_baked_mods(mod, stk)
    # Keyed by the STOCK rel (plan_transfer's source side), replacement = the
    # modded extract's differently-named PNG.
    assert diff["saved"]["image"] == {
        "images/scene_textures/radimg_Title_64x64_cccccccc.png":
            os.path.abspath(os.path.join(
                mod, "images", "scene_textures",
                "radimg_Title_64x64_aaaaaaaa.png"))}


def test_plan_transfer_image_remaps_by_manifest(tmp_path):
    # The pending-edits transfer follows a scene-texture assignment onto the
    # new version's renamed rel via the manifests.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={
        "images/scene_textures/Bonus_3_64x64.png": b"OLD-STOCK"})
    _mk_extract(tgt, {}, images={
        "images/scene_textures/Bonus_5_64x64.png": b"NEW-STOCK"})
    _write_texture_manifest(src, [
        ("scene_textures/Bonus_3_64x64.png", "/scenes/Bonus/scene.assets/3")])
    _write_texture_manifest(tgt, [
        ("scene_textures/Bonus_5_64x64.png", "/scenes/Bonus/scene.assets/3")])
    staged_changes.save(src, {"image": {
        "images/scene_textures/Bonus_3_64x64.png": r"C:\r\art.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert [e["rel"] for e in plan["image"]["matched"]] == [
        "images/scene_textures/Bonus_5_64x64.png"]
    assert not plan["image"]["dropped"]

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["image"][
        "images/scene_textures/Bonus_5_64x64.png"] == r"C:\r\art.png"


def test_plan_direct_diff_fans_deduped_src_image_to_all_ordinals(tmp_path):
    # Extraction content-dedupes radium images: an animation whose frames were
    # all baked identical is ONE old-side PNG occupying two occurrence slots.
    # The new version's frames differ per slot, so the modded image must land
    # on BOTH target rels, not just the first pairing.
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {}, images={
        "images/scene_textures/radimg_Anim_64x64_aaaaaaaa.png": b"1987-FRAME"})
    _mk_extract(tgt, {}, images={
        "images/scene_textures/radimg_Anim_64x64_cccccccc.png": b"STOCK-F1",
        "images/scene_textures/radimg_Anim_64x64_dddddddd.png": b"STOCK-F2"})
    _write_radium_manifest(mod, [
        ("scene_textures/radimg_Anim_64x64_aaaaaaaa.png",
         "/scenes/Anim/scene.radium"),
        ("scene_textures/radimg_Anim_64x64_aaaaaaaa.png",
         "/scenes/Anim/scene.radium"),
    ])
    _write_radium_manifest(tgt, [
        ("scene_textures/radimg_Anim_64x64_cccccccc.png",
         "/scenes/Anim/scene.radium"),
        ("scene_textures/radimg_Anim_64x64_dddddddd.png",
         "/scenes/Anim/scene.radium"),
    ])

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    repl = os.path.abspath(os.path.join(
        mod, "images", "scene_textures", "radimg_Anim_64x64_aaaaaaaa.png"))
    assert sorted(e["rel"] for e in plan["image"]["matched"]) == [
        "images/scene_textures/radimg_Anim_64x64_cccccccc.png",
        "images/scene_textures/radimg_Anim_64x64_dddddddd.png"]
    assert all(e["repl"] == repl for e in plan["image"]["matched"])
    assert plan["notes"]["image_old_only"] == 0
    assert plan["totals"]["transfer"] == 2


def test_plan_transfer_image_fans_deduped_assignment_to_all_ordinals(tmp_path):
    # Same fan-out through the sidecar route: one pending assignment on a
    # deduped source rel becomes one matched entry PER target occurrence rel.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={
        "images/scene_textures/radimg_Anim_64x64_aaaaaaaa.png": b"OLD-STOCK"})
    _mk_extract(tgt, {}, images={
        "images/scene_textures/radimg_Anim_64x64_cccccccc.png": b"NEW-F1",
        "images/scene_textures/radimg_Anim_64x64_dddddddd.png": b"NEW-F2"})
    _write_radium_manifest(src, [
        ("scene_textures/radimg_Anim_64x64_aaaaaaaa.png",
         "/scenes/Anim/scene.radium"),
        ("scene_textures/radimg_Anim_64x64_aaaaaaaa.png",
         "/scenes/Anim/scene.radium"),
    ])
    _write_radium_manifest(tgt, [
        ("scene_textures/radimg_Anim_64x64_cccccccc.png",
         "/scenes/Anim/scene.radium"),
        ("scene_textures/radimg_Anim_64x64_dddddddd.png",
         "/scenes/Anim/scene.radium"),
    ])
    staged_changes.save(src, {"image": {
        "images/scene_textures/radimg_Anim_64x64_aaaaaaaa.png":
            r"C:\r\frame.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert sorted(e["rel"] for e in plan["image"]["matched"]) == [
        "images/scene_textures/radimg_Anim_64x64_cccccccc.png",
        "images/scene_textures/radimg_Anim_64x64_dddddddd.png"]
    assert all(e["repl"] == r"C:\r\frame.png"
               for e in plan["image"]["matched"])
    assert not plan["image"]["dropped"]

    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)["image"]
    assert saved == {
        "images/scene_textures/radimg_Anim_64x64_cccccccc.png":
            r"C:\r\frame.png",
        "images/scene_textures/radimg_Anim_64x64_dddddddd.png":
            r"C:\r\frame.png"}


def _png(path, color, comment):
    """A real PNG: same *color* + different *comment* = byte-different files
    that decode to identical pixels (a re-encode, not a mod)."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    os.makedirs(os.path.dirname(path), exist_ok=True)
    info = PngInfo()
    info.add_text("Comment", comment)
    Image.new("RGBA", (4, 4), color).save(path, pnginfo=info)


def test_plan_direct_diff_skips_pixel_identical_rebake(tmp_path):
    # A vendor/tool re-encode byte-differs but is a pixel no-op — it must be
    # skipped (and counted), while a real pixel change still stages.
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _png(os.path.join(mod, "images", "rebaked.png"), (255, 0, 0, 255), "old")
    _png(os.path.join(tgt, "images", "rebaked.png"), (255, 0, 0, 255), "new")
    _png(os.path.join(mod, "images", "modded.png"), (0, 255, 0, 255), "old")
    _png(os.path.join(tgt, "images", "modded.png"), (0, 0, 255, 255), "new")
    with open(os.path.join(mod, "images", "rebaked.png"), "rb") as f_a, \
            open(os.path.join(tgt, "images", "rebaked.png"), "rb") as f_b:
        assert f_a.read() != f_b.read()     # fixture sanity: bytes DO differ

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    assert [e["rel"] for e in plan["image"]["matched"]] == [
        "images/modded.png"]
    assert plan["notes"]["image_rebake_skipped"] == 1
    assert plan["totals"]["transfer"] == 1


def test_diff_baked_mods_skips_pixel_identical_rebake(tmp_path):
    # Same filter on the stock-baseline route: an external tool re-encoded an
    # image it never modified — bytes differ, pixels don't, so it isn't a mod.
    mod, stk = str(tmp_path / "modded"), str(tmp_path / "stock")
    _png(os.path.join(mod, "images", "reencoded.png"), (255, 0, 0, 255), "a")
    _png(os.path.join(stk, "images", "reencoded.png"), (255, 0, 0, 255), "b")
    _png(os.path.join(mod, "images", "modded.png"), (0, 255, 0, 255), "a")
    _png(os.path.join(stk, "images", "modded.png"), (0, 0, 255, 255), "b")

    diff = mod_transfer.diff_baked_mods(mod, stk)
    assert list(diff["saved"]["image"]) == ["images/modded.png"]
    assert diff["notes"]["image_rebake_skipped"] == 1


def test_plan_direct_diff_audio_text_headsup_counts(tmp_path):
    # Audio/text can't transfer without a baseline, but the plan counts what
    # it couldn't attribute so the GUI can warn.
    mod, tgt = str(tmp_path / "modded158"), str(tmp_path / "stock159")
    _mk_extract(mod, {"audio/idx0001.wav": b"1987-SONG" * 50,
                      "audio/idx0002.wav": b"SAME" * 50},
                strings=[("a/scene.radium", "COWABUNGA", ""),
                         ("b/scene.radium", "SAME LINE", "")])
    _mk_extract(tgt, {"audio/idx0001.wav": b"STOCK" * 50,
                      "audio/idx0002.wav": b"SAME" * 50},
                strings=[("a/scene.radium", "WELL DONE", ""),
                         ("b/scene.radium", "SAME LINE", "")])

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    assert plan["totals"]["transfer"] == 0
    assert plan["notes"]["audio_unmatched"] == 1
    assert plan["notes"]["text_unmatched"] == 1


def test_apply_preserves_existing_target_edits(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {"audio/idx0001.wav": b"A" * 300})
    _mk_extract(tgt, {"audio/idx0001.wav": b"A" * 300,
                      "audio/idx0002.wav": b"B" * 300})
    staged_changes.save(src, {"audio": {"audio/idx0001.wav": r"C:\r\a.mp3"}})
    # target already has an edit on a different slot
    staged_changes.save(tgt, {"audio": {"audio/idx0002.wav": r"C:\r\b.mp3"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    mod_transfer.apply_transfer(src, tgt, plan)
    saved = staged_changes.load(tgt)["audio"]
    assert saved["audio/idx0001.wav"] == r"C:\r\a.mp3"
    assert saved["audio/idx0002.wav"] == r"C:\r\b.mp3"


# ---- font glyph slices: (radium, atlas ordinal, char) identity ---------------

def _write_glyph_manifest(root, rows):
    """rows: list of (glyph out_rel under images/, atlas out_rel, char str)."""
    d = os.path.join(root, "images", "scene_textures")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "glyph_images.txt"), "w", encoding="utf-8") as f:
        f.write("# glyph output\tatlas output\tchar\tx\ty\tw\th\tfont\n")
        for out, atlas, char in rows:
            f.write("%s\t%s\t%s\t1\t1\t8\t8\tFace\n" % (out, atlas, char))


def _glyph_fixture(root, stem, glyph_bytes, chars=("0x0041",)):
    """One font atlas + its glyph slice(s) with matching manifests."""
    atlas_rel = "scene_textures/radimg_Font_64x64_%s.png" % stem
    imgs = {"images/" + atlas_rel: b"ATLAS-" + stem.encode()}
    rows = []
    for i, ch in enumerate(chars):
        g_rel = "scene_textures/glyphs/radimg_Font_64x64_%s/U+%s_G%d.png" % (
            stem, ch[2:], i)
        imgs["images/" + g_rel] = glyph_bytes + ch.encode()
        rows.append((g_rel, atlas_rel, ch))
    _mk_extract(root, {}, images=imgs)
    _write_radium_manifest(root, [(atlas_rel, "/scenes/Font/scene.radium")])
    _write_glyph_manifest(root, rows)
    return ["images/" + r[0] for r in rows]


def test_plan_transfer_glyph_follows_char_across_atlas_rename(tmp_path):
    # The font art changed between versions, so every path under glyphs/
    # (atlas content hash) is new — the char identity carries the edit over.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    (src_glyph,) = _glyph_fixture(src, "aaaaaaaa", b"OLD")
    (tgt_glyph,) = _glyph_fixture(tgt, "cccccccc", b"NEW")
    staged_changes.save(src, {"image": {src_glyph: r"C:\r\A.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert [e["rel"] for e in plan["image"]["matched"]] == [tgt_glyph]
    assert not plan["image"]["dropped"]

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["image"][tgt_glyph] == r"C:\r\A.png"


def test_plan_transfer_glyph_char_gone_is_dropped(tmp_path):
    # The new font dropped the character: the manifests are authoritative, so
    # the edit is dropped even though a same-named file happens to exist.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    (src_glyph,) = _glyph_fixture(src, "aaaaaaaa", b"SAME")
    _glyph_fixture(tgt, "aaaaaaaa", b"SAME", chars=("0x0042",))
    # forge the same-rel file on the target (stale leftover)
    _wav(os.path.join(tgt, src_glyph.replace("/", os.sep)), b"stale")
    staged_changes.save(src, {"image": {src_glyph: r"C:\r\A.png"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert not plan["image"]["matched"]
    assert len(plan["image"]["dropped"]) == 1


def test_plan_direct_diff_stages_modded_glyph(tmp_path):
    # Baked-mods direct diff: a glyph slice whose pixels differ is staged onto
    # the TARGET's (renamed) glyph rel through the same identity.
    mod, tgt = str(tmp_path / "modded"), str(tmp_path / "stock159")
    (mod_glyph,) = _glyph_fixture(mod, "aaaaaaaa", b"MODDED")
    (tgt_glyph,) = _glyph_fixture(tgt, "cccccccc", b"STOCK")

    plan = mod_transfer.plan_direct_diff(mod, tgt)
    staged = {e["rel"]: e["repl"] for e in plan["image"]["matched"]}
    assert tgt_glyph in staged
    assert staged[tgt_glyph] == os.path.abspath(
        os.path.join(mod, mod_glyph.replace("/", os.sep)))


# ---- renamed image groups (image_group_tags) ---------------------------------

def _write_loose_manifest(root, rows):
    """rows: list of (out_rel under images/, card path)."""
    d = os.path.join(root, "images")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n")
        for out, card in rows:
            f.write("%s\t%s\t9\n" % (out, card))


def test_plan_transfer_carries_group_tags(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _mk_extract(src, {}, images={"images/x.png": b"X"})
    _mk_extract(tgt, {}, images={"images/x.png": b"X"})
    _write_radium_manifest(tgt, [
        ("scene_textures/radimg_T_64x64_cc.png", "/scenes/Title/scene.radium")])
    _write_texture_manifest(tgt, [
        ("scene_textures/Bonus_3_64x64.png", "/scenes/Bonus/scene.assets/3")])
    _write_loose_manifest(tgt, [("loose/logo.png", "/game/assets/loose/logo.png")])
    staged_changes.save(src, {"image_group_tags": {
        "rad::/scenes/Title/scene.radium": "Title Anim",
        "scn::/scenes/Bonus": "Bonus Art",
        "dir::/game/assets/loose": "Loose Stuff",
        "rad::/scenes/Gone/scene.radium": "Gone Group",
    }})

    plan = mod_transfer.plan_transfer(src, tgt)
    got = {e["key"]: e["name"] for e in plan["group_tags"]["matched"]}
    assert got == {"rad::/scenes/Title/scene.radium": "Title Anim",
                   "scn::/scenes/Bonus": "Bonus Art",
                   "dir::/game/assets/loose": "Loose Stuff"}
    assert [e["key"] for e in plan["group_tags"]["dropped"]] == [
        "rad::/scenes/Gone/scene.radium"]
    assert plan["totals"]["transfer"] == 3
    assert plan["totals"]["dropped"] == 1

    # A name the user already gave a group on the TARGET wins.
    staged_changes.save(tgt, {"image_group_tags": {
        "rad::/scenes/Title/scene.radium": "Theirs"}})
    res = mod_transfer.apply_transfer(src, tgt, plan)
    assert res["group_tags"] == 2
    tags = staged_changes.load(tgt)["image_group_tags"]
    assert tags["rad::/scenes/Title/scene.radium"] == "Theirs"
    assert tags["scn::/scenes/Bonus"] == "Bonus Art"
    assert tags["dir::/game/assets/loose"] == "Loose Stuff"
    assert "rad::/scenes/Gone/scene.radium" not in tags


def test_plan_transfer_remaps_glyph_folder_tag(tmp_path):
    # A renamed GLYPH group's key embeds the atlas content hash — it follows
    # the atlas identity onto the new version's stem.
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _glyph_fixture(src, "aaaaaaaa", b"OLD")
    _glyph_fixture(tgt, "cccccccc", b"NEW")
    staged_changes.save(src, {"image_group_tags": {
        "dir::images/scene_textures/glyphs/radimg_Font_64x64_aaaaaaaa":
            "Score Font"}})

    plan = mod_transfer.plan_transfer(src, tgt)
    assert [e["key"] for e in plan["group_tags"]["matched"]] == [
        "dir::images/scene_textures/glyphs/radimg_Font_64x64_cccccccc"]

    mod_transfer.apply_transfer(src, tgt, plan)
    assert staged_changes.load(tgt)["image_group_tags"] == {
        "dir::images/scene_textures/glyphs/radimg_Font_64x64_cccccccc":
            "Score Font"}
