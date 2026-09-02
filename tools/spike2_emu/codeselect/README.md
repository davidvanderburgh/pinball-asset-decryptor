# codeselect - the Spike 2 boot-time code selector (item 90)

One SD card, several complete game images; at power-up a menu on the LCD lets
the player pick the one that boots. This directory holds the selector program
that draws that menu (with a picture, an animation and a music loop per card,
a click on every move and a confirm sound), reads the buttons, the hook script
that swaps the `/games` mount, and the tests. The card layout and the emulator
side are in `DESIGN.md` and in the rig (`run_game.sh`/`watch.sh`).

```
codeselect.c     main loop, CLI, layout (row of 2-4 cards, carousel beyond),
                 countdown, sounds, the confirm wait, choice/last files,
                 the --snapshot frame (the Multi-boot tab's preview)
gfx.c/.h         software RGBA canvas: rectangles, rounded frames, TrueType
                 text (third_party/stb_truetype.h), RGBA blits, DIRTY-RECT
                 tracking + a packed sub-rect for the upload, 180-degree
                 rotation, P6 PPM
egl_stern.c/.h   Stern's exact EGL/GLES2 bring-up + one textured quad,
                 glTexSubImage2D of the changed rectangle only
art.c/.h         PNG stills and animated GIFs (third_party/stb_image.h, PNG +
                 GIF only), box-downscaled once into the card's art panel;
                 GIFs decode one frame per call
audio.c/.h       WAV loader (PCM 16-bit 44100 Hz 1-2 ch), the 4-voice s16
                 stereo mixer, sink selection, --audio-dump
audio_fifo.c     the emulator sink: the rig's audio FIFO (PAD_AUDIO_PLAY)
audio_alsa.c     the machine sink: the game's ALSA device through the rootfs
                 libasound (hand prototypes), plus the optional mixer_volume
input.c/.h       the button events, the shared 2-sample debouncer
input_hw.c       node bus (/dev/ttymxc1) + cabinet SPI (/dev/spidev1.0)
input_padsw.c    the emulator's keyboard channel file (PAD_SW_SHM)
conf.c/.h        images.conf v2, /data/codeselect.last, the choice file
log.c/.h         stderr + --log file; '[select] ' stdout lines
select.sh        the hardware hook for /etc/init.d/game
images.conf.example
fakebus.py       a fake node bus on a pty (for --input hw without a machine)
test/            the checks `make check` / `make check-hw` run
Makefile
```

## Build

Needs Ubuntu's `arm-linux-gnueabihf-gcc` (13.x), `qemu-arm-static`, GNU make
4.x, python3, and the card rootfs copy at `/home/david/spike2root` (`ROOT=`).

```sh
make BUILD=/home/david/tmp/item90/sel            # -> $BUILD/codeselect
make BUILD=/home/david/tmp/item90/sel check      # ELF ceiling + headless + padsw + select.sh
make BUILD=/home/david/tmp/item90/sel check-hw   # fakebus.py node-bus test on a pty
make BUILD=... install DESTDIR=/some/stage       # -> $DESTDIR/usr/local/codeselect/
```

The binary must run on the card's glibc 2.21, so the rootfs is used as the
sysroot BY HAND (`-nostdinc -isystem $ROOT/usr/include`, the rootfs crt
objects, `-nostdlib`, `-l:libc.so.6 libc_nonshared.a`, recipe D of the build
report). `--sysroot` alone silently yields a GLIBC_2.34 binary; the
`-U_TIME_BITS -U_FILE_OFFSET_BITS -U_FORTIFY_SOURCE -fno-stack-protector
-fno-pie` flags are load-bearing. The link line adds `AUDLIBS =
-l:libasound.so.2` (the rootfs alsa-lib 1.0.28, GLIBC_2.4 only; its
libdl/libpthread/librt are in the rootfs). `check_elf.sh` enforces: max
version node `GLIBC_2.17`, NEEDED only `libEGL.so.1 libGLESv2.so.2
libasound.so.2 libc.so.6 libm.so.6 libgcc_s.so.1`, interpreter
`/lib/ld-linux-armhf.so.3`. C only: the rootfs libstdc++ tops out at
GLIBCXX_3.4.20. The build is warning-free (`-Wall`); keep it so.

`make install` puts `codeselect`, `select.sh`, `images.conf.example` and
`font.ttf` (DejaVuSans-Bold from `/usr/share/fonts/truetype/dejavu/`, when the
build host has it; otherwise the card's own `/usr/local/spike/VeraMono.ttf` is
used at run time) under `$(DESTDIR)/usr/local/codeselect`, plus every file of
a `media/` directory beside the Makefile (when one exists) under
`$(DESTDIR)/usr/local/codeselect/media/`. The card builder injects that tree
into p2 and writes `images.conf`.

## The program

```
codeselect [--conf PATH] [--out PATH] [--input hw|padsw|none] [--nodebus DEV]
           [--spi DEV|none] [--padsw PATH] [--tables PATH] [--timeout SEC]
           [--last PATH] [--default N] [--log PATH] [--headless FILE.ppm]
           [--invert|--no-invert] [--preamble min|full] [--font PATH]
           [--media DIR] [--audio auto|alsa|fifo:PATH|none] [--audio-fmt PATH]
           [--volume 0-100] [--anim-frame N] [--audio-dump FILE]
           [--snapshot FILE.ppm] [--highlight N]
```

