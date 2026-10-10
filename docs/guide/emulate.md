# Emulate: play the game on this PC

[← Back to the README](../../README.md)

The Emulate tabs run a machine's own game program on this PC, so you
can watch what you built before it goes near the machine.

## Stern Spike 2

*Stern Spike 2 — Windows via WSL2, Linux, or macOS in a container*

Run the
game itself on this PC and watch what you built. Point it at a card
image and press Start: the card's game partition is mounted **read
only** and the real armhf game binary runs under `qemu-user` with its
hardware replaced by shims, in its own window at 60 fps, with sound
and keyboard input. It boots the way the machine does — splash, boot
checks, then attract mode (it skips to attract on its own by default,
or untick that and drive the boot yourself). The panel is a control
surface, not a second copy of the emulator: it shows the state,
process count, CPU and memory live, stops by killing every part and
then *verifying* nothing survived, and caps a forgotten session at
two hours. Video plays as well now: the Spike 2 decoder is an i.MX6
hardware block a PC doesn't have, so the host decodes each clip with
ffmpeg and publishes the frames into a shared ring the game draws
from. Scenes, text, lamps, switches and sound all work. A long
session stays up, too: a clip is looped by playing it again, and
every play used to leave another abandoned decoder thread — and its
8 MB of stack — behind inside the guest, so a run with video on
screen ran the 32-bit game out of address space and died with a
`SIGSEGV` after about seven minutes, picture and sound perfect right
up to the last second (fixed v0.119.7).
A Stern **Spike 3** card is recognised the moment you pick it and
refused before anything is copied: its game partition is encrypted,
so it cannot run here, and the log says so instead of a failed mount.
**Your own edits can run without a card being built** (v0.183.0).
Tick *Apply my replaced assets on top, without rebuilding the card*
in the source box and Start patches just the card files your
replacements live in - `image.bin` and its `.sidx` record, for a
replaced sound - into a small set of copies, and the guest reads
those over the same read-only mount. The card image on disk is never
written to and nothing is rebuilt, so hearing a replaced sound stops
costing the two full-size copies it used to: the build's copy of the
card, and then this tab's own copy of that new card onto the WSL
disk. On a Jurassic Park LE 1.16.0 card that is nine seconds. The
set is kept between runs, and a repeat run is cheaper still - an
unchanged set is reused where it stands, and a changed one is
patched where it changed rather than built again, so the second run
costs only what you have edited since. The folder shown beside the
box is the Write tab's own Assets Folder, read-only here, because
the project has one extract folder and one place to set it; the
choice is remembered with the project. And it refuses rather than
half-works: no assets folder, no `.checksums.md5` baseline to
compare against, an edit whose bytes can't be traced back to a file
on the card, or a booted card that doesn't carry the files it was
given, and the run stops and says which.
And a replacement you *picked* counts as one of those edits from
v0.196.3, even if you have never built a card with it: Start applies
the assignments waiting on the Replace tabs to the project folder
first, exactly as a build does before it repacks, and says in the log
that it did - it changed your folder and you did not press Build.
Before that the box could only see edits a previous build had already
written there, so a freshly picked sound, clip or image ran as the
stock card and the log said there was nothing to apply. If everything
you assigned fails to convert, the run refuses instead of playing the
stock card. On a multi-boot card the edits are prepared from ONE image
on it - the first game image on the card, which is where every extract
and write on that card goes - and applied over whichever image you
pick at the boot menu, and the run says so; to edit a different
image, build that image on its own and rebuild the multi-boot card
from it.
**Before the game starts, your videos and pictures are converted** -
a replacement to the card's own format, a game's own clip or picture
with its color profile baked in. Start first says how many videos
need it and about how long that takes, and asks before going on when
it comes to a minute or more. While it runs, the State line and the
footer bar count down "Converting videos: N of M (about X left)", and
"Preparing your edits" shows its steps. A converted video is kept, so
a later Start converts only what you have changed since. Cancel stops
it at once: the game is not started, and the videos already converted
are kept for next time.
**And a run of just your edits no longer ends on a black screen.**
Every set of edits carries the card's SD-validation record as well
as the files you changed, because a write refreshes that record
whatever was edited. That record sits beside the title on the card
rather than inside it, and a card run hands the game its own folder
and nothing else, so the record had nowhere to land and the run
stopped before the game started - the window was already open, so
what you saw was a black screen with your own edit named in the log
above it. A file that belongs outside the booted title's folder is
now named in the log and skipped: nothing here reads it, the
machine's own validator being the only thing that ever does, and the
same edits are what turn that off (v0.208.2). A file missing from
inside the title's folder still stops the run, so does a set built
for another card, and so does a set with nothing in it for this
title, which would be the stock card playing while the tab says it
is testing your edits.
**A scene the game cannot read is named** (v0.217.3). When the game
shows the Stern logo and stops on a `cereal::Exception` (`Could not
find type id ...`), the log now says which scene file it was reading,
how far in, and whether that file is one of your edits; if it is,
untick *Apply my replaced assets on top* and run again to confirm.
**And your edits run on top of a card PAD built** (v0.217.4). Every
spot in an extract - where each scene picture sits, which lines of
text are the stock ones - was measured on the card the project was
extracted from. A card PAD built already carries earlier edits, and a
picture kept at its own size or a longer line of text moves
everything after it in its scene, so edits prepared from the built
card went where its scenes no longer had them: the game stopped at the
Stern logo (v0.217.2), or the pictures in that scene were skipped and
the run was refused (v0.217.3). When the card you pick is the same
game and version as the card your project was extracted from, the
edits are now prepared from that original and run over the card you
picked, and the log says so. The result is what a fresh build would
put on the card. A card of another title or version is still used as
it is, with a note in the log, and so is a picked card whose original
is no longer where the extract found it.
**And a replaced video plays** (v0.219.1). The video decoder runs on
the PC, outside the folder your edits are laid over, so a clip you
replaced used to play as the stock one while every other edit
showed. The run now tells the video player where your edits are, it
plays each clip you replaced from them, and the log marks every such
play `(your edit)`; a run without edits plays the card's own clips as
before.
**And a built card keeps its own game program** (v0.219.3). Your
edits carry a copy of the game program, prepared from the card your
project was extracted from, and that copy replaced the program of the
built card you picked, along with everything its build had changed
there. A card built with longer sounds then showed GAME VALIDATION
ERROR, UPDATE SD CARD once a game started, but only with your edits
on top. The edits now keep every program byte the picked card's build
changed and they leave alone, the log says how many, and your own
edits still win where both changed the same byte. A card whose
program was rebuilt whole (blip-free sounds, longer program text) is
named in the log and runs with the prepared program as before. A set
prepared for another card is rebuilt at the next Start.
**The log names the validation check** (v0.220.3). GAME VALIDATION
ERROR, UPDATE SD CARD is one banner for six different checks; a run
now says whether the program it uses has its validator switched off,
and when a check goes up it logs a `[validation]` line naming it, by
number and with the values Tech Alerts shows (for example `#4 2534:2
- the sound bank, 2 record(s) failed`).
A **virtual playfield** window opens beside the game: the title's own
artwork with every switch, coil and insert drawn on it, inserts lit
live off the node bus, and switches you can click or press and hold
the way a ball would. All of it is read out of the card when the
title first runs — the artwork out of the game's assets, the
positions out of the game binary's own device table — so any title
works without anything being added to this repository first. A title
that ships no playfield drawing (many don't) gets a clickable
schematic of its switch list instead — and from v0.150.0 that is
known to be a property of the game's SOFTWARE VERSION rather than of
the title: Godzilla LE 1.13.0 ships neither the drawing nor the
device table while V1.14.0 ships both, so updating a card can turn a
schematic into a real playfield. From v0.151.0 the schematic view
carries the Start, Plunge and Reset balls buttons too — they had only
ever been drawn on the artwork, beside the plunger, so on a title with
no drawing there was nothing in the window that could put a ball into
play.
**The cabinet's own lights get a column of their own.** Left of the
artwork the window draws the topper (on the topper's own drawing
where the title ships one), the backbox speaker lights and the
expression-lighting blades as two bars, all lit live; each section
appears once its board has sent anything, and a topper switched off
the bus gets none. The side panel's **CABINET LIGHTS** box lists the
boards and carries an **Expression lights (blades and speakers)** tick
box: untick it to hide them (on a title with no artwork their blocks
leave the LED grid too). The window remembers the choice; it changes
the display only, never the game.
**The window can start a game, and it says what each press did.**
From v0.208.0 the row begins with **Insert coin**: pressing Start on a machine with
no credits does nothing, and does it silently, so a mouse-only session
could never get past attract mode — the coin had only ever been on the
keyboard. And every one of those buttons, plus a click on a trough
ball, now reports the helper's own answer in the status bar for a few
seconds ("shooter lane opened (ball launched)", "the trough is empty -
nothing to eject", "a game needs CREDITS"). Those sentences were being
printed and thrown away, which is why a press that could not do
anything looked exactly like one that had.
**A ball played with the mouse ends when it drains.** From v0.212.9 a
click in this window counts as somebody playing, so with ball save on
the ball feeder no longer takes the game's own re-served ball back to
the trough five seconds after it launches, and it keeps a way home
for every launched ball instead of one — which is what left a drained
ball never ending, Start refusing and the game searching for balls.
From v0.224.2 that judgement is about the ROOM and not about one
ball: while anybody has moved anything in the last minute, no
launched ball is taken back at all, so watching a battle play itself
out without touching the controls no longer hands your ball back to
the game and leaves your own Drain with nothing to end.
Plunge only launches the ball waiting in the shooter lane and never
serves one from the trough. With the key panel up, the bottom button
row is gone: Start Button and Left Coin are clickable rows in the key
list, the BALLS section reads trough, lane, in play and fed on one
line above Plunge, Drain and Reset balls, and Clear alerts is
**Clear switch alerts** under SERVICE. Drain is greyed out until a
ball is actually in play: a ball still waiting in the shooter lane
has to be plunged first, because draining it there told the game a
ball had come home while one still sat in the lane, and the machine
could never serve its next ball.
**A one-screen cabinet now draws at its own panel size.** The
machines that carry a single screen instead of a backbox-and-topper
pair — James Bond 60th, Star Wars Home Edition, Jurassic Park The
Pin — render at 800x480, and the rig used to hand every title the
same default size and merely shrink the WINDOW afterwards. That
shrinks the wrong picture: handed a size its scene was never drawn
for, one of those games paints its service screen into the top-left
corner and leaves the rest black, and another puts its
bottom-right badge 57% of the way across. The reported panel now
sizes what the guest RENDERS as well as the window, so those titles
come up the shape the real cabinet is; a size named by hand still
wins. Two things follow from a run's size no longer being fixed:
a remembered window position now records the render it was framed
around, so a size you left at 1360x768 is never replayed over an
800x480 window, and a save-state slot records its render size too,
which lets loading a checkpoint taken before this change be refused
in the pre-flight — before the running game is killed for it,
rather than after.
**A Home Edition's inserts light.** Star Wars Home Edition and
Jurassic Park The Pin drew every insert dark through the whole
attract light show, on a playfield window whose own status bar was
counting tens of thousands of decoded lamp writes at the same time.
A Home Edition is ONE playfield board, and both titles describe
their whole machine — flippers, trough, pops and every positioned
insert — in a single group of the game binary's device table: a
group the rig had pinned to the board number a full cabinet uses for
its cabinet wiring. Neither machine has that board at all, so every
lamp on it was addressed to nothing. That pin is now read from the
table's own wiring column, when a majority of the group's rows name
one board, and it gives way to whatever the running game says about
itself instead of overriding it. Measured across every title in the
library that carries a device table, exactly two maps change, and
they are these two.
**And those inserts light at the brightness the game asked for.**
The one lamp command a Home Edition drives its whole attract picture
through carries the level as two bytes — the shape the frame has
always been written down in here — and the rig read only the first
of them. Jurassic Park The Pin holds nine lamps up during attract;
seven of them came out as off and the other two at 2 and 3 parts in
255, which is a field report of exactly two lit inserts on a machine
that should show nine. Both bytes are read now, against a full scale
of 0x800 taken from what the wire actually carries rather than from
the width of the field: across 10728 writes on two titles the levels
land on eighths of full and stop at eight eighths, and a title that
ever sends past that reads as full rather than wrapping back around
into a dark lamp. It is the command that decides this and never the
model — the full-size Jurassic Park cabinet lights 42 inserts the
same way and was dimmed the same way — and a level of zero still
decodes as zero, so the titles that only ever use this command to
turn a lamp off are unmoved.
**And a Home Edition's light show runs.** From v0.212.9 the inserts
on Jurassic Park The Pin and Star Wars Home Edition cycle through
attract instead of holding nine lamps still, and two things were in
the way. The rig decides a game is past its Tech Alerts screen by
watching for a light show, and a Home Edition re-sends the same
lamp levels about eleven times a second while that screen is up, so
a parked machine passed for one in attract and nothing ever pressed
Service Back. A show now has to CHANGE the lamps, at the pace a real
attract does, before it counts, and a run whose lamps are busy but
never change says so in its log. The retry press waits 75 seconds
instead of 45, so it cannot land in a show that has already started.
And the show those insert boards actually run is a lamp command the
rig refused on an insert board; it is decoded now, checked against
a full-size title's own LED test (the lit lamp agrees 657 of 657
and 1522 of 1522), and it owns the lamps it addresses, so the steady
refresh command no longer writes over them and invents changes the
wire never carried.
**The switch list carries the game's own names.** A title whose
device table describes only a handful of its switches used to leave
the rest of the list as question marks — one 105-switch machine
showed fifteen named rows — because the one place that had the
other ninety, the game binary's own static switch table, was never
asked for names. It is asked now, joined on the wire (node and bit)
and nothing else, because that is the only key the two readings
agree on; a wire the static table lists twice is left alone rather
than guessed at. The walk costs about ten seconds and is paid once
per build, remembered in the switch list itself. And a row the rig
cannot address yet is drawn dimmed and left out of the click map
instead of staying clickable and pressing some other switch, with
how many are in that state shown under the list.
**The balls are real now, as far as the game is concerned.** A pinball
machine asks for a ball by firing its trough eject coil and then waits
for a trough switch to change; until v0.125.0 nothing answered, so a
ball only ever moved because you told it to and multiball could not
happen at all. The rig now watches that coil and answers it, which is
enough for the game to serve a ball at the start of a ball, re-serve
after a save, and feed a multiball. A strip under the playfield shows
the six trough positions in trough order with how many balls are in
play, and the positions are the control: click one with a ball in it
to take a ball out, click an empty one to bring a ball home from
play. Which switch actually moves is decided by the trough's shape
rather than by which dot you clicked, because a trough is a ramp and
the hole always appears at the far end.
The emulator's windows **come out in front of this app** when a run
starts, rather than opening behind it — Windows won't let a program
jump in front of the window you just clicked, so the rig keeps asking
until it's allowed, which can take a few seconds. And a **Reset
windows** button puts them all back to their default positions if one
ever ends up somewhere you can't drag it back from. That button is
now the second thing to reach for rather than the first: the rig
remembers where you last left each window, and a remembered position
that is off *every* screen is no longer restored at all, so a window
parked on a second monitor that was later unplugged opens where the
desktop puts it instead of out of reach, and the log names the
position it dropped. The check is deliberately the weakest one that
still catches a window nobody could see — a window half off an edge,
or on a second monitor the desktop still spans, is left exactly where
you put it — and the remembered *size* is always restored, because a
size cannot hide a window. A desktop that refuses a move outright is
also taken at its word now, after two readings that don't budge,
rather than aiming further away on each of six tries. The button
still exists for everything those leave alone, and works on every
platform, running or not.
**Pause** — the Pause key or F9, in the game window or the virtual
playfield window, or the Pause button on the playfield's status bar,
freezes the whole game on the current frame, video and sound
included, for as long as you like, and the next press carries on
from exactly that frame: the game's own clock stands still while it
is frozen, so nothing jumps ahead on resume. The same status bar
carries the tab's volume slider and Mute.
**Save states**, on by default — every Start boots the guest in the
one shape that can be checkpointed, so there is nothing to tick, and
the ⓘ beside the section title spells out what a save costs. The
virtual playfield window carries Save state / Load state buttons
with ten named slots per game, and the Emulate tab carries a slot
manager listing every slot's name, game, size and save time,
updating itself the moment
anything changes — no manual refresh. A save checkpoints the whole
running game — game binary, GPU state, video, sound, switch memory
— and a load brings it straight back, mid-game included, even in a
different session or after the card's assets have been swapped
(streamed video and audio play the new versions; artwork already on
screen at the save keeps its saved look until the game redraws it).
Slots are compressed to roughly a twentieth of their raw size, so
ten of them cost tens of megabytes rather than gigabytes; a save
briefly needs headroom on disk while it packs. A **Launch** button
on the manager starts the emulator straight into a chosen slot, or
drops the slot into a game that's already running. (Windows: that
boot runs the guest as root and drops every helper back to your own
desktop session so the window and the sound still work. It is the
one thing here that needs `busybox-static` and `criu`, and a machine
without either starts the ordinary way instead — every title runs,
one log line says save states are off and how to turn them on.)
A run that cannot be saved says why on the button instead of failing
quietly. From v0.196.1 the save-state controls take a row of their
own when the window is too narrow to hold them beside the game
buttons. The two clusters grow from opposite edges of the playfield,
and the window is sized from your screen, so on a shorter screen they
used to meet in the middle and draw on top of each other — the slot
picker over Start, Load state over Plunge, four buttons visible and
two of them unclickable. The fit is measured rather than assumed, so
a window with room to spare looks exactly as it did.
A **Volume slider and Mute** sit next to the Sound checkbox — the
level of the emulator's own sound coming out of your PC speakers,
not the in-game volume adjustment on the machine's own coin door.
Both work live, on a run that's already going, with no restart, and
the level you leave them at is remembered for next time.
A **Country (DIP switches)** and **Power** row sits under the card:
it is the cabinet the card is fitted to. Pick a country and the
machine is set to it — the CPU board's eight country DIP switches are
set to match, and so is the country stored in the machine, which is
the one the boot screen shows. A game whose country has just changed
opens its own Guided Setup to confirm it, as a real machine does. The
default, **As set in the game**, changes nothing. **Power** is the
mains: 60 Hz, as the emulator has always run; 50 Hz as a European
machine (a 50 Hz board, which boots normally); or 50 Hz as a US
machine (a 60 Hz board, the combination the game refuses to run on;
from v0.219.4 the emulator leaves that refusal up instead of pressing
past it). Both are remembered for every project and take effect at the next
Start.
Runs on Linux, and on Windows through WSL2. The rig ships with the
app, in `tools/spike2_emu`, and the prerequisites installer pulls in
what it needs (`qemu-user-static`, an ARM cross-compiler, `gcc` +
`libc6-dev`, `make`, `e2fsprogs`, `fuse3`, `ffmpeg`, `python3-gi` and
`gir1.2-webkit2-4.1` for the playfield window, `busybox-static`). Two
compilers, because two different things get built: the hardware shim
is ARM and the renderer that draws the picture is a native binary for
your own PC, so having one of them says nothing about having the
other. And `ffmpeg` *inside the distro*, which is a different copy
from the one the app puts on your PATH on Windows: the game decodes
neither its video nor its sound itself — its own decoder is that
i.MX6 block — so both are decoded out on the Linux side. It is the
one prerequisite whose absence stops nothing. Everything else here
builds or mounts something, so lacking it ends the run and names
itself; lacking this one lets the emulator build, boot, open its
window and hold 60 fps, and play black and silent. The run now
checks for it before it starts and says so in one line naming the
package, instead of leaving it to arrive as a decode error per clip.
`busybox-static` is the odd one out in the other direction: it is
what *save states* need, not what the emulator needs. The
checkpointable boot swaps its root for the guest's and then has to
let go of yours, which takes two native programs inside the guest
root — a static shell and a `pivot_root` — and no machine has them
by default. The one package carries both, so there is still only one
thing to install. A run that can't find them starts anyway, in the
boot shape the rig has always used, and so does a run whose swap is
refused after it has begun; either way one line says save states are
off and which package turns them on, and the playfield leaves its
Save and Load buttons out of that run rather than offering a slot it
cannot fill. The tab says the same thing before you press Start,
without claiming the PC can't emulate, because it can.
Save states need one more thing, and it is the only prerequisite here
that is not a package at all: **`criu`**, the program that actually
freezes the running game and thaws it again. No Ubuntu publishes it —
`apt-cache policy criu` answers with an empty table — so *"Set up
emulator…"* builds it from source, once, which takes a few minutes
and is named as a build rather than an install before it starts. It
is checked against your own kernel (`criu check`) before it is
installed, because a criu that can't freeze anything would only turn
the warning off and leave the buttons just as dead. That build now
carries criu's own later fix for one of its feature probes, which a
2026 compiler answers backwards — without it the build stops with
`conflicting redefinition of enum` on a brand-new Linux install — and
it now takes that same later release's fix for the *other* line a 2026
machine stops on, `discards 'const' qualifier` on `strrchr`, 250 files
further in: C23 made `strrchr` hand back a const pointer when it is
given one, and this pinned source predates that. Asking for the older
C dialect looked like it should settle that second one and doesn't —
criu turns the new behaviour on itself, through a define of its own,
whichever language you ask for — so the line is corrected the way
criu's own later release corrects it. The dialect is still asked for,
because it is what this pinned source was written and checked in.
With all of it, the same source builds on old and new compilers alike.
Anything whose absence costs a *feature* rather than the emulator is
listed apart from the rest, under a heading that names the feature,
so a missing package is never read as a PC that cannot emulate. Save
states are one such heading and **`make`** is another: the boot menu
a multi-boot card starts up into is an ARM program built by a
Makefile, so a machine without `make` answered a multi-boot **Build**
with the shell's own `make: command not found` while running every
title perfectly. It reads as **Multi-boot cards need: make** now, and
is asked of every desktop rather than only of Windows, because a card
is built the same way on all of them.
One more machine shape works without being told about now: WSL can be
configured so Linux can't start a Windows program at all
(`[interop] enabled=false`), and the virtual playfield *is* a Windows
program on Windows, because WSL has no GUI toolkit for it. That
window used to be impossible to open on such a machine. The run now
asks PAD to open it — PAD is already a Windows program with the right
Python — and PAD closes it again when the run stops.
On a machine where Linux *can* start a Windows program, that window is
opened with a Windows Python, and which one used to be whatever
`pythonw.exe` the PATH answered with. A stock python.org install has
the toolkit the window is built from but not the imaging library its
artwork is drawn with, so a run came up with a game window, sound and
switches and no playfield at all, and nothing anywhere said why. The
interpreter is chosen now rather than inherited: every Python the rig
knows of is asked whether it can import both, PAD's own bundled one
first — it ships with both, because the app draws itself with them —
and the run names the one it opened the window with. The tab says it
before you press Start as well, beside the sound player: which
interpreter opens the playfield, or that the one found has no imaging
library, with the single command that adds it.
A run that comes up with **no game window at all** now says which of
the two possible things happened, where before both looked the same:
the playfield opens, the log says the emulator is up, the guest really
is running, and there is no picture. When the window does exist the
run names it — `game window opened 1920x1080 on DISPLAY=:0` — and a
desktop showing nothing after that line now gets both of its causes,
in the order worth trying: the window opened somewhere you cannot see
it, cured by Stop and *Reset windows*, or WSLg is not mirroring it,
cured by Stop and *Restart WSL…* — which nothing inside Linux can
work out for you, because nothing inside Linux can see the Windows
desktop. The restart used to be the only advice offered, and it does
nothing whatever for the first case: the coordinates come straight
back out of the same file on the next run. When the renderer went
without a window instead, a block says so loudly and quotes the
renderer's own reason, and the run carries on rather than dying — the
guest boots, the sound plays, the playfield answers, and only the
picture is missing. From v0.205.1 that is no longer where it ends,
because there are two reasons for no window and one of them is worth
a second attempt. When the window opened and the graphics driver then
refused to give it a drawing surface, the renderer is stopped and
started again on the software rasteriser, which asks that driver for
nothing — the same cure a renderer that *died* on the same driver
already had, for the same reason: the graphics libraries Windows
injects into a running WSL go stale under a session left up for days,
which is why a reboot has always seemed to fix this. The picture
comes back, but software is not free on a visible run: the renderer
takes one to two CPU cores instead of a few percent of one, and the
game's videos stutter when the PC cannot spare them. So the run log
and the Emulate tab's Renderer row (amber, *no GPU*, with an info
badge) say why the GPU was given up — by name when WSL has lost the
graphics card because Windows updated or reset its driver under a WSL
that kept running — and give the cure: Restart WSL…, and restart
Windows if the next run says it again. A software renderer that will not start
hands the GPU one back rather than ending the run, because a run with
no picture is still a run. The other reason — no X server to put a
window on — is deliberately not retried, because no renderer can cure
it. And the window that did open comes back down when it is given up
on: nothing can ever paint it, so leaving it there put the game's
name in the taskbar over a preview that stays blank, which is what
the report behind this looked like from the desktop. The commonest
cause of all is checked for before the renderer even starts, because
`DISPLAY` being *set* is not the same as an X
server being reachable: WSLg sets it when the distro starts and never
takes it back, so anything that mounts a fresh `/tmp` over WSL's own
bind mount — systemd's `tmp.mount` does exactly this — hides the
socket from the renderer while leaving it in `/mnt/wslg/.X11-unix`.
The run binds it back when it is root, which the app's own launch is,
and when it can't it stops with the one `sudo mount --bind` command
that fixes the machine instead of spending a whole run drawing
nothing.
A window that opens and stays **black** is the other half of that,
and no instrument could tell its two causes apart: a picture that is
black where it is *drawn*, and a picture that is drawn correctly and
then lost between the graphics card and the Windows desktop. Both
arrive as a log in which every reading is healthy — card mounted,
guest booted, attract reached, clips decoding, frames swapping at 40
fps. The renderer now answers that question directly: it reads the
screen every few seconds and says whether there is a picture at all,
in at most four lines that reach the app's log pane, and only when
the answer changes — the first picture, one that goes away, one that
comes back. The fourth needs no waiting at all: video frames
arriving into a screen that stays empty means the black is being
*drawn*, so the window is innocent and *Restart WSL…* is not the
cure. It counts lit pixels rather than a percentage, because a dark
scene with a small logo rounds to zero and would be reported as a
black screen. `PAD_GL_PICCHECK` sets the seconds between readings
(default 5), or `0` switches it off.
One cause of that black window is now named before you press Start:
a WSL that **logs in as root** can't attach to the WSLg X server's
shared memory, so the game window opens black while the sound, the
switches and the playfield all work perfectly. The tab says so, and
says the cure — give the distro an ordinary user account and make it
the default — and the renderer's own Mesa complaint is carried to
the log pane instead of ending up in a file the app never shows.
Nothing is changed for you: which user a run starts as is a WSL
setting, and a guessed one is easy to get wrong in a way that trades
a black window for a renderer that can't start at all.
That notice was right about the machine it describes and, until
v0.196.1, fired on a second machine it could not help. Every Start is
elevated, and the run hands its helpers back to your desktop account
before the game window opens, or the renderer cannot reach the
display. It worked out which account that is by asking who owns the
extracted guest filesystem — the one folder an elevated run creates
for itself, which therefore answers *root* on any PC where this app's
own Start was the first thing ever to build it. The hand-back was
skipped, the window was black on that run and on every run after it,
and the notice then blamed a login setting that was already correct:
the setup check in the same log said the distro logs in as an
ordinary user. The question is now asked of the emulator's home
folder, which is where the rest of the emulator already asks it, so
an elevated run on an ordinary distro drops back to you as it always
meant to. A distro that really does log in as root still owns a root
home, still gets the notice above, and the cure named there is still
the right one. A stray *"integer expression expected"* line during
the same first build is gone too — it came from the count of the
ownership notices an elevated extraction never produces, and it was
only ever noise in the middle of an extraction that was going fine.
The run also stopped claiming you closed the window when you didn't.
*"renderer exited (window closed)"* was printed on nothing more than
the process being gone, so a renderer that **died** read exactly
like someone clicking the X. It now claims a close only when the
renderer says it was closed, and otherwise shows the renderer's own
last lines.
The tab checks for those before
you press anything, instead of leaving the run to hit them one
failure at a time: on a machine that already has them there is
nothing to see, and on one that doesn't an amber notice names the
fault and each missing package with what it's for. That question is
also the first thing to touch WSL after the app opens, and the first
WSL touch after a Windows reboot boots the whole WSL VM — tens of
seconds, sometimes minutes, that used to look like a frozen app. The
tab now says *"Starting WSL — the first start after a Windows reboot
can take a minute"* and stays fully usable while it boots. On Windows a **Set
up emulator…** button repairs it — it installs the missing packages
into WSL, registers the kernel's handler for 32-bit ARM programs, and
turns on systemd in `/etc/wsl.conf` so that registration survives a
WSL restart. It lists every package and file it will touch before it
changes one, and needs no password (`wsl -u root` is already root).
That registration lives in the *running* kernel, which makes
*Restart WSL…* one of the two ways a machine that could emulate a
minute ago quietly stops being one — on a distro that doesn't boot
systemd, the restart takes the ARM handler with it. So the restart
now asks the machine what it left behind instead of assuming it left
everything: the log says it is looking (the check is what boots WSL
back up, so on a cold VM the wait is the check, not a hang), and a
machine that came back unable to emulate gets the amber notice and
the **Set up emulator…** button right there — where before the tab
went on showing the machine it had probed at launch and the next
Start failed with `chroot: failed to run command '/bin/sh': Exec
format error`. A machine that came back intact is told nothing.
Silence from that notice used to mean two different things —
*asked, and nothing is wrong* and *nobody ever asked* — which left
anyone staring at a black window with nothing to press and nothing
to send. A **Check setup…** button now sits beside it, on every
platform. It changes nothing at all (the probe is read-only, so it
needs no confirmation dialog and no password) and it always answers,
in full, into the log pane: which packages are present, whether the
32-bit ARM handler is registered and whether it survives a restart,
who the distro logs in as, whether it can start Windows programs,
which display it has, and a closing line saying whether this PC can
run the emulator. A Mac gets the question a Mac has instead — there
are no OS packages to install there, so what it reports is Docker,
naming the path the `docker` command was found at and the engine
found behind it. It
asks four things the package check never did —
the login user, Windows interop, the display state, and whether the
good audio path is available at all — and each of them, when wrong,
becomes a notice line naming what that machine will do wrong and
what to change. None of the four is something a button can install,
so **Set up emulator…** no longer turns up underneath a notice it
has nothing to do about.
The audio one names the interpreter, the way the Mac's line names
its docker. A Windows Python that merely lacks the package now
reads as that path *with no sounddevice on it*, rather than as no
Python at all — two different machines that used to get the same
sentence and the same advice, only one of which it fitted — and
the cure underneath is the one that fits the machine it is on.
From v0.173.3 that is usually not a command at all. Every packaged
Windows install already ships a Python of its own, and the rig now
looks at that one first, so a machine whose only problem is the
missing package is sent to the gear menu instead of a terminal:
**Prerequisites** → **Install / repair prerequisites**, tick
**Stern Pinball**, nothing typed anywhere. A Python you installed
yourself still gets a command, but it names that interpreter's own
folder rather than the `py` launcher — which is an optional tick
in Python's installer and need not exist at all, and on the PC
behind this fix did not — so it reads `cd "<folder>"` and then
`.\python.exe -m pip install --user sounddevice`, because a quoted
full path on its own is a string in PowerShell, not a program to
run. A PC with no Python anywhere is pointed at python.org and the
**Add python.exe to PATH** tick. The search behind the line asks
the `py` launcher, and now PATH as well, so an install made
without the launcher is found at all. Fresh installs ship with the
package already, and existing ones pick it up the first time they
repair prerequisites.
On macOS that button now exists too, and does the one thing a Mac can
be missing. `docker` there is only a client: a Mac can have it
installed, on PATH and answering, with nothing behind it that runs a
container — which used to read as *"Docker isn't running"*, advice
about a Docker Desktop that Mac never had. A client with no engine is
now told apart from a stopped engine, in the check, in what Start
says when it refuses, and in the button: **Set up emulator…**
installs the engine (and the client too, if that is missing as well)
with whichever of Homebrew or MacPorts is already on the machine and
then starts it — in this window, streamed into the log pane, never
in Terminal. It lists what it will do before it does any of it, a No
changes nothing, and the half that needs a password is asked for by
macOS itself in its own dialog; saying no to that is reported as your
answer, not as a failure. Finding any of it stopped depending on PATH
as well, because a Mac app launched from Finder inherits almost none:
Homebrew's, MacPorts', Docker Desktop's, OrbStack's and Rancher
Desktop's own directories are searched too (`PAD_DOCKER` overrides).
That is also what un-silenced the Mac's speaker — the container's
sound is played on the Mac by `ffplay`, which was being missed the
very same way.
A package that is missing and a package apt can actually *install*
are two different facts, and the tab now reports both. Ubuntu
publishes `qemu-user-static` in its `universe` component while the
rest are in `main`, so a WSL distro with universe switched off
answers `E: Package 'qemu-user-static' has no installation
candidate` — and because `apt-get install a b` is all or nothing,
none of the others go on either. The notice says separately that WSL
can't install that package and why, turning universe back on is the
first line of the confirmation dialog, and the fix does that before
it installs anything, one package at a time so an unobtainable one
can't block the rest.
Both of those readings come out of apt's *downloaded* package lists
rather than out of the sources config, so neither question is asked
at all until there is an index to answer it from — a WSL distro that
has never run `apt-get update`, which is how a freshly installed one
ships, used to be told its sources offered none of the four packages
and that universe was switched off, on a machine where all four
install perfectly. When a release genuinely doesn't publish one, the
notice names the release, the components apt has switched on, and the
distro to move to, rather than guessing at a cause it never checked.
One package doesn't need that move: `qemu-user-static` depends on
nothing, so the fix downloads it from Ubuntu 24.04's archive and
installs that file. It happens under a throwaway apt root, the
downloaded file's own `Depends` is re-read and the install refused if
it has any, and your package sources are left exactly as they were.
The confirmation dialog names that as its own step, because it isn't
an `apt install`. When there is still nothing the button can do it
goes away instead of sitting under a notice saying the package can't
be installed — a tester pressed that button twice — and the notice
carries the two `wsl` commands that switch to a distro which has the
package.
Ubuntu 25.10 and 26.04 LTS need neither: their qemu no longer ships a
`qemu-user-static` package or a `qemu-arm-static` file. The static
interpreter is plain `/usr/bin/qemu-arm` from `qemu-user`, and
`qemu-user-static` is only a name that `qemu-user-binfmt` provides. From
v0.212.1 the tab, both installers and the emulator accept that
interpreter, and the notice, the dialog and the printed command ask apt
for `qemu-user-binfmt`. Up to v0.212.0 a 26.04 machine was told the
package was missing and that its release did not publish it.
On Linux there's no button — sudo would want a password a GUI app has
nowhere to ask for — and the notice prints the exact command for that
machine instead, `sudo add-apt-repository universe` first when that
is what's wrong. Otherwise there is no setup step: pick a
card image and press Start. The first run builds the guest filesystem
the game runs inside out of that card (a few minutes, once, no root
needed) and compiles the hardware shim and the GL renderer, and every
later run rebuilds any of them whose sources an update has moved on.
Those compiles happen on *your* machine with *your* compiler, so when
one fails the log now shows the compiler's own error lines and writes
the full output to a file it names — up to v0.119.0 it showed the
last eight lines instead, which on a real failure were eight harmless
warnings from a file that had compiled fine.
All three used to be manual steps that `rootfs.sh` only printed as
advice and nothing enforced, so a fresh install failed at whichever
one you stopped at — with an error naming a missing ring or binary
rather than the step. Every run also *proves* the guest can start a
program before it starts one, in about 25 ms, because a guest
filesystem that exists is not one that runs: an extraction that
stopped part way, a missing ARM loader, and the two ways the ARM
translator can be missing from the kernel all produce the same one
line, `chroot: failed to run command '/bin/sh': No such file or
directory`, and nothing else to go on. Three of the four are now
repaired for you out of the card you are already running; the fourth
is the one that needs root — on Windows the **Set up emulator…**
button above has it, on Linux it is named instead, with the
command that fits this machine. Start the app as yourself and never
with `sudo`: one elevated start used to leave everything the rig
builds - the hardware shim, both halves of the bridge, the GL
renderer, every stamp it keeps - owned by root, and every later run
as you then could not write them and stopped on a bare refusal with
no file named and no cause. From v0.223.1 a run that does have root
hands each of those back to the account that owns your emulator
folder as it writes them, so an accidental elevated start no longer
poisons the ones after it; the writes that could still fail say
which file, who owns it and who you are before they stop; and a run
that meets root's leftovers names the cause it almost always is, an
AppImage started under sudo, and carries on. It is a Linux program
throughout: the Windows-looking parts are workarounds for what WSL
lacks (no GUI toolkit for the playfield window, a degraded audio hop), and the
Linux path skips them. macOS runs it in a container, because
`qemu-user` translates Linux syscalls and the chroot needs Linux
namespaces — there is no port to write, only Linux to run. It needs
a container engine — Docker Desktop, OrbStack, Rancher Desktop or
Colima, and **Set up emulator…** installs one for you — and shows
its picture over VNC: the app opens it in
macOS Screen Sharing by itself once the game is up, with nothing to
install (the VNC password, should Screen Sharing ask, is `pinball`).
Every emulator window lives inside that one Screen Sharing desktop —
click a window to give it the keyboard, drag title bars to arrange —
and sound comes out of the container over a local stream played by
ffplay, part of the ffmpeg the prerequisites already require (looked
for in Homebrew's and MacPorts' own directories now, not only on
PATH, which is what stopped those Macs playing silently).
Nothing has to be added to
Docker's file-sharing list: the app copies the rig into your home
directory, which Docker already shares, and mounts the copy.
Measured at 57 fps in the
container with software rendering. A run used to stop by itself after
about a minute — the "did the game start?" check looked for the WSL
qemu process name, which does not exist in the container — and that
is fixed.

