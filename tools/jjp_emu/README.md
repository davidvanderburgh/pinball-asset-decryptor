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

# switches, LEDs and coils
wsl -u root -- bash tools/jjp_emu/build.sh          # shim + CUSE daemon
wsl -u root -- bash tools/jjp_emu/jjpcuse.sh start  # REAL /dev/jjp* devices
wsl -u root -- env JJP_DISPLAY=:1 bash tools/jjp_emu/run_game.sh --detach
# The playfield photo is decrypted out of the MOUNTED title, never checked in -
# a hard-coded Wonka image drew a Wonka playfield for every game.
wsl -u root -- python3 tools/jjp_emu/pfimage.py --root /var/tmp/jjp_*/root                                       --out /var/tmp/pf.png
wsl -u root -- python3 tools/jjp_emu/swdump.py --out /var/tmp/devices.json                                       --pf /var/tmp/pf.png
wsl -e python3 tools/jjp_emu/jjpsw.py --devices /var/tmp/devices.json                                       --pf /var/tmp/pf.png
# ...but normally you never type any of that: watch.sh opens the matrix itself,
# and jjpsw_launch.sh does the dump + photo for you.
#
# jjpsw.py shows the playfield photo carrying EVERY placed device - switches
# (blue circles, click to pulse, right-click to latch), lamps (brightness drawn
# as opacity) and coils (amber diamonds that flash when the game fires them) -
# beside a LABELLED table of the switches the title actually uses, grouped
# Cabinet / Playfield / Mechanism.  Hovering any marker raises a tooltip AT THE
# POINTER.  The whole 64-byte IN frame is driven, so the direct/cabinet switches
# below the matrix (start, flippers, coins) work too; 1=Start, 5=Coin,
# arrows/A/'=flippers, Space=Plunge, D=Drain (Shift=latch, keys need this window
# focused).  Each key is shown in its own switch's row and on the ball buttons.
# The photo scales with the window (keeps aspect; needs python3-pil.imagetk) and
# the window's size and position are remembered between runs
# (~/.jjp_matrix.json).
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
* **Switches, LEDs and coils are live.** With CUSE devices present the game
  opens them immediately and drives them at ~1 kHz: 382,506 frames in and
  382,512 out in one 40 s run, 6.15 M LED writes. Injecting the six trough
  switches flips the game's own `Switch` objects (offset 62 goes 0 -> 1, 64
  takes a timestamp), so the whole loop - UI, shared memory, character device,
  game - is verified end to end.
* The game **opens its window and renders**: `MAIN (100%) - Willy Wonka & the
  Chocolate Factory`, 32 threads including six busy `llvmpipe` software-raster
  threads, ~420% CPU, and a captured frame showing live attract mode.
  `grab.sh` reproduces the capture.

## The game window remembers its monitor

The game runs inside a nested Xephyr server and **Xephyr's own window is an
ordinary window on the Windows desktop** — but nothing persisted where it was,
so every launch put the game wherever the compositor chose. On a multi-monitor
desktop that is usually the wrong screen.

**Xephyr cannot position itself.** Its `-screen WxH+X+Y` and `-origin X,Y` place
a screen inside the *virtual X screen* (Xinerama), not the host window.

### It has to be moved through X, and that took two wrong turns to learn

The first version used Win32 `SetWindowPos` on the WSLg window. It cannot work,
and the measurements say why:

| | before | after a Win32 move | back |
|---|---|---|---|
| what **Windows** reports | 508,4 | 628,94 | 508,4 |
| what **X** reports | +800+65 | +800+65 | +800+65 |

Windows moved the window; **Weston never heard about it**. The two then disagree
about where the surface is, which is what left a window that could no longer be
dragged by its title bar. An earlier attempt that also restored the **size**
was worse: it killed the nested X server outright —

```
X connection to :1 broken (explicit kill or server shutdown)
XIO: fatal IO error 2 on X server ":1"
```

— and took the game with it. Before dying it went black, because the host window
ended up 957x768 while its X screen was still 1360x768 and WSLg painted the
mismatch black, while the X content underneath was perfectly healthy (98.8%
non-black in a `grab.sh` capture).

An **X** move propagates both ways — `xdotool windowmove` took X from +800+65 to
+306+147 and Windows followed, 508,4 → 179,59 — so the compositor stays in step
and the window keeps behaving like a window. `winpos.sh` is therefore entirely
in X coordinates and never consults the Windows side.

