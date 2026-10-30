# Supported manufacturers

[← Back to the README](../../README.md)

What the app can do for each manufacturer's machines, and the files it
reads. The README has the short table; this page has the detail. How
each tab works is in [Using the app](using-the-app.md), [Emulate](emulate.md)
and [Multi-boot cards](multi-boot.md).

## American Pinball

- **Games:** 6 (Houdini, Oktoberfest, Hot Wheels, Legends of Valhalla, Galactic Tank Force, Barry-O's BBQ)
- **Reads:** `.pkg` (AES-256-CBC encrypted ZIP)
- **Tabs:** Extract, Write, Replace Audio, Replace Video, Emulate

- **One key opens every title.** The game tree is an encrypted ZIP behind
  a small header, and a single static key decrypts every title from 2020
  to 2024. Write re-zips the changed tree and encrypts it the same way.
- **Emulate AP** plays a title from its `.pkg` on this PC (Legends of
  Valhalla first), with a virtual playfield of lights and switches.
- **Planned:** extracting from the Clonezilla `.iso`.
- Format notes: [docs/AP_PKG_RE.md](../../docs/AP_PKG_RE.md).

## Barrels of Fun

- **Games:** 4 (Labyrinth, Dune, Winchester, Bon Jovi)
- **Reads:** `.fun`
- **Tabs:** Extract, Write, Mod Pack, Replace Audio, Replace Video, Emulate, Multi-boot

- **Needed for recent firmware.** From the April 2026 firmware (Winchester
  4/29, Dune 5/13) BOF ships a custom Godot pack no public extractor reads,
  GDRE Tools included. The app reads it natively.
- **Emulate BoF** plays Dune, Winchester or Labyrinth on this PC, with the
  cabinet switches in their own window.
- **Multi-boot** (Labyrinth): the stock `.fun` and other builds become one
  update with a boot menu. See [Multi-boot cards](multi-boot.md).
- **Bon Jovi is extract-only for now.** Its `.fun` is a vendor-signed disk
  image, so the app can read every asset but can't build an update or
  emulate it yet. Image Info says how an owner could help; notes in
  [docs/plans/bonjovi.md](../../docs/plans/bonjovi.md).

### What Extract does

- Decrypts the `.fun`, pulls out the Godot pack and reads its own file
  directory, so every entry lands byte-exact and is checked against its
  MD5.
- Decodes the game's assets into normal files: QOA audio to WAV, textures
  to WebP, fonts out of their Zstd container.
- Lays the game's own tree out under `pck/`, plus friendly copies of the
  imported assets under `pck/_EDITABLE ASSETS/` (`audio/`, `images/`,
  `video/`, `fonts/`).
- No GDRE Tools needed for any current build; only an old Godot 3 pack
  still goes to GDRE.

### Editing

- **Audio, textures, fonts:** edit the copies under `pck/_EDITABLE
  ASSETS/`. Keep each file's name: the 6-character hash in
  `title_card-7787d7.webp` pairs it back to its Godot file.
- **Video and other plain files** sit at their real path under `pck/`
  (videos in `pck/assets/videos/<mode>/`). Replace them in place, keeping
  the name.
- **Replace Video** lists the ~300 Ogg Theora mode clips (Dune: 297 at
  1280x720). A replacement is re-encoded to the slot's size and frame
  rate, and may be any length: Write re-points the pack's offsets.
- **Loop** on Replace Audio (on by default for `*LOOP*` tracks) makes a
  replacement loop to fill its mode instead of going silent.
- **Write** repacks a new `.fun` and dates it a day past the installed
  code (the editable *Update version* field), so the machine accepts it.
  **Modified Files** previews what will ship.
- **Not round-tripped yet:** edited `.ogg` and `.ttf`/`.otf` files, and the
  compiled scripts and scenes. The build log says so.

## Chicago Gaming Company

- **Games:** 5 (Medieval Madness Remake, AFM Remake, MB Remake, Pulp Fiction, Cactus Canyon)
- **Reads:** `.img` (the raw bootable installer image; Cactus Canyon ships on a microSD master, so image the whole card to `.img`)
- **Tabs:** Extract, Write, Mod Pack, Replace Audio

The installer `.img` nests three disk images inside each other, with no
encryption. The app opens all three; you get the game's asset tree.

| Game | What you get |
|---|---|
| MM / AFM / MB Remakes | A few hundred `.wav` callouts per game, plus the original WPC ROM and boot bitmaps |
| Pulp Fiction | 6 sound banks decoded into ~1,000 `.wav` files, repacked on Write ([docs/CGC_BNK_RE.md](../../docs/CGC_BNK_RE.md)) |
| Cactus Canyon | The Williams DCS sound ROMs, CGC's 756 added sounds and 2,044 colour display pictures, each repacked on Write ([docs/CC_REVISITED_RE.md](../../docs/CC_REVISITED_RE.md)) |

### Options on the Extract and Replace tabs

- **Auto-transcribe samples to callouts.csv** names CGC's numbered sounds
  (`S0197_C6.wav`) by what they say, with `faster-whisper` on this PC. The
  CSV is searchable in Excel.
- **…and rename WAVs using transcripts** renames the files too
  (`S0197_C6 - Get the troops ready.wav`). Write still puts each one back
  at the path the game expects.
- **Auto-name now** names the sounds in an existing project without
  extracting again. A clip that failed for lack of memory shows as `error`
  in the CSV, not `non-speech`.
- **Group duplicates** (Pulp Fiction, Replace Audio) gathers every slot
  with the same recording under one row. Right-click > **Apply to all
  copies** replaces them all.
- **Decode DMD scenes to PNG/MP4** (MM / AFM / MB, experimental) renders
  the WPC ROM's stills, animations and fonts. They are for viewing only
  and never written back. Cactus Canyon's art animations render through a
  colour dot-matrix shader.

### Building and flashing a card

- **Write checks its own build:** it filesystem-checks the game partition
  and verifies the repacked payload byte for byte before handing you an
  image.
- **Build / flash SD card** reads the whole card back after flashing and
  compares it with the image. **Skip verify** leaves that out for one
  flash.
- **Keep the SD card's settings, audits and high scores** (Spike 2) reads
  the card's data partition first and puts it back after the image. A
  card with none (a new one) is refused before anything is written.
- **Administrator:** a flash asks for it when it starts (UAC on Windows,
  your password on macOS). On macOS the first flash may also ask for
  **Full Disk Access**; the message gives the steps.
- **Card diagnostics…** (Write tab) reads a failed card's install log back
  off it and checks the payload, read-only. It shows how far the machine's
  install got, e.g. after a "SHELL ERROR".
- **Old modded cards:** a card built by app version 0.35 or older can
  carry the factory's unfinished ext4 journal, which undoes the mod on the
  machine. The diagnostics flag it; rebuild the card.

## Data East (classic DMD)

- **Games:** 16 (Lethal Weapon 3, Jurassic Park, Tales from the Crypt, Star Trek 25th Anniversary, Hook, Teenage Mutant Ninja Turtles, Batman, The Who's Tommy, Guns N' Roses, WWF Royal Rumble, etc.)
- **Reads:** `.zip` (MAME ROM dumps)
- **Tabs:** Capture (Extract)

These games keep their DMD animations compressed in the ROM, readable only
by the game's own code. So Extract runs the game in attract mode under
PinMAME and records the 4-shade DMD animations with their sound as one MP4
per scene.

- Needs libpinmame and ffmpeg. You supply the ROMs; none are bundled.
- Why there is no static decode: [docs/DE_DMD_RE.md](../../docs/DE_DMD_RE.md).

## Dutch Pinball

- **Games:** 2 (The Big Lebowski, Alice's Adventures in Wonderland)
- **Reads:** The Big Lebowski: `.zip` (full + delta updates); Alice: `.img` (Clonezilla auto-installer)
- **Tabs:** Extract, Write, Apply Delta, Mod Pack, Replace Audio, Replace Video, Emulate

- **Unencrypted.** Both games ship plain files.
- **The Big Lebowski:** give Extract a full image plus the deltas you need
  and it merges them in version order. Write builds an update one version
  newer, so the machine's USB update accepts it.
- **Its colour-DMD video** (`.cdmd`) decodes to MP4/PNG with its sound,
  with an optional dot-matrix look, and re-encodes back into `.cdmd`.
- **Alice:** the game disk is rebuilt from the Clonezilla image, with no
  WSL needed. An option converts its ProRes `.mov` videos to H.264 MP4.
- **Emulate DP** plays either game from its disk image: see
  [Emulate](emulate.md#dutch-pinball).

## Jersey Jack Pinball

- **Games:** 12 (Wonka, GnR, Hobbit, Wizard of Oz, Avatar, Sonic the Hedgehog, etc.)
- **Reads:** `.iso` Clonezilla image, or **directly from the game SSD**
- **Tabs:** Extract, Write, Mod Pack, Replace Audio, Replace Video, Emulate, Multi-boot

- **No dongle needed** to extract or write, on every title including the
  Sonic-era engine. The app recognises each title's scheme from the image.
- **Direct-SSD** reads and writes the game's own SSD with no ISO in
  between. Writes go to both A/B slots, so the change survives the next
  boot.
- **Extract filters:** Graphics, Sounds and File System (the slow full
  dump is opt-in). Extraction runs on every CPU core.
- **Shared engine assets** (sound-test music, menu sounds, the initials
  screen art) come out decrypted in their own `ecoredata/` folder, and
  replace like any other asset.
- **Emulate** runs the real game on this PC with the game's purple USB
  key: see [Emulate](emulate.md#jersey-jack-pinball).
- **Multi-boot:** two install ISOs of the same game code become one
  install stick with a boot menu. See [Multi-boot cards](multi-boot.md).

### Replacing assets

- **Older titles:** a replacement may be any length. Replace Audio's
  **Full length** keeps a longer clip whole; otherwise it is trimmed to
  its slot.
- **Sonic-era titles:** a replacement must keep its original byte size,
  and the app fits it for you. A PNG or WAV takes the slack in its own
  file; a video is padded with no re-encode, or encoded down to fit first.
- **`.ogv` and `.avi`** clips can't be padded, so one that isn't the
  slot's exact size is refused, naming the size to hit.
- **Checksums** the game checks on load are re-made for you.

### Getting it onto the machine

- **Build / make USB install stick…** formats a stick FAT32 and copies the
  ISO's files on: the only stick a JJP machine reads. An Etcher or `dd`
  stick fails with *Failed to mount USB stick*.
- **Leave the purple key in** while it installs, or the installer stops on
  *Security key not found*.
- **Onto the game's SSD:** the same dialog can write the install straight
  onto the SSD in a dock on this PC.
- **ISOs built by app version 0.218.0 or older** carry short file names
  the installer can't find. Build the ISO again before making a stick.

### A brand-new title

The advanced **Decrypt using the game's HASP dongle** box runs the game's
own decryption with its dongle plugged in (Windows/WSL only). It also saves
a `crypto_capture` file a developer can use to add dongle-free support.

If the game hides its crypto entirely, the run saves a `jjp_diagnostics`
archive instead. Sending that file is how a new title gets added; it is how
Sonic's support was worked out.

## Pinball Brothers

- **Games:** 4 (ABBA, Alien, Queen, Predator)
- **Reads:** `.upd`, `.iso` (Clonezilla)
- **Tabs:** Extract, Write, Apply Delta, Mod Pack, Replace Audio, Replace Video, Emulate

**Emulate PB** plays Predator, Alien and ABBA from their files on this PC,
with a virtual switch window. Queen is not supported yet.

## Sega (Whitestar DMD)

- **Games:** 18 (Apollo 13, GoldenEye, Twister, Independence Day, Space Jam, The Lost World, The X-Files, Starship Troopers, Godzilla, South Park, Star Wars Trilogy, plus the Sega-on-Data-East-hardware titles Maverick, Frankenstein, Baywatch, Batman Forever)
- **Reads:** `.zip` (MAME ROM dumps)
- **Tabs:** Capture (Extract)

The same as Data East: the 1994–99 games keep their animations compressed
in the ROM, so Extract records them under PinMAME as per-scene MP4s with
sound. Needs libpinmame and ffmpeg; you supply the ROMs.

## Spooky Pinball

- **Games:** 14 (Beetlejuice, Evil Dead, R&M, Halloween, Looney Tunes, etc.)
- **Reads:** `.pkg`, `.ed`, `.scooby`, `.beetlejuice`, `.looney`, `.iso`, `.zip`
- **Tabs:** Extract, Write, Mod Pack, Replace Audio, Replace Video, Emulate

- **Replace Video** lists every video the game ships in its own tree, in
  any container (Halloween alone has 242 `.webm`).
- **Emulate Spooky** boots a title from its package to attract, with a
  virtual playfield, Volume and Mute: Beetlejuice, Scooby-Doo, Texas
  Chainsaw Massacre, Evil Dead, Looney Tunes, Halloween, Ultraman, Rick and
  Morty and Alice Cooper's Nightmare Castle.
- **The DMD titles** (Jetsons, Domino's Spectacular Pinball Adventure, Rob
  Zombie's Spookshow International) run from their update zip in a window
  of their own, without WSL.
- **America's Most Haunted** can't run: its update carries only the
  display card, not the game program.
- **Total Nuclear Annihilation** can't be decrypted: its key is unknown.

## Stern Pinball (Spike 2)

- **Games:** 26 (Godzilla, Jurassic Park, Deadpool, Star Wars, Iron Maiden, Led Zeppelin, James Bond, etc.)
- **Reads:** raw SD-card `.img` / `.bin` / `.raw`, or **directly from the SD card**
- **Tabs:** every tab the app has

Spike 2 cards are unencrypted ext4: videos and pictures are loose files.
The sounds are the hard part: each is scrambled with a keystream only the
game's own code makes, so the app runs that code in an ARM emulator to
decode and re-encode them bit-exact.

### What you can change

| Tab | What it does on Spike 2 |
|---|---|
| Replace Audio | Every sound, named by the game's own Sound Test menu where it has one. Longer sounds, music modes, play in turn, attract flipper sounds. |
| Replace Video | Every clip, at full size on the card. Random clips, the modes that play each clip, its sounds. |
| Replace Images | Loose pictures, scene textures, font glyphs (one PNG per letter) and the boot screen. A **Fonts** window imports a desktop font into a game font. |
| Scenes | Draws each scene as the machine does; move, resize, tint, hide or add a picture or a line of text. |
| Replace Text | The scenes' text and the game program's own text (mode names, award lines), which may grow longer than the original. |
| Color profile | One colour correction for the whole screen, or a profile baked into chosen files only. |
| Default Settings | The settings and factory high scores a fresh card boots with, including names, and settings the machine's menu hides. |

### Building the card

- **The card passes the machine's checks.** Write refreshes the card's
  `.sidx` validation record for every changed file and switches off the
  game's own self-check, so the machine shows no GAME VALIDATION ERROR.
- **Blip-free callouts:** every replaced sound plays your audio all the
  way through. On a direct SD write about 6 ms of the original plays
  twice inside each replacement.
- **Full-size files** (videos, longer sounds, longer text) need an image
  build through the Linux filesystem driver: WSL2 on Windows, `debugfs` on
  macOS (`brew install e2fsprogs`).
- **SD card size** builds for a bigger card when the stock card's free
  room runs out: see [SD card size](using-the-app.md#sd-card-size-stern-spike-2).
- **Rebuilds are quick:** a second build onto the same image updates it in
  place, and unchanged sounds come from a cache.
- **Port + build** puts your mods onto other stock cards (a new version,
  the other model) and builds each, in one click.

### Reading cards

- **Image Info** (ⓘ beside the pickers) reads a card without extracting
  it: game, version, edition, partitions, asset counts, settings. **Copy
  Report** is for bug reports.
- **Compare** shows what changed between two cards in seconds, from their
  own validation records. Once both are extracted it compares the sounds
  one by one, by how they sound.
- **Partition Explorer** browses any file on the card, and **Replace
  with…** swaps one at any size.
- **Direct-SD** and **Save card as image…** read and write the physical
  card.
- **Emulate** runs any Spike 2 card on this PC: see [Emulate](emulate.md#stern-spike-2).
- **Multi-boot** puts up to 16 games on one card: see [Multi-boot cards](multi-boot.md).

**Older Stern generations:** the era switcher in the Stern card's header
picks Spike 2, Spike 1, SAM or Whitestar. Architecture notes:
[docs/architecture/stern.md](../../docs/architecture/stern.md).

## Stern Pinball (Spike 1)

- **Games:** 6 (WWE WrestleMania, KISS, Whoa Nellie!, Game of Thrones, Spider-Man VE, Ghostbusters)
- **Reads:** Stern's update `.iso` (a raw MBR SD-card image), or a card dump (`.img`/`.bin`/`.raw`)
- **Tabs:** Extract, Write, Replace Audio, Replace Images, Replace Text,
  Default Settings, Mod Pack, Emulate

- **Fast extract.** Every sound is plain 16-bit PCM, so a whole card
  decodes in seconds, one WAV per sound. An unlisted title still extracts.
- **Write** fits each replacement to its slot, matches its loudness and
  refreshes the card's validation record.
- **The DMD's pictures:** Extract writes every one as a PNG in the DMD's
  16 shades: still pictures (`images/pictures/`), the letters of every
  font (`images/fonts/fontNN (H px)/`, each named by its character) and
  animation frames (`animations/`), numbered in the game's order so an
  animation's frames sort together (KISS LE: 24,195 in all).
- **Replace Images** puts edits back in the game's own formats. A picture
  of another size is scaled to fit. A frame busier than the bytes it had
  goes to free space in `image.bin` on every title but Ghostbusters, which
  has none (there it may lose shades, and the log says so).
- **Not in `image.bin`:** the power-up screen (title, version, language)
  draws with fonts built into the game program, so it doesn't change.
- **The words on the DMD** (song names, prompts) are text: edit them on
  Replace Text.
- **Default Settings** edits every operator adjustment (up to 175 on
  Ghostbusters LE).
- **Auto-transcribe, Music ID, per-clip loudness, Flash and Save card as
  image** work as on Spike 2.

### Emulate (Windows via WSL2)

The game boots to its real attract in its own window, beside a switch and
LED window.

- **Play:** every switch is named; arrows are the flippers, `1` starts
  and `5` adds a coin. The trough answers the game, so Start plays a
  full game with sound.
- **Titles tried:** Game of Thrones, Ghostbusters LE, KISS, WWE, Whoa
  Nellie!, Primus, Can Crusher, and Transformers The Pin.
- **Transformers The Pin** (2012 home model) gets its two 16-segment
  displays drawn in red. Hold both flippers three seconds for test mode.
- **Save states:** save a game mid-ball and load it later. Slots are per
  title.
- **Runs beside a Spike 2 game:** each tab manages only its own emulator.

### The app's own Linux (PAD-Runtime)

**Fix setup** can install a small Linux of the app's own as a private WSL
distro (a one-time ~370 MB download). Your own distro isn't touched or
needed, so a PC with WSL but no distro can emulate.

- **Once it's there, everything** the app does in Linux runs inside it:
  both emulators, extract and write, the multi-boot builder, the
  prerequisite check.
- **Your work is kept apart:** extractions, card caches and save states
  live on their own disk under `LOCALAPPDATA`, so replacing the runtime
  keeps them.
- **Spike 2's Update emulator Linux…** appears when the installed one is
  older than the app.
- **Right-click Fix setup** to delete the emulator's data, the downloads
  or the runtime itself. `PAD_RUNTIME=0` goes back to your own distro.

## Stern Pinball (SAM)

- **Games:** 26 (Mustang, Metallica, AC/DC, TRON: Legacy, The Walking Dead, Star Trek, X-Men, The Avengers, Avatar, Iron Man, Spider-Man, Batman: The Dark Knight, Indiana Jones, CSI, Family Guy, Shrek, Pirates of the Caribbean, World Poker Tour, etc.), every version PinMAME has (375)
- **Reads:** the code update as Stern ships it for the USB stick: the `.bin` (The Walking Dead 1.05: `.ebi`), the `.zip` it comes in, or a MAME romset zip
- **Writes:** a copy of that `.bin` with your sounds, pictures and animation frames in, for the game's USB update
- **Tabs:** Extract, Replace Audio, Replace Images, Write, Mod Pack, Capture

| Extracted | Count on TRON | Replace notes |
|---|---|---|
| Sounds (`audio/idxNNNN.wav`) | 1,103, in 8 seconds | Fitted to the slot's rate and length, loudness-matched. Can't be longer than the original. |
| Still pictures and font glyphs (`images/`) | 2,392 pictures, 1,639 glyphs in 44 fonts | Scaled to the picture's size and the DMD's 16 shades. Glyphs are named by number. |
| Animation frames (`animations/imgNNNN.png`) | 4,150 frames | Repacked in the game's own formats. A frame must fit the bytes its animation has; busier art may lose shades, and the log names it. |

- **Write** keeps the `.bin` the same size and fixes its checksums, so it
  installs from the game's update screen like Stern's own.
- **All four sound-engine generations** work (24 titles, World Poker Tour
  to The Walking Dead); each was proven playing in PinMAME.
- **No animation frames** on the 2006-2008 titles (World Poker Tour,
  Pirates, Family Guy, Wheel of Fortune) or Batman: The Dark Knight.
- **Capture:** tick *Use PinMAME runtime capture* to record the DMD
  animations and sound as MP4s. Needs libpinmame and ffmpeg; pick the
  **SAM** era on the Stern card.
- Details: [docs/plans/sam_compatibility.md](../plans/sam_compatibility.md).

## Stern Pinball (Whitestar)

- **Games:** 17 (Monopoly, Elvis, The Lord of the Rings, The Sopranos, The Simpsons Pinball Party, Terminator 3, Ripley's Believe It or Not!, NASCAR, Austin Powers, Playboy, etc.)
- **Reads:** `.zip` (MAME ROM dumps)
- **Tabs:** Capture (Extract)

The same as Sega's Whitestar games: PinMAME records the DMD animations
with their sound as MP4s. Pick the **WHITESTAR** era on the Stern card.
Needs libpinmame and ffmpeg; you supply the ROMs.

## Williams (WPC-era)

- **Games:** 41 WPC titles (Attack From Mars, Medieval Madness, Twilight Zone, Theatre of Magic, Fish Tales, etc.)
- **Reads:** `.zip` (MAME ROM dumps)
- **Tabs:** Extract (static and capture)

Two extract paths, each with its own checkbox on the Extract tab.

### Static extract (decoded from the ROM)

A Python port of [permartinson/wpcedit.js](https://github.com/permartinson/wpcedit.js)
(after Garrett Lee's WPC Edit) reads the ROM's picture, animation and font
tables.

| Output | What it is |
|---|---|
| `dmd_scenes/scene_*.png` | Every full-frame DMD picture (~800–1,400 a game) |
| `dmd_scenes/pairs/pair_*.png` | 4-shade composites of paired planes |
| `dmd_scenes/browse.mp4` | Every scene at 2 fps, to skim |
| `animations/anim_*.mp4` | The game's animations, one MP4 each |
| `fonts/font_*.png` | Every DMD font as a sprite sheet |
| `sounds/track_*.wav` | Every DCS music cue, voice line and effect (1993+ games only), via a bundled [DCSExplorer](https://github.com/mjrgh/DCSExplorer) |

**Auto-transcribe samples to callouts.csv** (DCS games) names the sounds
by their spoken callouts, as on CGC.

### PinMAME runtime capture

[libpinmame](https://github.com/vpinball/pinmame) plays the game: it adds
credits, presses Start and plays scripted shots. Each moment is saved as
an MP4 with its sound (`skill_shot.mp4`, `multiball_start.mp4`…).

- **16 titles** have hand-tuned scripts of 10–21 moments: AFM, MM, ToM,
  FT, WW, TZ, AF, STTNG, IJ, JD, NGG, T2, DM, RS, SS, Dracula.
- **The other 25** use a generic playthrough built from each game's switch
  layout.
- **While it runs,** a live DMD preview and a switch grid show; click a
  switch to press it.

## Per-game lists

The full game lists live in the plugin sources:

- [ap/games.py](../../pinball_decryptor/plugins/ap/games.py)
- [bof/games.py](../../pinball_decryptor/plugins/bof/games.py)
- [cgc/games.py](../../pinball_decryptor/plugins/cgc/games.py)
- [jjp/games.py](../../pinball_decryptor/plugins/jjp/games.py)
- [pb/games.py](../../pinball_decryptor/plugins/pb/games.py)
- [spooky/games.py](../../pinball_decryptor/plugins/spooky/games.py)
- [stern/games.py](../../pinball_decryptor/plugins/stern/games.py)
- [williams/games.py](../../pinball_decryptor/plugins/williams/games.py)
