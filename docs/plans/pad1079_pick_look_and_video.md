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

## Next (run 2): a video per character on its pick screen

What the runtime already has (tools/spike2_emu/modes/sdk/pad_mode_runtime.c):
- `pm_backdrop(name)` loops a clip (stock or build-added) in the city's place BEHIND the HUD, with a crop
  (`bd_crop_next`, else the port's `backdrop_crop`, "ScoreFrame"); the co-op award cards already use it
  (`coop_bonus_crop`, ~line 17320). `pm_clip` plays full-screen OVER the HUD (would hide the card).
- `coop_screens_tick` shows `PadCoop_<n>` for `pk.at` while the pick is open.

Plan:
1. Owner side: a Video... button per character (and for RANDOM?) -> `coop/character_<n>.<ext>` + `"video"` key;
   carried by the settings file like pictures.
2. Card: a character with a video gets its portrait window cut to alpha 0 (premultiplied: rgb 0 too) so what
   plays behind the HUD shows through; the frame + glow stay.
3. Build: the clip goes into the card like a mode's own clip (mode_assets clip entries / video bank add), name
   e.g. `pad_coop_<n>`; the app pre-composes it with ffmpeg so its picture lands in the window: scale/crop to
   the window (380x306 card px at CARD_AT + (40, 84) on the 1360x768 glass) on black, at the geometry the
   backdrop actually plays at on Godzilla (measure in the emulator: where ScoreFrame/the city element draws
   and at what size the clip is stretched - PAD-562's lesson: bank Video size != clip size).
4. Runtime: coop.cfg `character_clip <n> <name>`; when the pick moves onto n, `pm_backdrop(name)` (with the
   crop that fills the glass), and `pm_backdrop(0)` when it moves off / closes, unless the award cards own it.
   Needs PM_CAN_BACKDROP on the port (Godzilla LE + Pro have it).
5. Proof: emulator, Godzilla LE 1.16 and Pro 1.16 (rig kit C:/tmp/PAD-1031/rig, PAD-1054's solo start: right
   flipper held at Start), glshot frames of the pick on a character with a clip and one without, flipper
   presses moving between them, and the clip stopping at the pick's close.
6. Tests: card window alpha, cfg lines, settings file round trip; the shot script grows a Video... step.
