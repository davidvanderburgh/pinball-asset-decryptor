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

## Done in round 2 (commit 92e336874): a game mode's own sounds by music mode

Neither route above: each music mode's file is ONE MORE OWN SOUND on a carrier of its own from the same allocator
(own-sound key `music@2`, `sound_start@3`...: beds, swaps, banks as for the plain sound, so every title that carries a
mode's sound carries these). ModeSpec.sound_modes {key: {"2": file}} (files in the mode folder); the mode file gets
`<key>@<m> <request> ...` lines (mode_project.own_sound_lines); mode_file.c own_sounds_alt / own_sounds_music_mode
put the MUSIC MODE's carriers in place at each start (pm_music_mode in pad_mode.h). Modes.own_top (load) and
own_mm (engine, from mode_own_used) give the card MUSIC MODE and its setting line. Modes tab Sounds page: "By music
mode" grid (ModesTab._own_modes_state, rpc modes.choose_own_mode). Emulator proof: Godzilla LE 1.16, mode starting
at ball start, MUSIC MODE 1 -> bed 618, 2 -> bed 105 (C:	mp\PAD-1637ig mkset2.py / job2.sh).

Not covered: code modes' and block modes' own sounds (`call:<cue>`, `music:<name>`), set in their own code / blocks.
