# JJP (Jersey Jack Pinball) PC emulator rig

Runs a Jersey Jack game on this PC, the way `tools/spike2_emu` runs a Stern
Spike 2 game. Development title: **Willy Wonka v03.03**.

Status as of **2026-08-19**: the game **boots, runs and draws**. It reaches
**attract mode** — verified by capturing its own window and reading the frame
(Wonkavator Multiball, 3D model over an animated sky, 98% of the frame lit).
See *What is proven* and *What is open* below; do not trust anything here that
is not in one of those two lists.

## Why this is a different (and smaller) job than Spike 2

A JJP game is a **native x86-64 Linux ELF** on Ubuntu 21.10, linking Allegro
5.2.8, libavcodec 58 and OpenCV. Three of the Spike 2 rig's largest subsystems
simply do not exist here:

| Spike 2 needs | JJP |
|---|---|
| `qemu-user` + armhf cross-toolchain | **Not needed** — native x86-64 |
| GL bridge (`glbridge.c`, `eglshim.c`, `padglhost.c`) | **Not needed** — Allegro draws through GLX, WSLg serves it |
| Video bridge (`gstvid.c`, `padvidhost.py`, the demand ring) | **Not needed** — the game links libavcodec and decodes its own WebM |

What replaces them is one thing Spike 2 has no analogue for: **the dongle**.

## The dongle is not a check — it is the decryption key

The retail game binary is wrapped by **Sentinel LDK Envelope**. 7,086 of its
8,566 sized functions are **ciphertext at rest**; each is fronted by a 5-byte
`call 0x21b0a60` into a shared decrypt-and-tail-jump trampoline. String
literals are encrypted too. The purple USB key (Sentinel HL, `0529:0001`)
supplies the AES key that decrypts the code.

Consequences, all verified rather than assumed:

* There is **no branch to patch** and **no boolean to flip**.
* An `LD_PRELOAD` stub **cannot** work: `hasp_login` and friends are
  statically-linked *internal* symbols reached by direct rel32 calls with zero
  relocations, so the loader never resolves them through a preloadable object.
* A fake `/dev` node yields `HASP_HASP_NOT_FOUND`.
* `ptrace` trips a second gate: `Debugger detected (E2011)` then a deliberate
  self-`SIGSEGV`. Do not attach a debugger to a live game.
* The key is **per title**. A key for another JJP game will `H0007` on Wonka.

Without the key the game prints exactly one line and exits 1:

```
Sentinel LDK Protection System: Sentinel key not found (H0007)
```

which is the image's own `rungame.sh` "dongle missing" case. A GUI must render
that as a first-class state, not as a crash — it is what the real machine shows.

### The non-obvious half: WSL has no udev

Starting `aksusbd` and `hasplmd` is **not enough**. On a real machine
`/etc/udev/rules.d/80-hasp.rules` does two things when the key appears:

```
SYMLINK+="aks/hasp/%k"                                   ->  /dev/aks/hasp/<kernel>
RUN+="/usr/sbin/aksusbd_x86_64 -c $root/aks/hasp/$kernel"
```

WSL runs no udev, so both must be done by hand or `hasplmd` never learns the
key exists and the game still `H0007`s. `dongle.sh` does exactly this, and it
is the single difference between a failed and a successful boot.

## Usage

Everything runs as root inside WSL. From Windows:

```powershell
usbipd attach --wsl --hardware-id 0529:0001
```

`usbipd` needs a WSL session **already running** or it fails with "There is no
WSL 2 distribution running". Then:

```
wsl -u root -- bash tools/jjp_emu/jail.sh       # overlay + bind mounts
wsl -u root -- bash tools/jjp_emu/dongle.sh     # register key, start daemons
wsl -u root -- bash tools/jjp_emu/audio.sh      # ALSA -> PulseAudio -> Windows
wsl -u root -- bash tools/jjp_emu/display.sh    # resizable window at 1360x768
wsl -u root -- env JJP_DISPLAY=:1 bash tools/jjp_emu/run_game.sh --detach
wsl -u root -- env JJP_DISPLAY=:1 bash tools/jjp_emu/grab.sh out.png

# switches
wsl -u root -- bash tools/jjp_emu/build.sh          # the hardware shim
wsl -u root -- env JJP_DISPLAY=:1 JJP_SHIM=1 bash tools/jjp_emu/run_game.sh --detach
wsl -u root -- python3 tools/jjp_emu/swdump.py --out /var/tmp/devices.json
wsl -e python3 tools/jjp_emu/jjpsw.py --devices /var/tmp/devices.json                                       --pf tools/jjp_emu/wonka_pf_image.png
wsl -e     bash tools/jjp_emu/status.sh         # key=value, for the GUI
wsl -u root -- bash tools/jjp_emu/killgame.sh   # stop, and PROVE it stopped
wsl -u root -- bash tools/jjp_emu/unjail.sh     # tear the jail down
```

