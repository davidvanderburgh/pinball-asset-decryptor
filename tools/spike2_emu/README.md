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
| Elvira's HoH 1.13.0 | boots, 60 fps, switch input, reaches its Guided Setup |
| Jaws LE 1.02.0 | boots, 60 fps, switch input, clears Tech Alerts, reaches its Guided Setup |

All four boot, render at 60 fps and take input. EHOH and Jaws stop at Guided
Setup because that is what a machine with no saved settings does on first boot,
not because anything is wrong.

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

### Where those tables come from, and where they do not

`mktables.py` builds them, per title, into `$PAD_TABLES/<title>/` — under the
rootfs by default, so the WSL side that writes them and the Windows playfield
window that reads them name one directory. `watch.sh` runs it before opening
the window, and the window runs it itself if it finds nothing.

| | |
|---|---|
| `playfield.png` | copied out of the title's own assets |
| `device_xy.txt` | the device table in the game ELF |
| `led_io.txt` | derived from `device_xy`; the wire enumeration only ever *checked* it |
| `switch_list.txt` | the shim's `[sw]` dump, i.e. it needs a run |
| `switch_xy.txt` | the two joined on the device NAME |

**Three of the five need no run at all**, which is what lets a title show
artwork, inserts and coils the first time it boots. The switch half is the one
exception and cannot be made otherwise: the game builds its switch table on the
heap, so the id belonging to a name is not in the binary anywhere. It is cached
per title, so only the first run of a title waits for it.

**These were checked into git until 2026-08-06, and only Godzilla's existed** —
so every other title got a schematic and it read like a property of the title
rather than of the repository. The artwork was worse: it sat here ignored by
this directory's own `*.png` rule while `gameinfo.py` claimed it was committed.
Nothing under `games/` is generated into the checkout any more.

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
| Switch block layout | `padsw.h` (C), `padsw.py` (the scripts) — three regions, one writer each |
| Device maps and decoders | `devicexy.py`, `ledio.py`, `leddecode.py`, `coildecode.py`, `padled.h` |
| Where anything is | `padpath.py` / `padpath.sh` (paths), `gameinfo.py` (titles), `parts.py` (partitions) |
| Per-title tables | `mktables.py`, built from the card — see above |
| First-time setup | `rootfs.sh`, `getboot.sh`, `gethex.sh` |
| Build | `build.sh`, `buildgl.sh`, `buildbridge.sh` |
| Run | `watch.sh`, `runbridge.sh`, `nbrun.sh`, `verify2.sh`, `verify3.sh` |
| Safety | `alive.sh`, `killgame.sh`, `runlim.sh` |

Everything else is an instrument. They were written one at a time against a
specific wrong answer, and the handoff says which.

## Running it

All of these are `wsl -e bash <path>/<script>`, from this directory:

```bash
watch.sh          # WATCH IT: a real window on the Windows desktop, keyboard drives it
alive.sh          # what is still running. MUST print 0 after every run
killgame.sh       # emergency stop
build.sh          # the hardware shim      \ both built on demand; see below
buildbridge.sh    # the GL backend         /
```

**`watch.sh` and `runbridge.sh` build what they need.** `ensurebuild.sh` checks
the hardware shim and both halves of the GL bridge against a digest of their
sources: missing gets built and stops the run if it cannot be, stale gets
rebuilt and never blocks, and neither happens while a run is live. The builds
above are for building deliberately, not because a start needs them.

**A failed build is reported by its errors, not by its last eight lines.**
`gcc` compiles every source before it gives up, so the errors sit wherever the
broken file was on the command line and the tail belongs to whichever file came
last — the one arrangement a tail can never show is an error early with noise
after it, which is the common one. `_pad_build` republishes the matching error
lines first, keeps the tail only as the fallback when nothing matches, and
writes the full output to `$TMPDIR/pad-<script>.log`, which it names in the log.
Both builders pass `-Werror=implicit-function-declaration` so GCC 13 gives
GCC 14's answer here rather than on a user's newer distro.

`buildgl.sh` and `buildbridge.sh` **both write `libGLESv2.so.2`**, so whichever
ran last decides which backend is live. Re-run the one you want before measuring.

## Four rules that are not negotiable

- **Never wrap a run in `timeout`.** It signals only its direct child, which
  here is a `setsid` wrapper, so the guest survives it and spins at ~140% CPU
  forever. Use `watch.sh`'s own minute cap, or `runlim.sh`.
