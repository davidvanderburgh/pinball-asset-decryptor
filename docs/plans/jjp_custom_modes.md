# JJP custom modes (PAD-1335)

Status 2026-11-15: **emulator-proven on Guns N' Roses 3.03** with the GnR key.
A custom mode, loaded from outside the game binary, runs inside a live game:
it starts on the Jam Target, plays a game sound, shows a countdown banner,
scores 1,000,000 a hit through the game's own scoring (the game draws its own
floating "1,000,000"), and ends on the game's own mode timer. The game plays
on. No game code is patched.

## Why it works on JJP

The retail `game` is a Sentinel LDK Envelope: about 7,000 of its functions are
ciphertext at rest, and each decrypts itself on first call through a shared
trampoline. Calling them works. They stay decrypted in memory, so they can be
read through `/proc/<pid>/mem`, which never trips the anti-debug gate. Never
attach gdb or strace.

The binary **exports its whole C++ engine** in `.dynsym` (22,265 names on GnR;
`jjpelf.py` rebuilds it, since the section headers are stripped). A mode needs
nothing that isn't an exported function or a plain data pointer.

| Piece | What the engine has | How we use it |
|---|---|---|
| Mode | `Mode::Mode(name, id, ModeManager*, Lamp*, run_id, grace_id, grace_grace_id, Audit*, Audit*)`; 280-byte objects; `vtable for Mode` (24 slots) | Build one in our own memory and point it at a **copy** of Mode's vtable with three slots replaced |
| Lifecycle | `Mode::start` calls `proc_create(run_id, start_run_func)`. `run_proc` ticks at 125/s (+0x48 seconds, +0x4c ticks) and calls `hook_tick_work` (+0xa8), `hook_do_mode_start_choreo` (+0xb0), `is_timer_paused` (+0x38), then the total choreo (+0xb8), grace and `end` | Unchanged: the game runs our mode exactly as it runs Slash Solo |
| Trigger | Each `Switch` is a 104-byte global: +0 id, +8 name, +0x10 dispatch fn, run as a proc by `Switch::do_dispatches` | Wrap the dispatch pointer (one aligned 8-byte store) and call the original first |
| Points | `Mode::score_and_total` (+0x88) | Scores and totals like any game mode |
| Sound | 2,342 `se_*` `SoundEffect` globals; `play` is virtual on GnR (`GnrSoundEffect`) | Find `play` in the object's vtable and call it |
| Screen | Allegro 5 is a shared library the game imports | Interpose `al_flip_display` and draw on the backbuffer before the real flip |
| Events | ~80 `Hook<HookX_, Arg>::list` globals (ball start, switch dispatch, score, render, keyboard, state change...). Each is a `FastLinkedList`: head `{first, magic 0x45}`, node `{prio, &desc, name, next}`, desc `{fn, name}` | Not used yet; this is how the SDK will take game events |

`ModeManager::manager_list` is empty on GnR: modes are **named globals**
(`slash_solo`, `song_mode`, 22 `SongMode_*` songs, `tour_mode1..3`,
`no_sympathy_for_the_devil`, ...). `jjpmodelist.py` lists all 33 live ones
with name, id and proc id, on any title.

## Files

- `tools/jjp_emu/jjpmodes.c`: the proof mode. Title choices are env vars
  (`JJP_MODS_SWITCH`, `JJP_MODS_SOUND`, `JJP_MODS_SECONDS`, `JJP_MODS_POINTS`,
  `JJP_MODS_INGAME`). It logs to `/jjpe/temp/jjpmodes.log` in the jail.
- `tools/jjp_emu/buildmods.sh`: builds it against the image's glibc.
- `run_game.sh`: `JJP_MODS_SO=/var/tmp/jjpmodes.so` preloads it.
- `tools/jjp_emu/jjpmodelist.py`: the live mode roster.
- `tools/jjp_emu/jjppoke.py`: press a switch by name (hidden runs).

## Run it

```
wsl -u root -- bash tools/jjp_emu/buildmods.sh
wsl -u root -- env PAD_HIDDEN=1 JJP_MODS_SO=/var/tmp/jjpmodes.so bash tools/jjp_emu/watch.sh /mnt/d/Pinball/images/JJP/GunsNRoses-v03.03.iso
wsl -u root -- python3 tools/jjp_emu/jjppoke.py dswitch_coin_1 dswitch_start
wsl -u root -- python3 tools/jjp_emu/jjppoke.py switch_target_jam
```

## Rig fixes made on the way

- **The JJP scripts killed other rigs' games.** `killgame.sh` ran
  `pkill -9 -x game`, and `status.sh` / `swdump.py` counted or read any
  process called `game`, which includes a Spike 2 rig slot's game (a Turtles
  run on rig 2 at the time). They now keep to processes rooted in the JJP jail
  (`jjp_rig_pids`, `swdump.find_pid`).
- **Hidden runs.** `PAD_HIDDEN=1` now gives the JJP rig a private Xvfb, opens
  no switch matrix, and still refreshes the device dump
  (`jjpsw_launch.sh --dump-only`). A stale dump from an older GnR build had
  seeded an empty trough, so Start only asked for money.

## Next: a JJP mode SDK

1. Mode definitions as data (like the Spike 2 mode maker): trigger shots,
   points, timer, sound, screen text. Load them into one generic `jjpmodes.so`.
2. Shots from the switch roster: wrap several dispatch pointers; one mode at a
   time ("our modes run alone"), and yield to the game's own modes and
   multiballs (`ModeManager::any_mode_running`, the modes' `is_running`).
3. Screens drawn with the game's own `Displayable` / fonts instead of
   Allegro's built-in font; lamps through `MultiLEDInsert` / `LampBuffer`.
4. Delivery to a real machine: add `LD_PRELOAD` to the image's
   `scripts/rungame.sh` in a PAD-written ISO. The installer only gunzip-tests
   images, so a modified ISO installs.
5. Other titles: the engine is shared (Godfather has the same `ModeManager` +
   `is_qualified` pattern). Per title, only the switch, sound and screen names
   change, and `jjpmodelist.py` + `jjppoke.py --list` read those off the live
   game. Each title needs its own key.