| option | default | meaning |
|---|---|---|
| `--conf` | `/usr/local/codeselect/images.conf` | the menu (below) |
| `--out` | `/var/volatile/codeselect.choice` | written as one line `<index>\n` on success |
| `--input` | `hw` | `hw` = node bus + SPI, `padsw` = the rig's keyboard file, `none` = countdown only |
| `--nodebus` | `/dev/ttymxc1` | 460800 8N2, VMIN 0 / VTIME 3, ASYNC_LOW_LATENCY, RTS pulse - what the game does |
| `--spi` | `/dev/spidev1.0` | 100 kHz mode 3, 8-byte transfers every 10 ms; `none` disables |
| `--padsw` | `$PAD_SW_SHM` or `/dump/padsw` | the 4096-byte padsw file, re-read every 20 ms |
| `--tables` | `/dump/tables/$PAD_GAME/switch_list.txt` | `id num node bit name` rows; maps (8,25)/(8,24)/(1,11)/(1,2)/(0,8..11) to ids by WIRE, with a whole-name fallback for the action button (1,2) |
| `--timeout` | conf `timeout=`, else 10 | seconds; 0 = wait for START/ACTION; a key press restarts it |
| `--last` | `/data/codeselect.last` | read for the initial highlight, written on confirm |
| `--default` | conf `default=`, else 0 | highlight when the last-choice file is missing/invalid |
| `--log` | none | appended; stderr always carries the same lines |
| `--headless` | off | no EGL; the loop runs (1360x768) and the last menu frame is written as P6 PPM; the LOADING frame goes to `FILE.loading.ppm` |
| `--snapshot` | off | render ONE menu frame (1360x768, the moment the menu appears) as a P6 PPM and exit 0 - no EGL, no input backend, no audio, no choice/last file: the preview (below) |
| `--highlight` | conf `default=`, else 0 | `--snapshot` only: the highlighted card (0-based); the last-choice file is never read; past the last image = exit 2 |
| `--invert` | auto | auto = `/games/data/boot_display_cmd` contains the token `-invert` (rotate 180, as boot_display does) |
| `--preamble` | `min` | `hw` only: how much of the game's node-bus bring-up to replay first |
| `--font` | conf `font=`, `/usr/local/codeselect/font.ttf`, `/usr/local/spike/VeraMono.ttf` | first that loads wins |
| `--media` | conf `media=`, else `/usr/local/codeselect/media` | where the conf's media names live (a name starting with `/` is used as is) |
| `--audio` | `auto` | `auto` = ALSA when `snd_pcm_open` succeeds, else `fifo:$PAD_AUDIO_PLAY` when that is set and non-empty, else `none`; `alsa`, `fifo:PATH`, `none` force one |
| `--audio-fmt` | `$PAD_AUDIO_FMT` | the rig's fmt file; the FIFO sink writes `44100 2` into it first |
| `--volume` | conf `volume=`, else 50 | software mix gain, 0-100 (50 = -6 dB) |
| `--anim-frame` | animate | `--headless`: every animation shows frame N and never ticks (the layout tests); `--snapshot`: the highlighted card's frame, wrapping past the end - the other cards show their still, or frame 0, as they do live |
| `--audio-dump` | none | raw s16le 44100 Hz stereo of everything mixed (with `--audio none` the mix still runs, paced to the clock) |

Exit status: `0` = a choice was written to `--out`; `2` = no choice (bad conf,
no font, display failure, interrupted). With `--snapshot`: `0` = the PPM was
written, `2` = it was not (bad conf, no font, `--highlight` past the last
image, a file that cannot be written), always with a `[select] error:`
line. Every media failure - a missing or
undecodable picture, a WAV in the wrong format, no sound device, no FIFO
reader - is logged and the menu carries on without that piece; the card never
fails to boot over media.

Keys: LEFT FLIPPER / Service Minus = highlight left (wraps), RIGHT FLIPPER /
Service Plus = right, START / ACTION / Service Select = confirm; Service Back
is ignored (autoattract.sh presses it in the rig). Two agreeing samples make a
state, a press edge makes one event, releases make none.

