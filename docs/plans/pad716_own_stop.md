# PAD-716: game modes with their own stop logic, taken by a mode of ours

From PAD-710 (a mode in the place of one of the game's own modes counts as that mode): JP Pro's Ctrl Room Virus
Attack, Restore Power and Trex Chase, and Iron Maiden's hurry-ups, run their own stop logic. PAD-710's sweep read
"stopped 0" after the game's stop on them and proved JP Pro on Escape Nublar and Iron Maiden on Rime of the Ancient
Mariner Hurry Up instead. This ticket reads what those stops do and makes a mode in their place count the game's way.

## What the stops do (desk: JP Pro 1.16, Iron Maiden LE 1.18; C:\tmp\PAD-716_*.py)

- **Jurassic Park's cmode STOP (v[24], 0x101674)** asks the mode's own "stopped?" virtuals first (v[31], then v[32]
  (mode, player)) and marks it stopped through its own setters (v[54], then v[55] (mode, value, player)), each called
  only where a class overrides it. JP Pro's `cmode_trex_chase`, `cmode_trex_encounter`, `cmode_trex_rampage`,
  `cmode_ctrl_room_system_boot`, `cmode_ctrl_room_virus_attack` and `cmode_ctrl_room_restore_power` override v[32] and
  v[55]: their stopped byte is their own (+0x137, +0x107, +0x123, +0x107, +0x11f, +0x117; on a co-op game a shared
  one). Their START clears it through v[55]. The take (PAD-710) cleared the framework's +0xc3 instead, which those
  classes never read; so the first take's STOP worked (the byte starts 0) and a second take of the same mode in a game
  found it stopped already and did nothing: no END, no COMPLETED audit. The "stopped 0" PAD-710 read was +0xc3.
- **Iron Maiden's Soul Shard Hurry Up (v[12], 0x983d0)** runs the framework stop (stopped, END, the manager's
  stopped notice), then reports the outcome to the song that started it (`[hurry-up + 0x7c]` = the song's id; the
  song's v[42] with the hurry-up's id and "lost": Fear of the Dark records a won hurry-up at +0xa8 + player), and sets
  its stopped byte back to 0 so it can come round again. Its "stopped 0" is the game's design, not a missed outcome.
  The other Iron Maiden hurry-ups (Rime of the Ancient Mariner Hurry Up, the timed ones) use the framework stop.

## What changed

- `mode_framework.stopped_virtuals`: the guarded vtable loads before the stopped byte's read (the getter) and before
  its write (the setter); `value mode_slot_stopped_get / mode_slot_stopped_set`. Only Jurassic Park LE/Pro 1.16 of the
  39 C++ programs on hand have them (32 / 55). Shipped JP ports carry them; `lines_for` reads a program again for a
  port that has PAD-710's section but not these (older JP builds' ports at card build and derive).
- Runtime (`pad_mode_runtime.c`, PAD-716): `place_stopped` / `place_set_stopped` go through those virtuals where the
  port names them (else the framework byte); the take clears through the setter, as the START does; the end's log says
  `stopped a -> b`, and `(its own stop set it back)` for a 0 -> 0.
- MODE_SDK.md: "Modes with their own stop logic".

## Proof (emulator, hidden, muted; C:\tmp\PAD-716\rig, job.sh + p716test.c over rigbatch)

Each job takes the mode TWICE in one game (the game's START called as its rules call it, a mode file `in_place_of`
with an 8 s clock, won by its clock), with main's runtime (before.so) and this branch's (after.so), and reads the
game's own books after each take: JP's STARTED / COMPLETED audits (the manager's notices: the audit ids the mode's
+0x20 / +0x2c vectors point at), the mode's own stopped byte through v[32]; Iron Maiden's song record.

| build | modes | main's runtime (COMPLETED over two takes) | this branch |
|---|---|---|---|
| JP Pro 1.16 | Trex Chase 119, Trex Rampage 120, Ctrl Room Virus Attack 121, Restore Power 122 | 0 -> 1 (STARTED 0 -> 2: the 2nd stop skipped) | 0 -> 2, own stopped 0 -> 1 each stop |
| JP Pro 1.16 | Escape Nublar 127 (framework byte: the control) | 0 -> 2 | 0 -> 2 |
| JP LE 1.16 | Trex Chase 7, Trex Encounter 8, Trex Rampage 9, Ctrl Room Virus Attack 10, Restore Power 11, System Boot 12 | 0 -> 1 | 0 -> 2 |
| Iron Maiden LE / Pro 1.18 | Soul Shard Hurry Up 0, started by Fear of the Dark (running) | the song's hurry-up won 0 -> 1 at the 1st take; stopped 0 (its reset) | the same; the log: "stopped 0 -> 0 (its own stop set it back)" |

Every job: the game played on after both stops (out_all1, out_im2, out_le1). The Iron Maiden instrument starts the song
through its START and sets the hurry-up's +0x7c to the song's id, as the song does before it starts its hurry-up.