**This needs `xdotool`** (`apt-get install -y xdotool`), the rig's one addition
beyond `xserver-xephyr`. Without it both halves no-op with a message rather than
failing a launch.

`windowmove` takes a *frame* coordinate while `getwindowgeometry` reports the
window's, so asking for the remembered number lands close but not on it. Rather
than hard-code a decoration size every WM would disagree about, restore moves,
measures, and corrects by the error — it converges in one step and needs to know
nothing. Verified end to end: parked at 104,126, stopped, relaunched, came back
at 104,126.

`winpos.sh save` runs **before** anything kills Xephyr (there is no window left
to ask afterwards — `stop.sh` step 0, and `display.sh --stop` before its
`pkill`); `restore` runs once the display is up. Both are `|| true`: a window
position is a convenience and must never hold up a launch or a teardown. A
window that is not on screen is refused rather than remembered, so it cannot
overwrite a good position with an invisible one. State lives in
`/var/tmp/jjp_window.json`, and only a position — never a size.

## Two coordinate spaces, and the calibration between them

**Switches are in playfield-image PIXELS. Lamps are in INCHES.** Mixing them
silently piles every lamp into the top-left corner, and nothing in the game
states the relationship. `swdump.py` solves it from devices that share an
*exact* name suffix (`switch_jet_left` / `lp_jet_left`), which is the only
evidence that two devices sit at the same physical spot:

    x: px = 17.057 * in + 16.58
    y: px = 17.057 * in - 20.94

Matching on keyword *overlap* was tried first and is a trap - it paired
`switch_spinner` with `lp_factory_tour_1` and produced a 51 px mean error. The
fit is RANSAC'd and reports its own inliers, outliers and residuals on every
dump, so a bad calibration announces itself instead of quietly skewing the
markers.

### The two scales must be EQUAL, and getting that wrong cost us

An earlier version of this file recorded `y = 18.880 * in - 40.37` and
concluded that "the photograph is not a uniform scaling of the playfield body".
That was **wrong**, and believing it hid a real bug for months: every LED
drifted progressively downward, by 27 px at mid-playfield and **55 px** at the
SHOOT AGAIN insert between the flipper tips.

A photograph has **square pixels**, so one scale has to serve both axes. The
per-axis fit produced 17.06 across and 18.88 down because a lamp and a switch
that share a name are not always the same spot: `lp_inlane_left_1` is the arrow
*insert* and `switch_inlane_left_1` is the *rollover*, which sits ~2.3 in
**down-lane** of it. That offset runs along the lane, so it lands almost
entirely in Y and cancels in X - and because the usable pairs bunch into two
clusters (jets high, lanes low) it does not average out, it *tilts* the fit.
The jets, by contrast, really are co-located: lamp and switch agree to ~1 px.

Which scale is honest is decided by the game's own numbers, not by preference.
`hook_playfield_width/height` say the playfield is 20.25 x 46.0 inches, so a
scale implies a playfield of a given pixel size, and one that does not **fit**
the photograph is impossible:

| scale | implied playfield | fits a 385x768 photo? |
|-------|-------------------|-----------------------|
| 17.06 | 345 x 785 px      | yes                   |
| 18.88 | 382 x **868** px  | no - taller than the picture of it |

`_square_pixels()` therefore forces one scale onto both axes, keeps the one
whose playfield fits, and pins the corrected axis at the topmost anchor (the
jets - the pairs that genuinely are co-located). It records `square_pixels`
plus the `raw_scale`/`raw_offset` it replaced in the dump, so a bad correction
announces itself. `swdump.py --pf` takes the photo **for its size only**;
without it the correction still runs, just without that check.

Verified against six inserts measured by eye off Wonka's photo (SUPER SPINNER,
SUPERX 2X/3X/4X/5X, SHOOT AGAIN): **mean error 38.5 px before, 3.4 px after**.

Do not reach for an affine or homography fit here. Both were measured: an
affine fit's largest corrections land on the already-accurate *top* and it
barely moves the bottom, and eight clustered pairs cannot support a homography.

## What is open

1. **Still software rendering.** `display.sh` fixed the resolution (1360x768,
   CPU 420% -> 170%) but Mesa is still on `llvmpipe` inside the nested server.
   Hardware GL through WSLg's D3D12 path would be the next win.
2. **Second display not wired up.** Wonka is a two-display title; `display.sh
   --dual` offers the 800x480 "Wonkavision" apron as a second Xinerama screen
   but the game has not been verified to open a window on it.