- **Run `alive.sh` after every run** and confirm it prints 0. An orphaned guest
  is invisible and expensive.
- **Anything a run starts goes in `alive.sh` the same day.** That list is the
  rig's only definition of "clean", and it has twice been out of date: once it
  reported `TOTAL STILL RUNNING : 0` over seven leaked Windows-interop stubs
  and three orphaned card mounts. `killgame.sh` and `status.sh` now ASK
  `alive.sh` (`--total` / `--procs`) instead of keeping their own copies, so
  there is one list and one place to add to.
- **Bracket `pkill` patterns** — `pkill -f padvidhost.py` from inside
  `wsl -e bash -c '...'` matches the shell's own command line and kills it.
  Write `pkill -f "padvidhost[.]py"`.

### When a window will not close

A window that WSLg is still painting after its X client has gone cannot be
closed by clicking its X (there is nothing left to receive the close) and
`msrdc` refuses `Stop-Process`. `wsl --shutdown` is the only cure found; the
app's **Restart WSL…** button on the Emulate tab does it for you. Note that
synthetic closes do NOT work as a test either: `WM_CLOSE` and `SC_CLOSE` posted
to a RAIL window from Windows are both ignored, the same UIPI class as the
`SendInput` and PrtScn blocks documented elsewhere.

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

**Linux, or Windows with WSL.** `qemu-user-static` (binfmt `qemu-arm`
registered with the **F** flag), `gcc-arm-linux-gnueabihf`, `e2fsprogs`,
`fuse3`, and `python3-tk` for the playfield window. Then, once:

```bash
rootfs.sh <card.raw>    # the guest rootfs, from the card. No root needed.
```

On **Ubuntu**, `qemu-user-static` is published in the `universe` component and
the other three are in `main`. A distro with universe switched off therefore
answers `E: Package 'qemu-user-static' has no installation candidate` — apt
knows the name and has no version — and, because `apt-get install a b` is all
or nothing, installs none of the others either. `setupcheck.sh` reports that as
`nocand` and `universe=0` rather than only as "missing", and `setupfix.sh`
turns universe on before it installs anything.

That is the whole of it: the ARM hardware shim and the GL backend are compiled
by the first run that needs them. They used to be two more steps printed as
advice, which is how a user reached `env: './padglhost': No such file or
directory` at their first start.

`rootfs.sh` is the step that used to be missing: `run_game.sh` chroots into
`$PAD_ROOT` and nothing in the repository created it, so the recipe lived only
in a planning document that is not in git. It reads the partition table rather
than assuming one card's offsets (`parts.py`), extracts the OS partition with
`debugfs` — no loop mount, no sudo — and finishes with the boot partition,
which `rdump` of the OS partition never touches and whose absence is a `GAME
VALIDATION ERROR #3`. It refuses to extract to a `/mnt` path, because drvfs
cannot hold symlinks and `ld-linux.so.3` would silently vanish.

It does **not** extract a title. `PAD_CARD=<image> watch.sh` runs one straight
off the card in about a second; `rootfs.sh --game <title>` is there for a title
you run constantly.

Every run then checks that the guest can actually **start a program** — a user
namespace, a chroot, `/bin/sh`, about 25 ms — before it starts one. A rootfs
that exists is not a rootfs that runs, and all four ways it can fail (an
extraction that stopped part way, a missing ARM loader, no `qemu-arm`
registration, a registration without the **F** flag) produce the same single
line and no other clue:

```
chroot: failed to run command '/bin/sh': No such file or directory
```

The first two are rebuilt from the card you are already running; the last is
repaired by putting a copy of the interpreter inside the guest, which needs no
root. Only registering `qemu-arm` needs root, and that one is named with the
command for your machine — WSL loses the registration on every restart unless
the distro boots `systemd`.

### WSL and Linux are not two ports

This is a Linux program. `run_game.sh`, `cardmount.sh`, `padglhost.c` and
`padvidhost.py` contain nothing Windows-specific at all — the chroot, qemu-user,
the node bus, the card mount and the renderer are the same code either way.
What WSL needs on top are **workarounds, not features**, and there are exactly
two:

| | |
|---|---|
| the playfield runs as a **Windows** process | this WSL has no Tk of any kind, and installing one needs a sudo the rig does not have |
| audio bridges to a **Windows** player | the WSLg→Windows audio hop degrades music, while every instrument inside WSL reads clean |

