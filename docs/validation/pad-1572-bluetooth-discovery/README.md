# PAD-1572: spike-pinball-bluetooth runtime discovery on game programs PAD has changed (2026-11-25)

The author asked us to test his commit `6d1381a` ("feat(discovery): resolve game interfaces on machine with validated
caching") against `main`. Before this commit his `menu.so` admitted only exact executable hashes, so any game program
PAD had changed got no Bluetooth entry (PAD-1554/PAD-1559 notes). The commit finds the interfaces it hooks by
instruction fingerprints at start-up instead. No change to PAD in this ticket.

## Result

| Build (Spike 2, emulator) | His log | Bluetooth row / menu |
| --- | --- | --- |
| Godzilla Pro 1.16, stock (control) | discovery compatible (scan), menu hooks armed | yes / opens |
| Godzilla Pro 1.16 + a game program built by PAD main: longer text in an appended segment, MUSIC MODE row | discovery compatible, menu hooks armed | yes / opens |
| Godzilla Premium Heisei V1.99D + modes card, his menu.so preloaded LEFT of our runtime (wrong order, first pass) | discovery compatible, **immutable guards mismatch** | no |
| the same card in the card's own order (his `run-live.sh`: our runtime left of `menu.so`) | discovery compatible, menu hooks armed | yes / opens |

Identification took 150-175 ms per boot in the emulator (Foo Fighters LE 1.04: 2.1 s, a cold scan).

Desk check (`probe.sh`, `cmp2.sh`: his own `tests/discovery_probe.c` built for x86): every program below resolves to
the same 60 addresses as stock: six built with main by `mkelf.py` (Pro and LE; text, menu row, both) and four older
PAD builds (Music Mode Pro/LE, Heisei 1.16 builds). Heisei on 1.15 does not resolve: 1.15 is not a version he supports.

## The preload order, and the start menu both of us add to

The first pass reported a clash ("immutable guards mismatch") on the Heisei card. That was the rig's order, not a
card's: his `run-live.sh` puts `/usr/local/padmode/mode.so` LEFT of `menu.so`, and glibc runs the rightmost preload's
set-up first, so on a machine his menu checks the game's original code and then our runtime hooks. In that order both
arm (`menujob.sh` with the card's order: runtime then `menu.so`).

What did clash is the start menu ("CHOOSE YOUR MODE OF PLAY"), which both add a choice to: his Bluetooth, our MODE
CHALLENGE / Prolonged Competition / teams. His picker copies the menu's list once, at the menu's first button read,
and points the game's reads at the copy; it appends a row that borrows the selected mode's index, and when the list's
length is not its own it takes it for a new menu and appends again.

- Godzilla (a menu of game-mode indices, hooked at a frame site): our entry went into the game's stack list after his
  copy was taken, so it drew blank; and the count change made his picker append its row again, leaving a stray
  STANDARD. FIXED in the runtime: the entry goes into the list the game reads (`frame_read_list_at`: every 32-bit frame
  site ported is `add rB, rB, rC, lsl #2; ldr rD, [rB, #-k]`, so the list is rB - k at the hook) and takes his row's
  place without growing the list (`frame_append_at`): his picker puts its row back after ours. Same for Prolonged
  Competition and teams at the same site. Proven: Heisei with modes - Standard, Competition, King of the Monsters,
  CHALLENGE stepping all 13 modes, Bluetooth; MINILLA picked starts its mode; Action on Bluetooth opens his menu.
  Godzilla Pro with Prolonged Competition the same (COMPETITION UNTIL POWERED OFF, then Bluetooth).
- Deadpool, Foo Fighters and the other menus of RECORDS (`challenge_menu` sites, ~30 titles): his picker reads its copy
  from the first button read, before any point we hook, and our entry left a choice that closed the menu. The runtime
  now leaves its entry off such a menu while his menu is loaded (`start_menu_yields`, which looks for
  `/spikebt/menu.so` in the process), and on any 64-bit program (never run beside his). Proven: Deadpool Pro 1.16 and
  Foo Fighters LE 1.04 with Prolonged Competition cycle Standard, Competition, (Challenge,) Bluetooth cleanly, Action
  opens his menu. Without his menu, unchanged (controls in `final.list`).
- His `switch_edge` call-site wrapper and our `switch_edge` entry hook chain in the card's order (his patches a call to
  it, ours the function).

`final.list` (`menujob.sh`, `rigbatch --speed 1`): nine runs, 9/9.

## Build notes for the author (his CI does not cross-build menu.so)

Built at `6d1381a` with Ubuntu 24.04's `arm-linux-gnueabihf-gcc` 13.3 against the rig root's glibc 2.21 (`buildmenu2.sh`,
`xgcc`). His `scripts/verify-menu-elf.py` passed the first build ("libc imports <= 2.21"), but that build could not load
on the card: `undefined symbol: __clock_gettime64` (64-bit `time_t` default). With 32-bit `time_t`/`off_t`,
`native/discovery.c:736` (`info.st_size > SB_DISC_MAX_FILE`) fails his `-Werror` (`-Wsign-compare`), and with 64-bit
`off_t` the object imports `fcntl64`/`fstat64`, which glibc 2.21 does not export. The build that ran here used 32-bit time and
offsets, that one warning left a warning, and the `fstat` -> `__fxstat` stub glibc 2.21's `libc_nonshared.a` provides.
Every undefined symbol was then checked against the card's own libraries (only `__tls_get_addr`, from the loader, is
left). The helper (`spikebt`) is v0.3.0's: `helper/` and `src/` are unchanged since then.

## Not shown

A real radio. The rig has no Wandboard kernel, BlueZ 4 or adapter. The helper ran its demo backend, so pairing and audio
are his to prove on a cabinet. Spike 3 was not run for this commit.

## Files

`mkelf.py` (main's `_program_text_writes` on a stock ELF), `probe.sh`/`cmp2.sh` (desk probe), `xgcc` + `buildmenu2.sh`
(the menu build), `btjob.sh` + `s2.list` (the rigbatch job and builds), `guards.py` (his guards vs the port's sites).
