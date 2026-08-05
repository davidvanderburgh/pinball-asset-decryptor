# spike2_emu — running the Stern Spike 2 game on a PC

The real Godzilla Pro 1.15.0 armhf game binary, running under `qemu-user` in a
chroot of the card's own rootfs, with every piece of hardware replaced by
`LD_PRELOAD` shims. It boots to attract mode by itself in about 15 seconds, at
1360x768 / 60 fps on the GPU, with working audio, video and switch input.

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