## Jersey Jack Pinball

*Jersey Jack Pinball — Windows via WSL2*

The same
idea for a JJP machine, and a different problem. A JJP game is a
native x86-64 Linux program, so there is no CPU emulation at all: it
runs directly, draws through GLX into a nested X server at the
game's own resolution, and decodes its own video. What Stern spends
three subsystems on, this does not need.
What it needs instead is the **purple JJP USB security key**, and it
is not a check that can be skipped: the game binary is Sentinel LDK
Envelope protected, most of its code is ciphertext at rest, and the
key supplies the AES key that decrypts it. There is no branch to
patch. The keys are also per title, so a Wonka key will not run Guns
N' Roses. Plug it in and press Start — the panel hands it through to
WSL for you rather than telling you to plug in a key you already
plugged in, and it tells a key that is not this title's apart from a
key the licence daemon simply never picked up, because those look
identical and need opposite fixes.
Alongside the game comes a **switch matrix**: the game's own
playfield photograph, decrypted out of the title you are running,
carrying every switch, lamp and coil the machine has. Click a switch
to pulse it, right-click to latch, hover anything for what it is.
Lamps show their colour with brightness drawn as opacity, and coils
flash when the game fires them. A ball feeder answers the trough so
pressing Start actually starts a game and plays it through: serve,
plunge, playfield, drain, next ball. Both windows remember where you
left them.
Nothing in the rig is title-specific — the playfield artwork, the
device positions and the switch names all come out of whichever game
is mounted at run time, so a new title needs nothing added here.

## Dutch Pinball

*Dutch Pinball — Windows via WSL2, or Linux*

Plays
The Big Lebowski or Alice's Adventures in Wonderland from its disk
image (plus an optional update for The Big Lebowski, laid over the
installed version the way the machine does). Start prepares a cached
build per image, then the game runs in its own window with sound, and
a switch window presses or holds any of the machine's switches.

The American Pinball, Barrels of Fun, Pinball Brothers and Spooky
Emulate tabs are described with their manufacturers in
[Supported manufacturers](manufacturers.md).