`padpath.sh` owns every path. Nothing else may hard-code one.

## The image is never written to

`jail.sh` builds an **overlayfs**: the restored ext4 is the read-only lower, a
tmpfs is the upper. The game writes a great deal on first boot — it renames the
host, renders all 123 operator-manual pages to PNG, renders the T&C and
beta-agreement pages — and all of it lands in RAM and evaporates. The image can
be re-run from a known state forever, and a bad run cannot corrupt it.

The upper is also free instrumentation: `find $JJP_OVL/up -newer <stamp>` is an
exact list of everything a run touched.

## Traps already paid for

* **`pgrep -f /jjpe/gen1/Wonka/game` matches nothing.** The game runs as
  `./game`, so argv[0] is *relative*. That pattern reports a confident 0 over a
  fully live game — it leaked twelve processes and ~4.8 GB before it was
  caught. Match the process **name** with `pgrep -x`, never a full path.
* **`pgrep -c` prints `0` *and* exits 1.** The obvious
  `$(pgrep -c ... || echo 0)` therefore emits *two* lines and corrupts
  key=value parsing. Capture first, then default.
* **Run `alive.sh` from inside WSL.** Git Bash's `pgrep` sees only Windows
  processes, so every pattern misses. Both scripts refuse (exit 2) rather than
  reassure.
* **Git Bash mangles `/mnt/...` paths** passed to `wsl.exe`. Invoke the rig from
  PowerShell, and put real logic in script *files* — `wsl.exe` re-parses its
  command line and eats `$var` and `$(subst)`.
* **CRLF breaks the shebang.** `.gitattributes` pins `*.sh` to LF.
* **Exit 68 is normal on a first run.** The golden disk ships a Guns N' Roses
  hostname; the game renames itself `WONKA-<n>` and asks for a reboot. Run it
  again — the overlay kept the new name.
* **PulseAudio refuses root** with "Access denied": the WSLg socket belongs to
  the desktop user. `jail.sh` copies their cookie into the jail.

## What is proven (2026-08-19)

* The Wonka image restores, loop-mounts read-only, and the jail builds.
* With the key attached and registered, the game **gets past the envelope** —
  `H0007` is gone.
* The game runs **stably**: 3 processes, ~1.17 GB RSS, uptime unbounded
  (killed by us, never crashed).
* It does real work: sets its hostname, renders 123 manual pages, writes
  `net.log` and `audio.log`.
* X **is** reachable from inside the jail: `xdpyinfo` reports WSLg's
  `XWAYLAND0` at 3840x2160.
* `jail.sh` → `dongle.sh` → `run_game.sh --detach` → `status.sh` →
  `killgame.sh` is a verified clean cycle.
* **Audio works**: `audio.sh` routes ALSA at PulseAudio and the game appears
  as a live sink-input (`float32le 2ch 44100Hz`) on WSLg's RDP sink.
  NB a sine test is a known false-negative for the WSLg->Windows hop; judge
  music by ear, not by a tone.
* **A resizable window at native resolution**: `display.sh` runs a nested
  Xephyr at 1360x768, the game fullscreens into it, and CPU falls from ~420%
  to ~170%.
* The game **opens its window and renders**: `MAIN (100%) - Willy Wonka & the
  Chocolate Factory`, 32 threads including six busy `llvmpipe` software-raster
  threads, ~420% CPU, and a captured frame showing live attract mode.
  `grab.sh` reproduces the capture.

## What is open

1. **Still software rendering.** `display.sh` fixed the resolution (1360x768,
   CPU 420% -> 170%) but Mesa is still on `llvmpipe` inside the nested server.
   Hardware GL through WSLg's D3D12 path would be the next win.
2. **Second display not wired up.** Wonka is a two-display title; `display.sh
   --dual` offers the 800x480 "Wonkavision" apron as a second Xinerama screen
   but the game has not been verified to open a window on it.
4. **The game does not open the boards during attract.** Measured: four
   minutes with the shim tracing, `board_opens=0`, `dev_probes=0` — it never
   touches a `/dev` path at all. This is NOT a shim failure. The shim is
   proven by self-test, and `open`/`read`/`write`/`close`/`ioctl`/`access` are
   all IMPORTED symbols in the game's dynsym (211 imported of 18,717), so
   interposition reaches them. Board init is gated behind something not yet
   found — a setting, or a state the game only enters on leaving attract. The
   service menu's switch test (`DiagDedSwitchTest`) is the obvious next place
   to look, but reaching it needs cabinet switches, which is circular until
   the gate is understood.

## See also

`plans/jjp_pc_emulation_plan.md` — the full architecture and phased plan,
including the GUI integration seams and the switch-matrix strategy.
