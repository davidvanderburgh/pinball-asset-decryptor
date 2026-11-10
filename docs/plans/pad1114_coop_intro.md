# PAD-1114: an intro video of the owner's for co-op and team games (DoomWalrus666, Godzilla)

Ask: "For co-op and team modes, I would like to have a custom intro video with its own sound. This video would be
skippable by pressing both flippers. Once the video finishes, or both flipper buttons are pressed, the ball is put into
the shooter Lane, and then language options, and then character select screen".

## What stock Godzilla LE 1.16 does at Start (emulator census, run 1, 2026-11-10)

Rig kit C:/tmp/PAD-1114/rig (census.sh, sampler.py, go.sh <list> <out> [job] as root, sheet.py contact sheets;
outputs out_census_lang / out_census_skip, sheet_lang.png / sheet_skip.png).

- At Start the game asks `clip_play("intro<N>")`, one of intro1/intro3/intro4/intro6 at random (class BDLGameIntro;
  its words "Tokyo, Japan / December 19, 1965" drawn by the game over the film).
- PLAYER LANGUAGE SELECT (adjustment 14) is NOT a screen of its own: it is a bar at the bottom of that film,
  "USE FLIPPERS TO SELECT LANGUAGE: English", shown for the film's length (t02-t03 of the census). Each flipper
  RELEASE flips the language (cabinet keys 137/139, `site language_keys`, PAD-1078). The arm at Start is 0x225330
  (writes 5 to 0x712738); the toggle 0x13f7d0 checks state object 0x7b0f70 (state 1) and the rule at 0x7b13b0.
  FG 8 = FG_PLAYER_LANGUAGE_SELECT_RESTART_ALLOWED (never set in the census).
- A flipper press during the film ends it (skip run: both flippers at ~4 s, the logo at 6 s) - and both releases
  flipped the language twice (back to English).
- Then the GODZILLA logo reveal (PAD-1107 hides it under a pick card), then the city.
- The ball's arrival is NOT tied to the film: FG 12 (ball in the auto plunger) rose at 11.6 s in one run, 1.0 s in
  the other (the rig's ball feed). FG 13 (player control) at 0.6 s both times.
- The co-op pick today opens at Start (solo hold / menu pick / join) and takes the flippers from the language keys
  while its ball waits (PAD-1051/1078) - so the stock order with characters is pick and language at once.

## Design (decided)

The runtime imposes the reporter's order on a game that BEGINS as co-op or team (right flipper held at Start, the
start menu's CO-OP PLAY / TEAM PLAY pick, a team mode's filling Start): a game that becomes co-op later (a teammate
joining a plain game's ball 1) has no intro - its film has played.

1. INTRO: the game's `intro<N>` ask is answered with `PadCoopIntro` (clip_play name swap, as clip variants do) so
   the game's own film machinery plays ours full-screen; the game's words over it hidden (find the BDLGameIntro text
   nodes; pm_show 0 as coop_logo_hold does). Its sound: the intro's soundtrack on a carrier (PAD-945's road: a
   pseudo mode in sound_modes, `cintro <request> <carrier key> <our key> <ms>` in sounds.cfg), started when the clip
   is asked for, stopped at a skip. The film's own sounds (SE GZ VO GAME INTRO n, music) are faded while ours plays.
   If the swapped film does not hold for our clip's length, fall back to playing it on the backdrop (pm_backdrop).
2. SKIP: both flipper buttons down together (levels polled, either order within ~0.4 s) ends ours (seek the clip to
   its end / stop it, stop our sound). One flipper alone does nothing. The language keys are vetoed while the intro
   plays (extend coop_language_veto), so the skip does not flip the language.
3. BALL: the pick and the language wait for FG 12 (the ball in the plunger) after the intro.
4. LANGUAGE: with adjustment 14 on (and >1 language), after the intro the runtime gives the flippers to the language
   keys for a window (the game's bar is gone with the film: the top line says "FLIPPERS: LANGUAGE <name>" through
   message_borrow, each release the game's own toggle), ended by Action/launch or LANGUAGE_MS (8 s, renewed on a
   press). With adjustment 14 off, straight on.
5. PICK: coop_pick_open(1) deferred until then (today it opens at once).

## Done (run 1)

- coop_play: `intro` in the characters record (save/load/settings zip carry it), save_intro / intro_path,
  intro_clip (fitted whole on the bank's frame, silent), intro_audio (the video's own sound as a 44.1 kHz WAV, "" when
  it has none), INTRO_CLIP / INTRO_FILE / INTRO_MAX_SECONDS.
- scripts/shot_pad1114.py (Modes tab co-op row: cramped by its note + Try it; the dialog is the better place).
- Before shots: C:/tmp/PAD-1114/shots/before_characters_dialog.png (scripts/shot_pad1079.py before).

## Left (runs 2+)

- mode_write.coop_clips_into: the intro clip into the bank (`intro_clip PadCoopIntro <ms>` in coop.cfg).
- sound_modes + engine: the intro's soundtrack on a carrier (INTRO_MODE pseudo mode; is_shot bounded to SHOT_MAX;
  _free_carrier skipping attract/shot slots; `cintro` line; card record `#cintro`). engine._sound_modes_for_build
  adds it when coop_play.load(project) and an intro is set (WAV made by intro_audio into the write cache).
- runtime (pad_mode_runtime.c "PAD-1114"): steps 1-5; prebuilt mode.so rebuilt (build_prebuilt.sh).
- Dialog: an "Intro video..." row in the Co-op characters dialog (webui tabs/modes.py coop_intro rpc,
  modes_dialogs.js), help text, MODE_SDK.md, docs/guide.
- Tests: tests/test_pad1114_coop_intro.py (storage, settings zip, cfg lines, runtime lifted helpers).
- Emulator proof on Godzilla LE 1.16 + Pro 1.16: solo hold, menu CO-OP, TEAM 2v2: intro plays with sound, both
  flippers skip it, language window, then the pick; no intro on a plain Start.
- After shots (dialog) and the reply draft.
