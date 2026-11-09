# PAD-1079: the co-op pick screen, customizable (DoomWalrus666)

Ask: "change the colors of certain text, add videos, or other alterations and customizations of the character
selection screen at my choice".

## Done (run 1, commit 9caad2a91 + the Panel well fix)

- `coop_play.THEME`: a colour per text (heading, count, name, sub, badge, badge_text, does, help), the frame
  (accent), corners (accent2), panel; `backdrop` (coop/backdrop.<ext>) + `dim` (DIMS 0-80). `theme_of` checks
  values; `save_look`, `save_look_default`, `save_backdrop`. A character's own `colour` (frame colour).
- `_body` draws the panel (stock wash / panel colour wash / background picture darkened). Pick + award cards.
- Settings file (zip) carries the look and `pictures/backdrop.<ext>`.
- Dialog: Look... (title, wells, Background..., Darken it, Default look); a well per row.
- With no look set the 8 cards compared (pick 0/3/RANDOM + award, stock + Godzilla theme) are bit-identical.
- Tests: tests/test_pad1079_coop_pick_look.py; shots: scripts/shot_pad1079.py.

## Run 2: videos (built, committed; emulator proof pending)

- coop_play: `video` per character (save_video, coop/character_<n>_video.<ext>), can_video (port has backdrop_draw),
  window_box / window_clip (the video covering the portrait window's place on a black 1360x768 clip), clip_entries,
  video_still (preview); pick_card(window=) cuts the frame see-through; pick_screens/preview cut it only when
  can_video. Settings zip carries videos.
- mode_write.coop_clips_into: clips into the bank as the build has it (PadCoopClip<n>), coop.cfg `char_clip <n>
  <clip>` + `clip_crop Normal`. engine reads the bank for co-op-only cards with videos.
- Crop: read off Godzilla LE 1.16's bank, the VideoSurface keyframe tracks are Normal = identity, ScoreFrame =
  x1.065 and -43,-98 (the port's backdrop_crop). So the clips play at Normal.
- Runtime: coop_clip_show (pm_backdrop of the shown card's clip, given back when it goes); prebuilt mode.so rebuilt.
- Dialog: Video... per row (row buttons wrap), note when the title cannot play them; help + MODE_SDK.md.

## Left: the emulator proof (WSL hung 2026-11-09 ~08:00, every wsl.exe timed out; needs `wsl --shutdown`)

Kit ready in C:/tmp/PAD-1079: mkset.py built the override set (ovr/, ovr-modes/ with coop.cfg char_clip 1-2 +
clip_crop Normal; test0.mp4 testsrc2 on SHODAIGOJI, test1.mp4 smptebars on KINGOJI). Launch:

    wsl.exe -d PAD-Runtime -u root -e bash /mnt/c/tmp/PAD-1079/go.sh l1.txt r1

(job.sh: one teammate added, shots v1 a/b on SHODAIGOJI 1 s apart = the video moves, v2 KINGOJI, v3 SOSHINGEKI
picture, v4 back, v5 PICKED, v6 after = city again; out in C:/tmp/PAD-1079/out_gz_le_v1, mode.log lines "plays
behind its card" / "given back"). Check the pattern fills the frame exactly; then Pro 1.16 (same list line with the
pro card + key) and the after shots are done.
