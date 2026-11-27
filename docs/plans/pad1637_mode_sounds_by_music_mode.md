# PAD-1637: sounds by MUSIC MODE - status and the part left

DoomWalrus666 (Godzilla Pro / Premium retheme) asked for the co-op intro, character select and awards ceremony
music to change with the music mode choice, and in Discord: "Or any specially assigned audio track in Custom Modes
of any kind".

## Done (commits 91b02f439, 6c16729a6)

Co-op sounds by music mode, proven on the emulator (Godzilla LE 1.16, rig kit `C:\tmp\PAD-1637\rig`: mkset.py,
job.sh, job_m1/m2.sh, run_m1/m2.sh run as root in PAD-Runtime; proof logs in artifacts/PAD-1637/proof_music_mode_*.txt).

- Project: `coop_play.save_mode_sound(project, kind, m, src)` (kind intro / select / ceremony, top-level
  `characters["mode_sounds"]`), `save_picked_mode_sound(project, i, m, src)` (per character `picked_modes`),
  `mode_sounds(project)`; the co-op settings file carries them.
- Build: `engine._coop_mode_wavs` (cache prefix `coopmm_`), `Modes.coop_modes` `[(role, m, WAV)]`, pseudo modes
  `sound_modes.coop_mode(role, m)` = 4200 + (m-2)*32 + (role-4000); `_intro_lines` -> `by_mode`; sounds.cfg lines
  `cintro/cpick/ccer/cselm ... <m>`. `Modes.coop_top` (set by `load()`) gives the card MUSIC MODE by itself;
  `_sound_modes_cfg` writes `setting` for co-op mode files alone (`coop_mm`). MUSIC MODE must be ticked on the
  Service menu tab (as for the Audio tab's music modes).
- Runtime: `cmm_*` in pad_mode_runtime.c ("PAD-1637: the co-op sounds by MUSIC MODE"): each play copies the record
  and length of the mode now (sndm_mode), else mode 1's, else none.
- Dialog: Characters -> "By music mode..." grid (`ModesTab._coop_by_mode`, rpc `modes.coop_mode_sound`).

## Left: a custom game mode's own sounds by music mode

ModeSpec own sounds (mode_project.py ModeSpec `sound_start`, `sound_shot`, `sound_end`, `music`; Modes tab rows
`_OWN_SOUNDS` in webui/tabs/modes.py ~322) have one file each and never follow MUSIC MODE.

How they reach the card (engine order, line numbers approximate):
1. `mode_write.choose_own_sounds` (~735) -> `mode_sounds.assign` (~358): a carrier request per sound; on swap titles
   (`MS.swapped`) the engine picks it; Godzilla uses fixed carriers plus `music_sid` beds.
2. `_sound_modes_for_build` (engine ~12022) runs BEFORE the carriers are known.
3. `_mode_own_sounds_grow` (engine ~22921, called ~9389) converts (music: `MS.loop_wav` tiling, calls: raw + ms),
   fills `mode_own_used` (idx, carrier_idx, request).
4. `_sound_modes_grow` (~9461), `_sound_modes_for_banks` (~9501), `_plan_sound_banks` (~9537; `_bankable_idx`:
   swap sounds and music beds can go to banks), `_repoint_descriptors` + `_mode_swap_keys` (~9742/9886: swap titles
   get `swap <req> <stock key> <our key>` in the mode file; Godzilla's are re-pointed descriptors).
5. `_sound_modes_cfg` (~9922) writes sounds.cfg; the mode file is planned after (~10719).
Runtime: mode_file.c `own_call_try` -> `pm_sound_swap` fills `swaps[]`; `on_sound_lookup` matches
`swaps[i].stock` -> `LOOKUP_TAKE(swaps[i].ours)`. `sndm_mode()` is runtime-internal (mode.so's mode_file.c is
linked in the same object, so it can call it, but pad_mode.h has no accessor).

Two routes, pick by the Godzilla case (the reporter's title is a re-point / bed title, NOT a swap title):
- A (try first): after step 3, add the carrier's slot to `Modes.slots[carrier rel][m] = file` so the Audio tab's
  own machinery (descriptor per sid per mode, `sound <m> <sid> <hex>`; banks via `bsid`) carries mode m's file.
  Works for re-pointed carriers if `_sound_mode_descriptors` reads the carrier sid's descriptor AFTER the re-point;
  on swap titles the mode's descriptor names a different record so the stock-key swap no longer matches and mode
  m's record plays. Music needs the loop tiling (`MS.loop_wav` / bed_min_frames) applied to mode files too. Check
  the MUSIC MODE count (`Modes.count` / `load()`) includes them (as `coop_top`).
- B: `mown <m> <ours1> <oursM>` lines + a check in `on_sound_lookup`'s swaps match (swap titles only; banked sounds
  and beds not covered).

Then: storage on ModeSpec (e.g. `sound_modes: {key: {"2": file}}`, carried by mode packs / mode export), a
per-mode
chooser beside each own-sound row on the Modes tab, tests, and an emulator proof on Godzilla LE 1.16 with a mode's
music in mode 1 vs mode 2 (the mode maker's rig recipes: PAD-474 / PAD-1031 kits).
