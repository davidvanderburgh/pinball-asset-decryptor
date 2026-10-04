# Barrels of Fun multi-boot (PAD-342)

Several builds of one Barrels of Fun title in ONE `.fun`, and a boot menu the machine
shows at power-up: the flippers choose, START (or LAUNCH) boots, the countdown boots the
remembered choice. The menu is the same code selector the Stern card and the JJP machine
carry (`tools/spike2_emu/codeselect`), built for this machine as `bofselect`. The
builder is `mkbofmulti.py`; the Multi-boot tab drives it through its BOF backend
(`pinball_decryptor/webui/multiboot_backend.py`).

## How a BOF machine takes an update (Labyrinth)

Read out of the `.fun` files themselves (2026-10-03). A `.fun` is a GPG-symmetric gzip
tarball (Labyrinth's passphrase is `funkey`). The machine's `~/updatecode.sh`, run when a
stick with `lab.fun` goes in:

1. empties `/home/pinball/extracted`, decrypts the `.fun` into it, untars it into
   `extracted/decrypt`;
2. requires exactly ONE `*.x86_64` there, renames it `GDCraze.x86_64`, records its size in
   `~/craze/GAMEFILESIZE`, removes `~/craze/GDCraze.x86_64` and copies the new one in;
3. runs the update's own `update/update.sh`, which copies `update/.bash_profile` over
   `~/.bash_profile` and `update/updatecode.sh` over the updater itself.

`~/.bash_profile` (tty1's login, as `pinball`) is what starts the game: it checks that
`craze/GDCraze.x86_64` is the size `GAMEFILESIZE` says (copying `extracted/decrypt/
GDCraze.x86_64` back over it when not), then runs `./startgame` in a loop. The updater's
own progress screen (`update/main`) draws straight onto `/dev/fb0` after `fbset -xres 1366
-yres 768`. So an update changes how the machine STARTS, and that is the whole door: no
drive comes out of the machine.

## What a multi-boot `.fun` is

| member | what |
|---|---|
| `update/` | the primary's scripts, with two changes: `update.sh` runs `padselect/pad_install.sh` first, and `.bash_profile` carries the hook block before `while true` and an `rm -f` in front of its self-repair copy |
| `padselect/` | `bofselect` (the menu), `paddelta` (the rebuilder), `padselect.sh` (the hook), `pad_install.sh` (the install step), `font.ttf`, `images.conf`, `programs` (each image's size and md5), `build.json`, the menu's pictures |
| `pad_imageN.delta` | image N rebuilt from image 0 |
| the primary's other members, its program last | exactly as in the primary `.fun` |

Both patches are anchored on the vendor's exact lines and refused when they are not there.
The `rm -f` matters: after a switch, `craze/GDCraze.x86_64` is a HARD LINK to the chosen
image, and the profile's self-repair `cp` onto a hard link would write through it into the
other image's file.

**Why a delta.** A `.fun` is one file on a FAT32 stick, which holds no file of 4 GiB or
more, and one Labyrinth program is 4.3 GB (2.9 GB packed). A mod is its title's program
with some packed files changed: the Sarah build shares the first 1.5 GB (the engine) and
8,411 of 8,512 packed files with stock and differs in 311 MB. `delta_ops` reads both
programs' Godot pack directories (`plugins/bof/pck_directory.py`) and copies every file
they share from image 0 wherever it sits; everything else is compared at the same offset.
The builder checks, byte for byte, that the delta rebuilds the build before it writes
anything. Stock + Sarah = a 3.24 GB `.fun`.

**Everything lives under `extracted/`**, which the updater empties at the start of every
update: a later normal update takes the menu, both programs and the menu's memory away,
and that update's own `update.sh` puts its own profile back.

## On the machine

**Install** (`pad_install.sh`, once, inside the update): removes the decrypted archive the
updater leaves in `extracted/`; turns `craze/GDCraze.x86_64` from a copy of image 0 into a
hard link to it; rebuilds every other image with `paddelta` (writes `OUT.part`, `fsync`,
renames); checks every image against the md5 in `programs`. An image that does not check
out is taken out of the menu and its files removed; with one image left there is no menu.
It always exits 0, so nothing in the vendor's `update.sh` after it is skipped.

**Every power-up** (`padselect.sh`, from the profile, console only): no conf, one image,
`GAMEUPDATING` or the updater running = nothing. Otherwise `sudo -n bofselect --input fast`
draws the menu on `/dev/fb0` (`fb_linux.c`, the updater's own route) and reads the
flippers off the FAST Neuron (`input_fast.c`: `ID:` to find the NET port among the
`ttyACM`s that are not the Audio Controller, then `SA:` every 25 ms; nothing else is ever
sent - no switch or driver config, no watchdog, so no coil can fire). The chosen file is
hard-linked to `craze/GDCraze.x86_64` (remove first, always) and its size written to
`GAMEFILESIZE`, so the profile's own check passes and `./startgame` runs it as it always
has. Every failure ends on image 0, and the menu is killed after its own timeout plus a
minute. A read-only root is remounted rw for the swap and put back.

**Buttons.** `switch_left=15`, `switch_right=22`, `switch_start=14,20` (LAUNCH is a second
START) - the numbers in Labyrinth's own switch table. `SA:` is the switches' PHYSICAL
level and the game applies each switch's `reversed` flag itself, so pressed = different
from the first reading; a switch reading "pressed" for 3 s without a break is taken as its
rest level (a button held at power-up would otherwise read backwards for good).

**No sound.** `bofselect` is one static binary (the machine's Arch glibc is whatever its
last image carried), and a static binary cannot load the machine's libasound.

## Proven (2026-10-03, without a machine)

| what | how | result |
|---|---|---|
| the build | `mkbofmulti.py build` from the real stock and Sarah `lab.fun` | 3.24 GB `.fun`; image 1's delta 0.31 GB, rebuilt byte for byte before writing |
| read back | `mkbofmulti.py verify` (unpack, `paddelta`, md5) | both images rebuilt and checked |
| the machine's own scripts | `machine_sim.sh`: Labyrinth's `updatecode.sh`, `update.sh` and `.bash_profile` run UNMODIFIED against a bind-mounted `/home/pinball`, the FAST board by `bofhw.py` | 18/18: stock install; multi-boot install (image 1 rebuilt in 11 s, md5 ok, craze a link); RIGHT+START boots Sarah; LEFT+START boots stock with Sarah untouched; the countdown boots the remembered one; a normal update removes everything and the stock profile is back |
| the buttons | `codeselect/test/fast_test.py` against `bofhw.py`'s Labyrinth ports | NET found, Audio Controller skipped, flippers/START/LAUNCH, `CH:` fallback, a reversed button, a held button re-learnt, only `ID:`/`SA:` ever sent |
| the screen | the fake framebuffer (`PAD_SELECT_FAKEFB`) | 1360x768 canvas 1:1 on 1366x768 with 3 px borders; the LOADING frame stays |
| two screens | `codeselect/test/fb_bof_test.sh`: a fake fb with 1280x390 visible of a 1366x768 buffer | the whole buffer, 1:1 at 3,0 (backbox full screen); a buffer that is only taller keeps the visible area |

## Proven on a machine (David's Labyrinth, 2026-10-04)

The `.fun` from 55e9285c, on a FAT32 stick through BOF's own updater: it installed, the
menu came up at power-up, the flippers chose and START booted. So `/dev/fb0` is free when
the profile runs, `pinball`'s `sudo` works, and the Neuron's buttons reach the menu.

**One thing the machine showed: two screens of different sizes.** The DRM console puts one
buffer on both screens - the backbox 1366x768 and the 1280x390 strip over the playfield -
and fb0 reports the SMALLER as its visible area (1280x390 of a 1366x768 buffer). The menu
sized itself to that, so the backbox showed it at half size in its top left and the strip
showed the whole small menu. `fb_linux.c` now draws the whole buffer whenever it is wider
than the visible area: the backbox is full screen and the strip shows its top 1280x390
(the title and the upper half of the cards). BOF's own update screens get the same by
running `fbset -xres 1366 -yres 768` first.

## Running it

```
python3 tools/bof_emu/mkbofmulti.py plan  --primary lab.fun --extra "Labyrinth (Sarah mod)/lab.fun"
bash tools/bof_emu/ensurebofselect.sh "" /var/tmp/bofselect
python3 tools/bof_emu/mkbofmulti.py build --primary lab.fun --extra ".../lab.fun" \
    --out multi/lab.fun --selector-dir /var/tmp/bofselect --titles "LABYRINTH;SARAH CODE"
python3 tools/bof_emu/mkbofmulti.py verify --fun multi/lab.fun
sudo bash tools/bof_emu/machine_sim.sh lab.fun multi/lab.fun      # the machine's own scripts
make -C tools/spike2_emu/codeselect PLATFORM=bof check              # the menu, the rebuilder, the scripts
```
