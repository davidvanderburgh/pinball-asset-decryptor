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
| Godzilla Premium Heisei V1.99D + modes card, its mode runtime left out | discovery compatible, menu hooks armed | yes |
| the same card as it boots, with its mode runtime | discovery compatible, **immutable guards mismatch; stock game unchanged** | **no** |
| Godzilla Pro 1.16 + PAD's prebuilt mode runtime with no modes | discovery compatible, menu hooks armed | yes |

Identification took 150-175 ms per boot in the emulator.

Desk check (`probe.sh`, `cmp2.sh`: his own `tests/discovery_probe.c` built for x86): every program below resolves to
the same 60 addresses as stock: six built with main by `mkelf.py` (Pro and LE; text, menu row, both) and four older
PAD builds (Music Mode Pro/LE, Heisei 1.16 builds). Heisei on 1.15 does not resolve: 1.15 is not a version he supports.

## The one conflict: PAD's mode runtime and his start-menu picker

With a card's modes in place, PAD's runtime hooks Godzilla's start menu at `0x603d8` (port sites
`challenge_menu_frame` / `comp_menu_frame`, which add the MODE CHALLENGE / prolonged competition entry). His menu's
picker hooks the same loop: tick `0x603b4`, aliases `0x603d0`/`0x60438`, reads `0x603dc`/`0x60440`, and guards
`0x603d0`-`0x603dc` (`guards.py`). The runtime patches those words first, so his load-time guard check refuses and
leaves the game unchanged. That is safe (no crash, game plays) but the card gets no Bluetooth entry. Fixing it
needs the two to share that loop. It is a design decision between the two projects, not a patch to either.

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