On a Linux desktop both simply go away: the playfield is a local Tk window and
audio goes straight to PulseAudio. `padpath.sh`'s `pad_is_wsl` (and
`padpath.py`'s `is_wsl()`) is the **one** place that decides which of the two
applies — `playaudio.sh` used to carry its own copy of that test, which is the
duplication this rig's own rules forbid.

**`PAD_FORCE_NATIVE=1` makes a WSL session take the Linux branches**, which is
the only way to exercise them from a Windows machine. It is how the Linux path
was tested; what it cannot show is the playfield window itself, because the
distro that needs the workaround is by definition the one with no Tk.

### macOS: in a container, watched over VNC

`qemu-user` translates *Linux* syscalls, and `unshare`, user namespaces and
`chroot` into an ELF rootfs are Linux kernel features. So macOS is not a port
that could be written — running the rig there means running Linux there, and
`docker/` is that Linux.

```bash
docker/padbox.sh --build                 # once
PAD_CARD=~/cards/godzilla.raw docker/padbox.sh watch.sh 30
open vnc://localhost:5900                # Screen Sharing; nothing to install
```

**The container runs its own X server** and exports only the finished
framebuffer. Forwarding X to XQuartz instead would push every frame across the
VM boundary as uncompressed protocol, ~4 MB a frame at 1360x768.

**Software rendering is not the bottleneck and never was.** Measured on a
headless Xvfb with `GALLIUM_DRIVER=llvmpipe`, which is what a container with no
GPU gets: guest **57.1 fps**, renderer **59.9 fps**. The 1 fps figure this
project remembers is `glraster.c` running *inside* the emulated ARM guest, which
the GL bridge replaced and which none of this uses.

Three container details are load-bearing, all in `padbox.sh`:

| | |
|---|---|
| `--security-opt seccomp=unconfined` | Docker's default profile blocks `unshare`, so the guest could never get its mount and PID namespaces |
| `--cap-add SYS_ADMIN --device /dev/fuse` | `cardmount.sh`'s read-only card mount |
| `-p 127.0.0.1:5900` | the VNC display is an unauthenticated view of the machine; loopback only |

**KNOWN, and see REMAINING item 30: a container run ends by itself after about
60 seconds.** Everything is healthy until it does — full frame rate, clean
teardown — and `watch.sh`'s three exit paths all stay silent, so it is taking a
signal from outside. It was seen on Docker Desktop for **Windows**, which is not
the target; macOS uses a different VM layer entirely, so the first question is
whether it happens there at all. Video also does not stream in the container,
unexplained.

## Paths

Nothing here carries a path to a particular machine any more. `padpath.sh`
(sourced by the scripts) and `padpath.py` (imported by the Python) are the only
two files that know:

| | | |
|---|---|---|
| `RIG` | this directory | from `BASH_SOURCE` / `__file__` |
| `ROOT` | the guest rootfs | `PAD_ROOT`, else `~/spike2root` |
| `TABLES` | derived per-title data | `PAD_TABLES`, else `$ROOT/dump/tables` |
| — | any of those as **Windows** sees it | asked of `wslpath`, never built by pasting strings |

That last row is the one that reads like a detail and is not.
`\\wsl.localhost\Ubuntu\...` was written out in four files: it names a distro
that need not exist, under a prefix older WSL spells `\\wsl$`. `wslpath -w`
knows the right answer for the running system, and `watch.sh` passes the
translated values across interop through `WSLENV`'s `/p` flag, so the playfield
window normally has them already and asks nothing.

**This used to be 187 files carrying `/home/david` and 51 carrying the
checkout's absolute path**, and this section used to say it was 44 files and one
`sed`. Both halves of that were wrong, which is roughly the point: a count
nobody re-derives goes stale, and a path nobody derives never works anywhere
else. If you move the rig now, nothing needs editing.

Two things to know if you add a script:

- **Source `padpath.sh` before using `$RIG` or `$ROOT`**, with
  `. "$(dirname "$0")/padpath.sh"`.
- **A quoted heredoc does not expand anything**, so `$ROOT` inside `<<'PY'`
  reaches Python as five literal characters. Pass it through the environment
  (`export PAD_ELF=...` then `os.environ["PAD_ELF"]`), which is what the
  forensic scripts here do. Same trap for `pkill -f '...'`: single quotes stop
  the pattern expanding and it silently matches nothing.