4. **LED page format is not decoded.** Live LED traffic now exists and
   animates (2.3 M writes in 40 s, 31-51 bytes changing every half second),
   but the byte layout inside JJP's 64-byte LED pages is still unknown - a
   recurring `3f 0c` marker suggests a page header. The switch matrix layout
   was *derived and verified*; the LED mapping is still PROVISIONAL and the
   UI labels it as such. The matrix UI renders each lamp as its provisional
   RGB colour (three bytes at `index*3` in the concatenated LED frames) rather
   than a bare on/off. Brightness is drawn as **opacity** - the lamp composited
   over the photograph at an alpha taken from its level - because Tk has no
   alpha channel and painting the raw value made every level below about half
   look like the same flat near-black blob.

   **Measured 2026-08-20, against 15,393 samples of live traffic.** Three
   things came out of it, and the first two were bugs:

   * **full scale is 0x80, not 0x3f.** The payload runs 0x00..0x80 and 2.5% of
     bytes sit above 0x3f, so the old `*4` scaling pinned everything from 0x40
     up to 255 - the whole bright half of the range collapsed onto one colour
     and a lamp climbing through it appeared to snap to full. `led_level()`
     now scales by the measured `LED_FULL`;
   * **the pages have to be READ faster than they are drawn.** The game
     rewrites the LED frame ~2,139 times a second cycling 11 pages, and the
     shim keeps only the LATEST frame, so one look yields one page. Reading
     once per 100 ms repaint saw ~6 pages a second - each lamp refreshed about
     every 1.8 s, which aliases every fade into a jump. A separate
     `LED_POLL_MS` loop at 100 Hz gathers pages while the repaint stays at
     10 Hz; measured, that is 110 byte-changes reaching the screen per draw
     instead of 12. (The complete fix is for the *shim* to keep a buffer per
     page rather than one frame - a C change that cannot be made while a game
     is running.)
   * **the triplet really is R,G,B.** During attract the GI lamps read bright
     and warm (`gi_left_1` -> `70 00 10`), 154 of 164 placed lamps are
     non-zero, and each triplet's channels SUM to a quantised total (0x80,
     0x40, 0x3f, 0x15) - a colour split across three channels at one intensity.

   What is still NOT verified is the page ORDER (pages are concatenated by id,
   which is an assumption), so which lamp owns which triplet is only
   self-consistent, not proven. Nailing that needs the correlation pass: light
   one lamp from the game's own test menu and watch which byte moves.
5. **Direct / cabinet switches now have a route** (was item 5's open problem).
   The live `Switch` objects show the IN frame is 37 bytes wide, not 16: bytes
   0..3 are the direct switches (`dswitch_start`, flippers, coins, menu, tilt),
   4..19 the verified matrix, 20..36 stepper/topper. The shim used to fill only
   4..19, so the game read start/flippers/coins as permanently open - which is
   why keyboard start did nothing. Both the shim and the CUSE daemon now drive
   the WHOLE frame (`in_frame` in jjpshm.h) and serve it for the IO *and* CAB
   boards, since which one carries a given cabinet switch is not known and
   serving both is free. NEEDS A LIVE CONFIRM: pressing `1` should start a game.
6. **Coils barely move in attract**, as expected: the I/O out frame holds a
   steady `0x42` at byte 9 and nothing pulses. Verifying the coil half of the
   frame needs an actual game in progress.

## CORRECTED 2026-08-19: the boards WERE being opened

An earlier version of this file said "the game does not open the boards during
attract", measured over four minutes with the LD_PRELOAD shim tracing. That
conclusion was **wrong**, and the way it was wrong is worth keeping:

*The instrument was never connected.* The shim was mapped into the game and
`LD_PRELOAD` was set in its environ, but the Sentinel envelope resolves libc
for itself - it imports `dl_iterate_phdr`, `dladdr`, `dlsym` and `dlvsym` -
instead of going through the PLT/GOT the loader had pointed at the shim. The
control experiment is what exposed it: across a 40 s run the shim logged **zero
`open()` and zero `fopen()`** while the game opened thousands of asset files.
A hook that sees nothing at all is not evidence of absence; it is a broken
hook.

With real CUSE devices present the game opens them **immediately** -
`io_fd = 24`, `led_fd = 25`, 8 open fds, and 69,500 frames read and written in
40 s (it polls at ~1 kHz). The boards were never gated behind anything. They
simply did not exist.

## See also

`plans/jjp_pc_emulation_plan.md` — the full architecture and phased plan,
including the GUI integration seams and the switch-matrix strategy.
