# Emulate: play the game on this PC

[← Back to the README](../../README.md)

The Emulate tabs run a machine's own game program on this PC, so you can
watch what you built before it goes near the machine.

| | Stern Spike 2 | Jersey Jack | Dutch Pinball |
|---|---|---|---|
| Runs on | Windows (WSL2), Linux, macOS (container) | Windows (WSL2) | Windows (WSL2), Linux |
| Needs | a card image | the game ISO + its purple USB key | the disk image |
| Playfield window | Yes, clickable | Switch matrix | Switch window |
| Save states | Yes (Windows, macOS) | No | No |

The American Pinball, Barrels of Fun, Pinball Brothers and Spooky Emulate
tabs are described with their manufacturers in [Supported
manufacturers](manufacturers.md).

## Stern Spike 2

Pick a card image and press **Start emulator**. The real game runs in its
own window at 60 fps, with sound, video, lamps and keyboard. It boots the
way the machine does: splash, boot checks, then attract.

- **The card is never written to.** Its game partition is mounted read
  only. A stock card and your own build both work.
- **No time limit.** It runs until you press Stop, which then checks that
  nothing was left running.
- **What it costs:** about a third of one CPU core while it runs, plus 1–2
  GB of memory, shown live in the status line.
- **Spike 3 cards** are refused up front: their game partition is
  encrypted, so they cannot run here.

### Getting set up

The tab checks this PC before you press anything. A ready PC shows
nothing; one that isn't gets an amber notice naming each missing piece.

| | What to do |
|---|---|
| Windows | Press **Set up emulator…**. It lists every change first, then installs into WSL. No password needed. |
| macOS | Runs in a container. **Set up emulator…** installs a container engine (Colima) with Homebrew or MacPorts if you have none. |
| Linux | No button (it needs sudo). The notice prints the exact command to run. |

- **Check setup…** changes nothing and writes the full answer to the log:
  packages, the ARM handler, the WSL login user, the display, the sound
  path. When a run goes wrong, this log is the thing to send.
- **The first Start** builds the game's Linux from your card and compiles
  two small programs: a few minutes, once. Later runs start in seconds.
- **The first WSL use after a Windows reboot** can take a minute while WSL
  starts. The tab says so and stays usable.
- **Feature-only pieces** are listed under the feature they cost, not as
  "can't emulate": **Save states need:** `busybox-static` and `criu`;
  **Multi-boot cards need:** `make`.
- **Start the app as yourself**, never with `sudo`.

### The card it runs

- **Boot selector** ticks itself on a multi-boot card: pick the game with
  the flipper buttons, as on the machine.
- **Card cache:** the first boot copies the card to a local cache, so later
  boots are quick. The cache keeps under a size limit (64 GB by default on a
  distro disk), dropping the least recently used cards first. **Cache…**
  shows each card's image and whether a rig is using it, sets the limit, and
  deletes cards; deleting is always safe.
- **Use the extracted card** and **Use the last build** switch back to the
  project's own cards.

### Run your edits without building a card

Tick **Apply my replaced assets on top, without rebuilding the card**, and
Start plays the card plus your edits. Nothing is built, and the card image
is never written to.

- **Your picks count.** Start first applies the picks waiting on the
  Replace tabs to the project folder, as a build would, and the log says
  so.
- **Videos and pictures are converted first.** Start says how many and
  about how long, and asks first when it is a minute or more. Converted
  files are kept, so the next Start redoes only what changed.
- **Only the files your edits touch are copied** (e.g. `image.bin` and its
  `.sidx` for a replaced sound). A repeat run reuses them.
- **On a card the app built,** the edits are prepared from the card your
  project was extracted from, then run over the built card. Its own build
  changes are kept.
- **On a multi-boot card,** the edits come from the first game image on it
  and run over whichever game you pick at the menu.
- **It refuses rather than half-works.** No assets folder, no baseline to
  compare with, or an edit that traces back to no file on the card: the
  run stops and says which.
- **Show it through the machine's screen** draws the game through your
  Machine screen (Color profile tab), so the PC shows the colors the
  machine will.

### The cabinet: Country, Power, Edition, Topper

The row under the card is the cabinet the card is fitted to.

- **Country (DIP switches)** sets the CPU board's country switches and the
  country stored in the machine. A changed country opens the game's Guided
  Setup, as a real machine does. **As set in the game** changes nothing.
- **Power:** 60 Hz (as the emulator has always run), 50 Hz as a European
  machine, or 50 Hz as a US machine (which some games refuse, as they do
  on a real one).
- **Edition** is which model the machine is. One Premium/LE card runs every
  Premium, LE and (on some titles) SLE, plus named editions such as
  Godzilla 70th Anniversary, and the service menu names that model. Each
  session starts on the card's own model.
- **Topper** opens the second screen above the backbox on the machines
  that have one (Mandalorian, Venom, Stranger Things). Untick it to run
  without.
- Country and Power are remembered for every project and take effect at
  the next Start.

### The virtual playfield

A second window draws the machine's playfield from the card itself, with
every insert lit live and every switch clickable.

- **Click a switch** and the game reacts as if a ball rolled over it.
- **Balls are real to the game:** it serves, re-serves after a save and
  feeds multiballs on its own. The trough strip shows every position;
  click one to take a ball out or bring one home.
