# spike2_emu — running the Stern Spike 2 game on a PC

A real Stern Spike 2 armhf game binary, running under `qemu-user` in a chroot
of the card's own rootfs, with every piece of hardware replaced by `LD_PRELOAD`
shims. It boots to attract mode by itself in about 15 seconds, at 1360x768 /
60 fps on the GPU, with working audio, video and switch input.

## Any title

The rootfs is the OS partition and carries no title of its own; each game is a
directory under `games/`. `PAD_GAME` picks one:

```bash
PAD_GAME=turtles_pro watch.sh
```

## Straight off the card, with nothing extracted

```bash
PAD_CARD=images/Stern/spike2/jaws_le-1_02_0.Release.16G.sdcard.raw watch.sh
```

`cardmount.sh` puts the card's games partition on a **read-only FUSE mount** and
`run_game.sh` bind-mounts the title into the chroot. No copy, no root, about a
second, and the image cannot be modified. `mount -o loop,offset=` would need
real root; fuse2fs does not, and `apt-get download` + `dpkg-deb -x` into a
private prefix gets fuse2fs without a package manager or a password. Extraction
still works and is still the faster option for a title you run constantly.

## Titles

| title | state |
|---|---|
| Godzilla Pro 1.15.0 | full: attract, video, audio, switches, coils, artwork playfield |
| TMNT 1987 Pro 1.59.0 | attract, video, audio, switches, coils; schematic playfield; one Tech Alert (node 2 not registered) |
| Elvira's HoH 1.13.0 | boots, 60 fps, switch input works, reaches its Guided Setup |
| Jaws LE 1.02.0 | boots and renders, switch table found (109); still crashes in libc during scene load |

Jaws is the one that does not work. It dies in `memcpy` with a null
destination, called from the game at `0x66ebb4`, after 125 scene loads: an
object's virtual "ensure capacity" at vtable+8 returns without setting the
buffer pointer at `this+32`, and the game memmoves into it anyway. Reporting a
realistic 1 GB of RAM (`PAD_MEMTOTAL_KB`) was the obvious theory and it made no
difference at all - same address, same 125 scenes.

What the rig works out about a title by itself:

| | |
|---|---|
| the switch table | found in the heap at run time by SHAPE (`sw_find_table`), because the address differs per title and the layout does not |
| node firmware version | read off the `.hex` filenames the title ships beside its binary |
| device positions | scanned out of the binary by `devicexy.py`, seeded from the image-name strings rather than an address window |
| playfield artwork | the title's own `assets/nuk/images/Test/*_playfield.png` |

**Not every title has positions.** Godzilla Pro 1.15.0 ships a graphical device
test mode - a playfield drawing and an XY record per switch, coil and insert.
TMNT 1.59 ships neither: no `images/Test`, and "playfield" appears in its binary
only inside adjustment help text. So the playfield window draws artwork when a
title has it and a schematic switch list (`swtable.py`) when it does not. Both
are clickable and live; only one is a picture.

Anything the shim reads at a hard-coded address is a `TITLE_ADDR`: overridable
per title, checked before use, and switched off rather than fatal when it is not
mapped. That is not tidiness - the first attempt at a second title died 0.06 s
in, inside a printf, reading Godzilla's audio gate.

**`plans/spike2_pc_emulation_handoff.md` is the authoritative document.** It is
not in git (`plans/` is ignored); this README only covers what you need to run
the thing. Everything about *why* any of it is shaped this way — and the long
list of confident conclusions that turned out to be wrong — lives there.

## Layout

| | |
|---|---|
| Hardware shim (ARM, `LD_PRELOAD`) | `hwshim.c`, `alsastub.c`, `gststub.c`, `gstvid.c`, `padsw.h`, `padvid.h` |
| GL backend A, software raster | `glraster.c` |
| GL backend B, the bridge (default) | `glbridge.c` + `padglhost.c` (native x86-64), `padgl.h` |
| EGL, either backend | `eglshim.c` |
| Host decoders / players | `padvidhost.py` (video), `playaudio.sh` (audio) |
| Virtual playfield (Windows) | `playfield.py`, `coilact.py`, `plunge.py`, `swpoke.py` |
| Device maps and decoders | `devicexy.py`, `ledio.py`, `leddecode.py`, `coildecode.py`, `padled.h` |
| Build | `build.sh`, `buildgl.sh`, `buildbridge.sh` |
| Run | `watch.sh`, `runbridge.sh`, `nbrun.sh`, `verify2.sh`, `verify3.sh` |
| Safety | `alive.sh`, `killgame.sh`, `runlim.sh` |

Everything else is an instrument. They were written one at a time against a
specific wrong answer, and the handoff says which.

## Running it

All of these are `wsl -e bash <path>/<script>`, from this directory:

```bash
build.sh          # the hardware shim
buildbridge.sh    # the GL backend  <- run this one last, see below
watch.sh          # WATCH IT: a real window on the Windows desktop, keyboard drives it
alive.sh          # what is still running. MUST print 0 after every run
killgame.sh       # emergency stop
```

`buildgl.sh` and `buildbridge.sh` **both write `libGLESv2.so.2`**, so whichever
ran last decides which backend is live. Re-run the one you want before measuring.

## Three rules that are not negotiable

- **Never wrap a run in `timeout`.** It signals only its direct child, which
  here is a `setsid` wrapper, so the guest survives it and spins at ~140% CPU
  forever. Use `watch.sh`'s own minute cap, or `runlim.sh`.
- **Run `alive.sh` after every run** and confirm it prints 0. An orphaned guest
  is invisible and expensive.
- **Bracket `pkill` patterns** — `pkill -f padvidhost.py` from inside
  `wsl -e bash -c '...'` matches the shell's own command line and kills it.
  Write `pkill -f "padvidhost[.]py"`.

## The coin door interlock, which explains a whole class of "it does nothing"

The emulated machine keeps the real one's interlock and it is not optional:

- **Coin door CLOSED** (switch 33 held, the default) — 48V is live, so coils
  fire. The service buttons are locked out; pressing Enter does nothing.
- **Coin door OPEN** (switch 33 released) — the service menu works. 48V is off
  and the game says so on its own screen: *48V DISABLED / CLOSE COIN DOOR*.
  **No coil can fire in this state**, which makes a perfectly working playfield
  look broken. The playfield window says so in the status bar.

You can close the door *while in the menu* to get both at once, which is how the
coil frames were captured. To see coils fire without playing: close the door,
open the trough switches so the balls look missing, press Start — the game puts
up LOCATING PINBALLS and ball-searches on an 8.3 s cycle. `coildecode.py` reads
the result out of a `PAD_COIL_PROBE=1` capture.

## Requirements

WSL with `qemu-user-static` (binfmt `qemu-arm` registered with the **F** flag) and
`gcc-arm-linux-gnueabihf`. The guest rootfs is extracted from the card image to
`/home/david/spike2root`; the handoff has the `debugfs` recipe, and a warning
that the obvious version of it is incomplete in two ways that each cost an
investigation.

## Paths

The scripts carry this directory's absolute path, because they are invoked from
WSL against a Windows-side checkout and there is no reliable relative anchor.
They were rewritten when the rig moved out of `c:\tmp\spike2_emu` into the repo;
if you move it again, the path appears in 44 files and a single `sed` fixes it.
