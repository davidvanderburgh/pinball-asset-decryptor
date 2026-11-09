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

## Proven (run 3, 2026-11-09, after the PC restart)

Emulator, rig kit C:/tmp/PAD-1079 (go.sh l1.txt / l2.txt), each 1 pass: Godzilla LE 1.16 and Pro 1.16. SHODAIGOJI's
test pattern fills its card's frame exactly and moves (clip clock 3.8 s -> 5.4 s); the flipper to KINGOJI swaps to its
clip; SOSHINGEKI (no video) shows its picture with the city round the card; PICKED keeps the clip; after the pick the
city is back ("given back" each time, 3 plays / 3 given back, no faults). While a clip plays the glass round the card is
the clip's black. Shots: artifacts/PAD-1079/proof_*.png. After the restart PAD-Runtime had lost the qemu-arm binfmt
(the run "ended by itself at 4s", Exec format error): `cat /usr/lib/binfmt.d/qemu-arm.conf >
/proc/sys/fs/binfmt_misc/register` as root.

The build now gates on the bank's Normal crop BEING the identity (video_bank.crop_transform). John Wick LE/Pro have a
backdrop but on the bank's surface (clip v2, `backdrop_surface 1`, no city vtable): can_video is False there, the
dialog says so and the pictures show.