- **Buttons:** **Insert coin**, **Start**, **Plunge**, **Drain** and
  **Reset balls**. The status bar says what each press did ("a game needs
  CREDITS").
- **The coin door** buttons (BACK, -, +, SELECT) open the operator menu.
- **Cabinet lights** (left of the playfield): the topper, the speaker
  lights and the expression-lighting blades, lit live. Untick **Expression
  lights** in the CABINET LIGHTS box to hide them.
- **Insert colors:** an RGB insert shows the color the game gives it. A
  single-color insert is drawn white; set its color in the INSERT COLORS
  box.
- **No playfield drawing** on some games and versions: you get a
  clickable switch-list schematic instead, with the same buttons.
- **Pause** (the Pause key or F9, in either window) freezes the whole game,
  video and sound too. The next press carries on from that frame.

### Save states (Windows and Mac)

**Save state** on the playfield window checkpoints the whole running game;
**Load state** brings that moment back, mid-game too, even in a later
session.

- **Ten slots per game.** The tab's slot list shows each slot's name,
  game, size and time, with **Rename** and **Delete**.
- **Launch** starts the emulator straight into a slot, or loads it into
  the run that is up.
- **After you replace assets,** a load plays the new videos and sounds.
- **Cost:** about 50–150 MB a slot, and a save briefly needs about 1.5 GB
  free. A slot loads only on the same app build, game and firmware.
- They need `busybox-static` and `criu`. **Set up emulator…** gets both
  (criu is built from source, a few minutes). Without them every game
  still runs; only save states are off.
- **On a Mac** the emulator's container brings both. Docker Desktop cannot freeze a running game, so there a run starts without save states and the log says why; colima, which **Set up emulator…** installs, can.

### Sound and windows

- **Volume** and **Mute** set the emulator's sound on your PC, live, and
  are remembered. They are not the machine's own volume setting.
- **The windows come out in front** of the app by themselves. It can take
  a few seconds: Windows won't jump a window over the one you just
  clicked.
- **Each window reopens where you left it.** A spot that is off every
  screen (an unplugged monitor) is skipped. **Reset windows** puts them all
  back at their defaults.
- **Game display** picks the game window's monitor and whether it sits where you leave it, fills the screen or takes a set window, with or without a frame. A change reaches a running game within a second.
- **Silence after the boot chime** usually means it is still at Tech
  Alerts.

### When something goes wrong

| What you see | What to do |
|---|---|
| **Black game window**, sound and switches fine | Usually a WSL that logs in as root. **Check setup…** names it. **Install emulator Linux…** gives the emulator its own Linux with an ordinary user; your own distro is not changed. |
| **No game window** at all | The log says which: opened off screen (Stop, then **Reset windows**) or WSLg not showing it (Stop, then **Restart WSL…**). |
| **Renderer row amber, "no GPU"** | WSL lost the graphics card (often after a driver update). The game runs in software, slower. **Restart WSL…**, then restart Windows if it says so again. |
| **Videos black, everything else fine** | `ffmpeg` is missing *inside* WSL (a different copy from the app's own). The run names the package. |
| **A stuck window, crackly sound** after a long session | **Restart WSL…**. It closes everything in WSL, so stop the game first. |
| **GAME VALIDATION ERROR** | The log's `[validation]` line names which check failed. |
| **Stops at the Stern logo** | The log names the scene file the game could not read, and whether it is one of your edits. |
| **"Update emulator Linux…"** shows | The emulator's own Linux is from an older version. Press it; your cards and save states are kept. |

The log's `picture:` lines say whether the window has a picture at all.
*STILL BLACK* while video frames arrive means the game itself is drawing
black, so restarting WSL won't help.

### On a Mac

- The game runs in a container (Docker Desktop, OrbStack, Rancher Desktop
  or Colima). Nothing has to be added to Docker's file sharing.
- The picture opens in macOS **Screen Sharing** once the game is up (VNC
  password `pinball`). Click a window there to give it the keyboard.
- Sound plays through `ffplay`, part of the ffmpeg the app already needs.
- **Start Docker** starts the engine you have; **Get Docker…** opens the
  download page when there's nothing to install with.

## Jersey Jack Pinball

*Windows via WSL2*

A JJP game is a native Linux program, so it simply runs: no CPU
emulation. Pick the game ISO, plug in the key and press Start.

- **The purple JJP USB security key is required.** The game's code is
  encrypted and the key holds its decryption key, so there is nothing to
  work around.
- **Keys are per title:** a Wonka key will not run Guns N' Roses. The tab
  tells a wrong key apart from one WSL simply didn't pick up.
- **Key on another PC?** Pick **On another PC** in the Security key card:
  Start borrows it over the network, Stop hands it back.
- **The ISO is only read.** The game runs on a temporary overlay, thrown
  away on Stop, so every start begins clean.
- **The switch matrix** draws every switch, lamp and coil on the game's own
  playfield photograph. Click a switch to pulse it, right-click to hold
  it.
- **A ball feeder** answers the trough, so Start plays a whole game: serve,
  plunge, drain, next ball.
- **Fix stuck state** restarts WSL to clear a wedged run (about 15 s).

## Dutch Pinball

*Windows via WSL2, or Linux*

Plays The Big Lebowski or Alice's Adventures in Wonderland from the
machine's disk image.

- **The Big Lebowski** can take an update zip on top (the official one or
  one the Write tab built), laid over the image the way the machine
  installs it.
- **The first Start** copies the game out of the image (several GB, a few
  minutes). Later starts are quick, and both files are only read.
- **The switch window** shows every switch. Hold one with the mouse, or
  right-click to latch it.