ACTION is the button on the lockdown bar - the one a player's thumb is already
on. It confirms exactly as START does; only the `[select] key:` line tells them
apart (`key: action` vs `key: start`). In the rig it is the Space key
(padglhost's bind); on the machine it is node 1 bit 2, another bit of the same
0x11 reply that already carries START, so it costs no extra bus traffic.

### The picture

A dark 1360x768 (or whatever `fbGetDisplayGeometry` says) menu: `SELECT GAME
CODE`, one card per image, the highlighted card framed amber on a lighter
fill, a footer `LEFT / RIGHT FLIPPER: choose   START or ACTION: boot` and
`booting <title> in N s` (or `press START or ACTION to boot <title>` with
timeout 0).

The footer names the buttons that EXIST. With no Action button resolved -
beatles has no lockdown row, and a menu still waiting for its switch table
has not resolved one either - both lines drop it: `LEFT / RIGHT FLIPPER:
choose   START: boot` and `press START to boot <title>`. Whichever pair was
drawn is quoted verbatim in the `menu:` and `snapshot:` log lines, so nothing
outside the program has to guess at it; `FOOT_START` / `FOOT_ACTION` near the
top of `codeselect.c` are the definitions.

Both bottom lines are SHRUNK and then CUT to the glass. Shrinking alone was
not enough: `gfx_fit_px()` stops at its minimum size and returns that size
whether or not the text fits, and a conf may carry a 199-character title,
which is still about twice the panel wide at 24 px - so the line ran off both
edges, because `gfx_text_center()` centres whatever it is given.
`gfx_ellipsize()` now ends anything still too wide with `...`, and what is
drawn is never wider than the panel. The countdown line is sized from its
longest form (the `press ...` one) so its size does not change as the digits
drop from 10 to 9, but each form is cut on its own. Checked by eye at 2 and
9 images with a 199-character title, and with a 199-character single word,
which is the case wrapping cannot help with.

* **2-4 images**: a row, card width scaled to fit (602 / 389 / 283 px).
* **5-16 images**: a carousel of three cards at the 3-card width, the
  highlighted image always in the middle, its neighbours left and right (with
  wrap-around), the neighbours-but-one peeking in from the screen edges as
  empty frames, and a `<   n / N   >` line under the cards. LEFT/RIGHT rotate
  the carousel.
* **No media configured**: the card is the v1 layout - `IMAGE n` label, the
  title (shrunk to fit, wrapped to two lines when it must), the subtitle
  (wrapped to four) - byte for byte (`test/headless.sh`'s first frames are
  identical to the v1 renders). Every card line goes through
  `gfx_ellipsize()` as well, because wrapping splits on spaces: one long word
  is still wider than the card. A title too long for its two lines is cut
  there by the wrap, with no marker - only the over-wide single line gets a
  visible `...`.
* **Any image with art or an animation**: every card gets an art panel across
  the top 40 % of the card (546x168 for two cards, 333x168 for three,
  227x168 for four) above the label; the title shrinks to 48 px and the
  subtitle to 26 px with the lines that still fit (two or three). A card's
  picture is aspect-fitted into its panel and centred (never upscaled; the
  tools pre-scale). The highlighted card plays its GIF on the GIF's own
  frame delays (100 ms where the file says 0, clamped 20 ms-10 s); the
  others show their still, or frame 0 when they have no still.
* **Confirm**: one `LOADING <title>...` frame with the chosen card's picture
  above the line; it stays up (swapped every frame) while the confirm sound
  plays to completion, then the program exits and the LCD keeps that frame
  until the game's first frame.

The canvas is redrawn in full only on a state change (highlight, countdown
second, carousel move); an animation tick repaints just the highlighted
panel. Every drawing call grows a dirty rectangle, and the frame uploads only
that rectangle, tightly packed, with one `glTexSubImage2D` (a 546x168 panel
tick = 367 KB instead of the 4.18 MB canvas); `eglSwapBuffers` runs every
frame regardless (the bridge paces to 60 Hz).

### Snapshot: one frame for the preview

```
codeselect --snapshot FILE.ppm --conf images.conf --media DIR [--highlight N]
           [--anim-frame N] [--timeout SEC] [--font PATH] [--invert]
```

draws the frame the machine shows the moment the menu appears - card N (or
the conf's `default=`; the last-choice file is never read) highlighted, that
card's GIF at frame N (0 when unset, wrapping past the end), every other
card its still or frame 0, the countdown at its full `timeout=` value
(`press START or ACTION to boot ...` for 0) - writes it as a binary P6 PPM and exits
0. Nothing else runs: no EGL, no input backend, no audio (the WAVs are not
opened), no choice or last-choice file, no LOADING frame. Every animation
is decoded in full first, so the run is the decode plus one draw (71-87 ms
under qemu for the test media, measured 2026-09-02). `-invert` is NOT
auto-detected: that
rotation compensates for an LCD mounted upside down and the preview shows
what the player sees; `--invert` forces it. Errors - an unreadable conf, no
usable font, a `--highlight` past the last image, a PPM that cannot be
written - print `[select] error: ...` and exit 2; a missing media directory
or file is as non-fatal as it is live (`art: cannot load ...` in the log,
the card renders without its picture). stdout carries one line a caller can
parse:

```
[select] snapshot: FILE.ppm 1360x768, highlight 1 (TMNT 1987) from --highlight, frame 2 of 4, timeout 10 s, invert 0, font /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf, media /some/dir
```

`frame F of N` is the frame shown and the highlighted card's frame count
(`0 of 0` when it has no animation), so a caller can step `--anim-frame`
through 0..N-1 to play it.

**Paths under qemu.** The GUI runs the snapshot as `qemu-arm-static -L
/home/david/spike2root codeselect ...`. The font and every media file are
plain `fopen`s, and qemu-user relocates an ABSOLUTE path into the `-L`
sysroot when the file exists there, falling back to the host path when it
does not (measured 2026-09-02 with qemu 8.2: `--font
/usr/local/codeselect/font.ttf` loaded the rootfs copy, which does not exist
on the host; `/usr/local/spike/VeraMono.ttf` likewise; a host path and a
path relative to the host cwd both loaded as themselves). So a conf
`font=/usr/local/codeselect/font.ttf` works once the rig has installed the
selector into the rootfs, and before that it falls through to the card's
VeraMono - there is always a font; a caller that wants a KNOWN face passes
`--font` with a host path (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`,
what `make install` ships as `font.ttf`). The same rule shadows any `--conf`
or `--media` path that also exists under the sysroot; keep them out of
`/usr/local/codeselect/`.

### Media

`/usr/local/codeselect/media/` on the card (flat; names `[A-Za-z0-9._-]+`;
the whole set at most 20 MB - the tools enforce that, the selector only reads):

| kind | format | notes |
|---|---|---|
| art | PNG (any colour type) | pre-scaled to the panel by the tools; decoded with stb_image, downscaled into the panel, 4 B/px in RAM |
| anim | animated GIF, <= 512x288, <= 30 frames, <= 1.5 MB | `stb_image`'s per-frame decoder; frame delays from the file; frames beyond 30 are ignored; only the two previous full-size frames are kept while decoding |
| music, sound_move, sound_confirm | WAV: RIFF PCM (or extensible-PCM) 16-bit 44100 Hz, 1 or 2 channels | mono is duplicated; anything else is refused with `audio: <file>: unsupported (...)`; clips longer than 120 s are cut |

Decode order: every still and the highlighted card's GIF before the first
frame (a 4-frame GIF takes ~4 ms under qemu), the other GIFs one FRAME per
loop iteration afterwards, so the menu appears at once and never stalls.

### Sound

One s16 44100 Hz stereo bus, four voices (music loop + move/confirm + one
spare, the oldest one-shot is stolen when all are busy), saturating mix,
master gain from `volume=` (256 * v/100), a 20 ms fade when a voice is
stopped so nothing clicks. `audio_pump()` runs from the main loop every
iteration and mixes exactly what the sink can take right now - never blocks:

* `alsa` (the machine): `snd_lib_error_set_handler(quiet)`,
  `snd_pcm_open("sysdefault:CARD=sgtl5000main", PLAYBACK, 0)` - any failure
  is "no alsa" (never the `null` device: alsa-lib 1.0.28 asserts on it),
  `snd_pcm_set_params(S16_LE, RW_INTERLEAVED, 2, 44100, resample 1, 500 ms)`,
  non-blocking; `snd_pcm_avail_update` says how much fits, `snd_pcm_writei`
  in <= 1764-frame chunks (the game's period), `-EPIPE` -> `snd_pcm_recover`.
  The mixer is untouched unless `mixer_volume=` is set: then the game's own
  recipe puts `192*(v/63)^0.2` into `PCM Playback Volume` on ctl `backbox`
  and `cabinet`. At exit: blocking `snd_pcm_drain` + close, BEFORE the choice
  file and before the EGL teardown, so the game finds hw:0 free.
* `fifo:PATH` (the emulator): writes `44100 2\n` to `--audio-fmt` first
  (playaudio.sh waits on it), opens the FIFO `O_WRONLY|O_NONBLOCK` (ENXIO =
  no reader yet, retried every 100 ms from the loop; a missing FIFO every
  1 s), `F_SETPIPE_SZ` 1 MB, paces to the wall clock 200 ms ahead, writes
  in 4 KB (PIPE_BUF) chunks so a partial write can never desync the stereo
  frames, drops on EAGAIN (counted), reopens on EPIPE (the same 100 ms
  ENXIO retries until a reader is back; while there is none, the fmt file
  is rewritten whenever it has been removed - a restarted playaudio.sh
  deletes it and waits 60 s for a fresh one - and a 3 s gap is logged
  once); streams silence while nothing plays so padplay's 25 s no-data
  watchdog stays quiet; `SIGPIPE` is ignored by `main()`. The reader is the
  rig's padrelay.py, which holds the read end only while a Windows
  padplay.py is on its socket, and that player dies on its first `print()`
  after the wsl.exe session that launched the run exits (measured
  2026-09-02: sound gone 31 s in, at the player's sixth 5-s report, and
  playaudio.sh's restart loop never sees it because the interop stub never
  returns) - the selector, like the game's alsastub, can only keep retrying
  and say so.
* `none`: with `--audio-dump` the mix still runs into the dump, paced.

Sounds: `sound_move` on every LEFT/RIGHT/-/+ edge; the highlighted card's
`music` loops (a hard switch when the highlight moves to a card with a
different file; the same file keeps playing); on START/Select the music
fades, `sound_confirm` plays TO COMPLETION (cap 8 s from the press, then the
sink's lead) under the LOADING frame, the sink is drained and closed, and
only then are the last-choice and choice files written.

### images.conf (v2)

```
# '#' comments; one image per line; index = order (0-based)
image=/dev/mmcblk0p3|STERN STOCK|TMNT Pro 1.59.0 - original Stern code|art0.png||
image=/dev/mmcblk0p7|TMNT 1987|1.59.0 - upscaled cartoon retheme|art1.png|anim1.gif|music1.wav
image=/dev/mmcblk0p7:img2|HEISEI|a games tree inside a shared partition
sound_move=move.wav
sound_confirm=confirm.wav
volume=50          # software mix gain 0-100 (default 50)
#mixer_volume=32   # hardware only: the codec 'PCM' volume, game curve, 0-63
#media=/usr/local/codeselect/media
default=0          # highlight when there is no usable last-choice file
timeout=10         # 0 = wait for ever
#font=/usr/local/codeselect/font.ttf
```

`image=<device>|<title>|<subtitle>|<art>|<anim>|<music>` - fields 4-6 are
optional media file names (relative to the media directory, empty = none);
a three-field line is the v1 form and stays valid. `<device>` is the block
device on hardware - `/dev/mmcblk0p3`, `/dev/mmcblk0p7`, or
`/dev/mmcblk0p7:img2` for a games tree in a subdirectory of a shared
partition - and an opaque token in the emulator (`p3`, `p7`, `p7:img2`). Up
to 16 images (`CONF_MAX_IMAGES`). `volume` is clamped to 0-100,
`mixer_volume` to 0-63. Unknown keys are ignored so the file can grow.

### stdout lines (the rig forwards `[select]` to its event pane)

```
[select] menu: 2 images, highlight 1 (TMNT 1987) from last choice, timeout 10 s, input hw, invert 0, 1360x768, font ..., audio alsa, media /usr/local/codeselect/media
[select] key: left|right|start|action|select|plus|minus|back
[select] chose 1 TMNT 1987
[select] error: <what>
[select] snapshot: FILE.ppm 1360x768, highlight 1 (TMNT 1987) from --highlight, frame 2 of 4, timeout 10 s, invert 0, font ..., media ...   (--snapshot only)
```

### log lines (stderr and --log)

```
audio: alsa sysdefault:CARD=sgtl5000main ok       the machine sink is up
audio: fifo /dump/audio.fifo open                 the rig's reader took the FIFO
audio: fifo reader went away, reopening           EPIPE: the relay closed the read end (its player died)
audio: no fifo reader for 3 s (it went away; ...) still none 3 s later: dropping, said once
audio: fifo /dump/audio.fifo open again after 4012 ms without a reader
audio: fmt /dump/audio.fmt = 44100 2 (rewritten: it had been removed)
audio: fifo closed without a reader (none for the last 26000 ms; it went away)   at exit
audio: none (<reason>)                            e.g. no alsa: ... ; PAD_AUDIO_PLAY unset
audio: <file>: unsupported (format ..., need PCM 16-bit 44100 Hz 1-2 ch)
art: image 0 art0.png -> 298x168 | art: cannot load <name> (<why>)
anim: image 1 4 frames 200x112 | anim: cannot open <name> (<why>)
media: 2 art, 1 anim (4 frames), 1 music, move=y confirm=y   once every decode is done
confirm: 1178 ms under the LOADING frame
audio: 105531 frames written, 0 dropped           at exit
egl: 8487 frames, 1234 KB uploaded, closing (the LOADING frame stays up)
```

## The EGL path (egl_stern.c)

Byte-for-byte boot_display's `glWindow::create_window` (the game shares it):
`setenv FB_MULTI_BUFFER=2`, `fbGetDisplayByIndex(0)`, `eglGetDisplay`,
`eglInitialize`, `eglChooseConfig {RED 5, GREEN 6, BLUE 5, ALPHA DONT_CARE,
SAMPLES 0, DEPTH 24}`, `fbGetDisplayGeometry`, `fbCreateWindow(0,0,w,h)`,
`eglCreateWindowSurface(NULL)`, `eglBindAPI(ES)`, `eglCreateContext
{CLIENT_VERSION 2}`, `eglMakeCurrent`, clear + swap, `glViewport`, blend.
Then `#version 300 es` sprite shaders with `layout(location=0)`, VAO + VBO
only (the bridge refuses client-side arrays), ONE RGBA8 texture created with
`glTexImage2D` and updated with `glTexSubImage2D` of the dirty rectangle
(packed rows of w*4 bytes, so the default UNPACK_ALIGNMENT holds),
LINEAR/CLAMP set explicitly (the bridge keeps per-name shadows across
guests), never `glPixelStorei` (not exported by the bridge). The whole
bring-up is retried 6 times 500 ms apart because on hardware boot_display may
still be releasing the display. Teardown leaves default-looking GL state
(unbind, `glUseProgram(0)`, blend off, the viewport reset - and NO clear or
swap: the `LOADING` frame just shown has to stay on the LCD until the game's
first frame, many seconds later), then `eglMakeCurrent(dpy,0,0,0)`,
`eglTerminate`, `eglReleaseThread`. No `eglDestroy*` (the shims do not export
them). Every EGL/GL/fb prototype is hand-written; no Khronos headers exist on
the box.

Proven against the rig's bridge libs on a private ring (ringcat.py as the
host): attach, `TEXIMAGE 1360x768 RGBA/UNSIGNED_BYTE`, one `TEXSUBIMAGE` per
state change, 124 acked swaps at ~61 fps, teardown, exit 0; and on David's
machine (2026-09-01: menu on the LCD, flipper selection, START, both images
boot). The sub-rect upload path is the same call with a smaller rectangle.

## The node bus (input_hw.c)

What the game does, from the godzilla_pro 1.15.0 ELF (read_nodebus.md A-F):

* open `O_RDWR|O_NOCTTY`; `TIOCGSERIAL`/`TIOCSSERIAL` with `ASYNC_LOW_LATENCY`;
  `cfmakeraw`; `CS8|CREAD|CLOCAL|CSTOPB`; `cfsetspeed(B460800)`; `~CRTSCTS`;
  `VMIN 0 VTIME 3`; `tcsetattr`; `tcflow(TCOON)`; `tcflush(TCIOFLUSH)`; RTS
  5 ms on / 5 ms off. Every failure is logged and tolerated (pty, /dev/null).
* exchange = `tcflush(TCIFLUSH)`, write the frame, read exactly `reply_len`
  bytes (poll-capped), check the checksum (bytes 0..ck sum to 0) and STATUS
  (`& 0x0c` = error).
* `--preamble min`: `0a 00` (2) . `07 01 01` . `80 02 f1 8d 00` . enumeration
  (`f0 22`, `f0 11`, `00` polls with `f0 10`/`f0 20` per named node, `f0 22`)
  . identity `fe` reads of nodes 8 and 1 (logged: fw, part, board, variant).
* `--preamble full` additionally replays the write-only frames captured
  byte-exactly before the game's first 0x11: node 8 `ff`, `14 40 00 27 00`,
  `14 60 00 40 00`, `46 ff 01`, `72 ff*12`, `48 00 00`; node 1 `ff`,
  `14 08 00 17 00`, `14 60 00 40 00`, `44 01`. The coil-config series
  (`46 <mask>` / `40 <i>` / `72` / `85` / `84`) was never captured verbatim
  and is NOT replayed.
* then `88 02 11 65 0c` (node 8) and `81 02 11 6c 0c` (node 1) every 25 ms:
  RIGHT = byte 3 bit 0, LEFT = byte 3 bit 1, START = byte 1 bit 3, ACTION
  (the lockdown bar) = byte 0 bit 2, released = 1 / pressed = 0. START and
  ACTION are two bits of the SAME node-1 reply, so the button costs no extra
  frame. A silent node backs off 500 / 1000 / 2000 ms so the
  menu stays responsive when a board does not answer (and the audio sink's
  0.5 s buffer rides through such a stall; a longer one is a gap, not a crash).
* SPI: `SPI_IOC_WR_MAX_SPEED_HZ 100000`, `SPI_IOC_WR_MODE 3`, an 8-byte
  `SPI_IOC_MESSAGE(1)` with tx zeros every 10 ms; rx[1] bits 0-3 = Service
  Select/Plus/Minus/Back, active low. tx[7] = 0 is the game's UNMUTED value
  for the backbox/cabinet amplifier bits, so the selector's sound is not
  muted by its own SPI traffic.

The first 40 exchanges are logged in hex (`nb <tag>: tx ... rx ...`), then
only changes and failures; the SPI logs its first 5 words and every change.

## Where things go on the card

```
/usr/local/codeselect/codeselect       the program (comm 'codeselect')
/usr/local/codeselect/select.sh        the hook
/usr/local/codeselect/images.conf      written by the card builder
/usr/local/codeselect/font.ttf         optional (DejaVu Sans Bold)
/usr/local/codeselect/media/*          art PNGs, GIFs, WAVs named by images.conf
/etc/init.d/game                       stock + one guarded line after 'pkill boot_display ':
                                       [ -x /usr/local/codeselect/select.sh ] && /usr/local/codeselect/select.sh
```

`select.sh` (POSIX sh, busybox `awk sed head tr mkdir mount umount` + `pidof`):
waits up to 3 s for boot_display to be gone, runs `codeselect --conf
images.conf --out /var/volatile/codeselect.choice --log
/dump/log/codeselect.log`, reads the index and looks the device up. Index 0
(the primary, fstab's `/dev/mmcblk0p3` at `/games`) touches nothing. Otherwise
`umount /games` and then, by the device form:

* `<dev>`: `mount -t ext4 -o ro,relatime,exec <dev> /games`
* `<dev>:<sub>`: `mkdir -p /mnt/multi` (on the stock read-only rootfs that
  fails and `/var/volatile/multi` on the tmpfs is used instead),
  `mount -t ext4 -o ro,relatime,exec <dev> /mnt/multi`,
  `mount --bind /mnt/multi/<sub> /games`

and checks that the new `/games` has `game`. Any failure (no binary, no conf,
selector exit != 0, no choice, unknown index, a `<sub>` with `/` or a leading
`.`, `umount` busy, a failed mount, no `game`) undoes what it did and mounts
`/dev/mmcblk0p3` back on `/games`: the primary boots. It never touches
`/mnt/boot`, and it never writes the last-choice file (the selector does, on
confirm). `select.sh --lookup N [conf]` prints image N's device (without the
`:<sub>`), `--lookup-sub N [conf]` the subdirectory (used by the tests); the
`CODESELECT_*` environment variables let the tests run the hook against a
fake selector and fake mount/umount.

## In the emulator

`run_game.sh` runs, inside its namespace and before the pivot/chroot exec,
with no LD_PRELOAD:

```
chroot "$R" /usr/local/codeselect/codeselect --conf /dump/codeselect.conf \
    --out /dump/select.choice --input padsw --timeout "${PAD_SELECT_TIMEOUT:-30}" \
    --log /dump/codeselect.log --media /dump/media
```

with `PAD_SW_SHM=/dump/padsw PAD_GAME=<primary title> PAD_GL_BRIDGE=/dump/padgl
PAD_GL_W=1360 PAD_GL_H=768 PAD_AUDIO_PLAY=/dump/audio.fifo
PAD_AUDIO_FMT=/dump/audio.fmt` inherited from watch.sh (the audio variables
are empty on a `PAD_AUDIO=0` run, which `--audio auto` reports as `audio:
none (... PAD_AUDIO_PLAY unset)`). The keyboard flippers (Left/Right
arrows), `1` (START), Space (ACTION, the lockdown-bar button) and
Enter/`=`/`-` (Service Select/Plus/Minus) arrive through padsw; ids come from
`/dump/tables/$PAD_GAME/switch_list.txt` by wire - (1,2) for ACTION, with a
whole-name fallback (`ACTION BUTTON` / `LOCKDOWN BUTTON`, case-insensitive,
an `(OPTIONAL)` suffix tolerated) for a list that puts it elsewhere - or the
platform ids (36 START / 25-28 service) before a title has a table (then the
flippers are unknown - use `-`/`=`/`1`). A list that names no lockdown button
at all (beatles is the one such list here) leaves ACTION unset rather than
letting some other switch stand in for it; Space then does nothing, `1` still
boots, and the footer says `START: boot`.

**ACTION gets no platform id at all**, which is why 34 is missing from that
list. Swept over the 31 cached lists on this disk, id 34 is the lockdown-bar
button on 20 - but on SEVEN it is `COIN DOOR INTERLOCK` (node 0 bit 23):
aerosmith_le, avengers_infinity_le, foo_fighters_le, guardians_le,
iron_maiden_le, mando_le, rush_le. That switch is not a button; a shut coin
door holds it made, which is a machine at rest (padglhost latches it at
window open). A table-less menu that read id 34 therefore read a switch
nobody had touched as an ACTION press and booted the highlighted image on its
own. It is also `VOLUME ENCODER 1` on batman and the START button on beatles.
ACTION now waits for the table or for its name, and loses least by waiting:
it is the only key with a name fallback.

Note the blast radius: this whole platform-id window is **emulator-only**. A
real machine runs the `hw` backend, which reads node 1 bit 2 straight off the
0x11 reply and never sees a switch id at all. Only `--input padsw` guesses.

The other platform ids were swept too. 25-28 slide onto `DIP 8` / `SERVICE
SELECT` / `SERVICE PLUS` / `SERVICE MINUS` on the eight older lists, so the
service cluster is off by one until the table lands; none of those is ever
held made, so the worst they do is move the highlight. 36 is `TICKET NOTCH`
on eight lists and `Left Coin` on beatles - dead keys.

One collision is **knowingly left standing**: on **batman** id 36 is that same
`COIN DOOR INTERLOCK`, so pre-table START carries the hazard ACTION just lost.
Reviewed and kept deliberately (2026-09-02), because the two sides of the
trade are not the same size:

* **Keeping 36** costs, on one title, in a window that only exists under the
  emulator, a phantom confirm that boots the wrong image. That is a restart.
  It cannot reach a real machine.
* **Dropping 36** costs all 30 other titles their keyboard confirm in that
  window - START is the only confirm key a table-less menu has, since the
  flippers are unresolved there by definition - leaving nothing to do but wait
  out the countdown.

Disarming one title by half-breaking thirty is the worse machine, so 36 stays
and the window is closed from the other end: with no table the list is
re-checked every 250 ms rather than every 2 s, and every title David runs
carries a cached table, so in practice the window is nearly always nil. What
fires it is not the door's level (a switch already made when the first sample
lands sets the debouncer's first settled level and raises no edge) but a
rising edge, i.e. padglhost re-resolving id 36 onto the door while this menu
is still on platform ids.

The switch list is also **re-read whenever its mtime moves**, for the reason
padglhost re-resolves its own binds (`padglhost.c:2008-2030`): mktables
repairs a partly-derived list about a second into a run, and a menu that
latched on the first parse kept the poorer answer for its whole life. A
rewrite that parses to nothing leaves the standing ids alone, so a later good
write still re-resolves. The footer repaints when the answer changes.

The rig copies the card's
`/usr/local/codeselect/media` (or `PAD_SELECT_MEDIA=<host dir>`) to
`$ROOT/dump/media` and forwards the conf's `sound_move`/`sound_confirm`/
`volume`/`mixer_volume` keys.

## Tests

`make check` (all under qemu-arm-static against the rootfs libs, no chroot,
no rig). The emulator is handed to the test scripts through the environment
(`QEMU=...`, exported by the Makefile), never on their command line: a rig
teardown (`killgame.sh`, `watch.sh`) does `pkill -9 -f 'arm-binfmt|qemu-arm'`,
and a `bash test/x.sh qemu-arm-static ...` argv matched it, so a concurrent
teardown killed the tests. Only the short-lived qemu child matches now - so
still, `make check` / `check-hw` must not run while a rig run is being torn
down.

1. `test/check_elf.sh` - the readelf ceiling above.
2. `test/headless.sh` - headless renders: 2/3/4 images, `--default 1`,
   last-choice precedence, `--invert` (the exact 180-degree rotation), the
   PPM shape, an empty conf refused; then media from `test/mkmedia.py` (two
   solid PNGs, a 4-frame solid-colour GIF, 0.2 s / 1.0 s / 0.5 s tones and a
   22050 Hz WAV - no PIL needed): `--anim-frame 2` puts the art colours at
   the panel centres (and at the mirrored coordinates with `--invert`), the
   `media:` line, a confirm wait and a non-silent `--audio-dump`; a missing
   PNG and the bad WAV are non-fatal (exit 0, logged); 5- and 9-image
   carousels (the highlight centred, a neighbour's pinned GIF frame in
   place); a 17-image conf refused. Then `--snapshot`: `--highlight 1
   --anim-frame 2` on the media conf (card 1's GIF at frame 2 = blue at its
   panel centre, card 0's still, the amber countdown line present on its
   baseline, `frame 2 of 4` on stdout, no choice/last/LOADING file, no
   `nb`/`spi`/`audio:` line in the log and `0 music, move=n` - the WAVs are
   never opened; neither `--input` nor `--audio` is passed), `--highlight
   0` (card 1 shows its STILL: a card that is not highlighted never
   animates), a frame past the end wrapping, no `--highlight` = the conf
   default with a last-choice file present and untouched, a timeout-0 conf
   (`press START` line), a missing media directory (exit 0, `art: cannot
   load`), and `--highlight` past the end / an empty conf / `--snapshot`
   with `--headless` refused (exit 2, no PPM). PNGs in
   `$BUILD/t/codeselect_*.png` for eyes.
3. `test/padsw_test.py` - a padsw file, RIGHT (id 64 on turtles_pro) held
   100 ms then START (36), with the test holding the read end of a FIFO the
   selector writes into (`--audio fifo:... --audio-fmt ... --audio-dump`):
   expects `key: right`, `key: start`, `chose 1`, choice file `1`, exit 0,
   the ids line naming `start 36 action 34`, `audio.fmt` = `44100 2`, silence
   streaming before the first key, sound after RIGHT and after START, an exit
   >= 0.9 s after START (the 1.0 s confirm WAV plays out first), a non-silent
   dump. Then: the same RIGHT with ACTION (34) instead of START - `key:
   action`, never `key: start`, `chose 1`; two synthetic tables for the
   name fallback - one whose (1,2) row is missing but which spells the button
   `lockdown   button   (OPTIONAL)` on another wire (resolved, logged `(by
   name)`, while the `TOURNAMENT START BUTTON` and `ACTION BUTTON TARGET`
   decoys are refused), and one naming no lockdown button at all (`action
   -1`, and START unharmed).

   Then **the phantom action**: a run with NO switch table and id 34 made
   before it starts, released and re-made 1.2 s in (the two ways a latched
   coin door can present - the level, and padglhost re-resolving the door
   onto id 34 mid-menu, which is the one that actually fired). It must log no
   `key:` at all, sit out its whole 4 s countdown and choose 0. The **positive
   control** is the same edge on id 36, START's platform id, which must still
   confirm - without it a run that simply ignored the padsw file would pass.

   Then **the footer**: `--snapshot` against a list with a lockdown row, one
   without, no list at all, and `--input hw`, reading the footer the log line
   quotes; ACTION is named only where one resolved, and always on hw.

   Then **the re-read**: a list that starts without a lockdown row and gains
   one mid-menu must be re-read on its new mtime (`changed on disk; ids
   re-resolved`, `action 9`), repaint the footer (`footer: ACTION button
   resolved`) and then accept a press on the id it just learned.

   Finally a run against a FIFO that does not exist still exits 0 on the
   countdown.
4. `bash -n select.sh` + `test/select_sh_test.sh` - the images.conf lookups
   (`--lookup`, `--lookup-sub`, six-field lines, the `:<sub>` form) with the
   host awk AND the card's busybox awk under qemu, then the whole hook with
   a fake selector and fake mount/umount: index 0 untouched, the plain
   device remounted, the `:<sub>` form mounted and bound, and the primary
   put back after a missing tree, a bad `<sub>`, a failed mount, a busy
   umount, a failed selector, an index past the conf, and the fallback dir
   when `/mnt/multi` cannot be created (11 cases).

`make check-hw`: `test/fakebus_test.py` starts `fakebus.py` on a pty and runs
`--input hw --nodebus <pty> --spi none --default 1`; presses LEFT then START
via the control file; expects `chose 0`, the exact frames `88 02 11 65 0c`,
`81 02 11 6c 0c`, `88 02 fe 78 0d`, `81 02 fe 7f 0d`, the `0a 00 -> 03 00`
exchange, the enumeration frames, the pressed-LEFT reply
`00 ff 1f f9 40 00 00 00 00 00 a9 00`, and no `BAD CK`. A second run presses
`action` instead (node 1 bit 2) and expects `key: action` with no `key:
start`, `chose 1` (the untouched default), no `countdown expired`, and both
node-1 replies on the wire: `04 59 7f 00 00 00 00 00 00 00 24 00` at rest and
`00 59 7f 00 00 00 00 00 00 00 28 00` with bit 2 down.

The fake bus's at-rest words are OBSERVED, not invented, and `fakebus.py`
records which part of each is which. Node 1 used to idle at `ff` x8, a guess,
and a wrong one in the byte that matters: byte 0 carries bit 2, the Action
button. The real word is `04 59 7f 00 00 00 00 00` - what 187 of the 190
logged runs on this disk prime node 1 with, across godzilla,
dungeons_and_dragons, batman, avengers and stranger_things, and whose set
bits are exactly the union of the node-1 bits in all 31 cached switch lists
({2, 8, 11, 12, 14, 16..22}: lockdown button, ticket notch, start, tournament
start, tilt pendulum, six coins, slam tilt). Every bit with a switch reads 1
(released = 1 for a button), every bit without one reads 0, and there is no
node-1 switch above bit 22, which is why bytes 3-7 are zero. The press
variants in those same logs move only the expected bit (`04 51 7f ..` =
START held, `00 59 7f ..` = ACTION held, `04 59 7e ..` = Left Coin).

## What to look for on hardware

In `/dump/log/codeselect.log` (also the serial console):

```
nb: /dev/ttymxc1 open (460800 8N2, VMIN 0 VTIME 3)
nb 0a: tx 0a 00 rx 03 00                      the bridge answered at all
nb poll: tx 00 rx 08                          enumeration named node 8
nb fe: tx 88 02 fe 78 0d rx ...               node 8 identity (fw/part/board logged)
nb: node 8 switches 00 ff 1f fb 40 00 00 00   the first 0x11 answer (at rest)
spi: rx ff 0f 0f 00 00 00 00 00               the cabinet word at rest
egl: initialised 1.4 / egl: display 1360x768  Vivante came up
egl: up after N attempt(s)                    N > 1 = boot_display was still releasing the LCD
audio: alsa sysdefault:CARD=sgtl5000main ok   the codec took the stream (else 'audio: none (no alsa: ...)')
media: 2 art, 1 anim (30 frames), 1 music, move=y confirm=y
[select] key: left / [select] chose 1 TMNT 1987
confirm: 1540 ms under the LOADING frame
audio: 123456 frames written, 0 dropped
select.sh: image 1: mounted /dev/mmcblk0p7 at /games
```

Failure signatures: `nb ...: short reply (timed out)` on every frame = the
bus is not answering (try `--preamble full`, then a hardware capture);
`egl: giving up after 6 attempts` = the display never came free (the hook
boots the primary); `select.sh: umount /games failed` = something held
`/games` (the primary boots, still mounted); `audio: none (no alsa: ...)` on
the machine = the codec device could not be opened (the menu is silent, the
boot is unaffected); a silent machine with `audio: alsa ... ok` = the
kernel-driven stream does not reach the amplifiers at the boot-time codec
state (try `mixer_volume=`, then the `aplay` test from the audio report).
