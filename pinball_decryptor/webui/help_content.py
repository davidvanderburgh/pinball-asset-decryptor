"""The green ? "Tips for this tab" window's text.

Every working-view tab carries a pile of behaviour that used to live only in
inline grey prose or hover tooltips.  This collects those tips per tab so a
user can pull up "everything worth knowing about this page" on demand
(``tabs/shell_extras.py`` ``tips``; the window is ``static/js``).

Content is deliberately static + manufacturer-agnostic (plugin-specific
behaviours say "where available"); if per-manufacturer help is ever needed,
grow ``HELP_CONTENT`` into a hook on ``Manufacturer`` like ``write_intro``.

A body is words in a light markdown, or a list of words and picture blocks
(``webui/tips_render.py`` says what each draws, PAD-386): bullets, steps and
a callout read faster than a paragraph, so new tips use them.
"""

import os

# (title, body) sections per notebook-tab name.  Keys match the tab captions
# exactly (the tab's key, as the ? window asks for it).
HELP_CONTENT = {
    "Select Card": [
        ("The whole job", [
            "A mod is four steps, one tab each.",
            {"flow": [
                {"icon": "sd", "title": "Pick", "text": "the card, here"},
                {"icon": "extract", "title": "Extract",
                 "text": "its files into a project folder"},
                {"icon": "edit", "title": "Replace", "text": "what you like"},
                {"icon": "write", "title": "Write",
                 "text": "a new card image, then flash it"}]},
        ]),
        ("Pick the card",
         "**Browse…** to a card image or update file, or drop the file from your "
         "desktop or a folder on the path or on **Browse…**. Or use **From SD card / "
         "SSD** (where available) to read a card in a reader; on Windows that needs "
         "Administrator.\n\n"
         "The app's **Browse…**, **Choose…** and **Add…** buttons take a dropped "
         "file or folder the same way, and so does a row on the Images, Video and Audio "
         "tabs."),
        ("Is it the right card?",
         "For a Stern Spike 2 card, the page shows what the machine shows as it starts: "
         "the game's loading screen, or a multi-boot card's menu with the default game "
         "lit (a few seconds the first time; a card in a reader shows the first game's "
         "screen).\n\n"
         "**Card details**, under it, lists firmware, edition, games, asset counts and "
         "partitions; on a Stern card, **Official release** says whether it is Stern's own "
         "release or a changed one. **Copy** is for bug reports. Nothing on the card is changed."),
        ("A card for another project",
         "Pick a card while the open project was extracted from a different one (a James "
         "Bond card over a Godzilla project) and **New project** comes up, filled in for "
         "the card you picked: **Create** makes it a project of its own and switches to it; "
         "**Stay in** keeps the open project. Until you switch, the panel on the right says "
         "the project is another card's and keeps the button.\n\n"
         "A card that already has a project of its own opens that project instead."),
        ("What works without an extract",
         "| Tab | Straight from the card |\n"
         "|---|---|\n"
         "| Partitions, Compare, Emulate, Multi-boot | Yes |\n"
         "| Write | Yes on Stern, JJP and CGC (flash an existing image). Others need "
         "an extract. |\n"
         "| Replace tabs, Mod Pack | No. They need an extract. |\n\n"
         "Tabs that need an extract show a lock in the list on the left. They still "
         "open, under a banner saying what is missing."),
    ],
    "Extract": [
        ("What Extract does",
         "Extract copies the ticked kinds (**Audio**, **Video**, **Images**, **Text**) "
         "off the card picked on Select card into the **Project Folder**: the one folder "
         "the Replace, Write and Mod Pack tabs all work out of.\n\n"
         "- **Change** goes back to Select card.\n"
         "- The ticks and auto-name options are remembered per manufacturer."),
        ("Which game is this card?",
         "In **From SD card** mode, the line under the dropdown names the game on the "
         "card (and how many games a boot menu holds), read in place with nothing "
         "copied: plug cards in one by one to sort a stack. Needs Administrator on "
         "Windows; the line says when it's missing."),
        ("Detection",
         "The recognized game and firmware version show in the title bar.\n\n"
         "- **Not recognized** usually means the wrong kind of file, or a copy still "
         "in progress.\n"
         "- A file from another manufacturer gets a one-click switch."),
        ("Save card as image",
         "In **From SD card** mode, **Save card as image…** copies the whole card, "
         "sector for sector, into one .raw file as big as the card. Nothing on the card "
         "is changed.\n\n"
         "- Back a stock card up before modding it.\n"
         "- Save a card before and after a change on the machine, then diff the two on "
         "the Compare tab."),
        ("Multi-boot cards",
         "On a card with a boot menu, Extract and Build work on the **first** game. A "
         "notice says so and lists the games; a Build copies the others and the menu "
         "through untouched. **Info** beside the path lists the games any time.\n\n"
         "### To change another game\n"
         "1. Extract and change that game's own image, and build it.\n"
         "2. On the Multi-boot tab, load the card, point that game's row at your build "
         "and update the card in place."),
        ("Projects",
         "The folder you extract into **is** your project: a hidden file in it keeps "
         "the manufacturer, stock image and options, so opening it again restores "
         "everything.\n\n"
         "The blue folder button in the header has **New**, **Open**, **Save as** (a "
         "full copy minus build output), **Recent**, **Properties** and **Projects** "
         "(sizes, notes, and **Archive** to free disk space)."),
        ("Naming the sounds", [
            {"cards": [
                {"icon": "wave", "tone": "info", "title": "Auto-name call-outs",
                 "text": "Speech to text on this PC. First run downloads a ~75 MB "
                         "model, then works offline."},
                {"icon": "audio", "tone": "info", "title": "Auto-name music",
                 "text": "Online AcoustID match. The number after a title (e.g. 0.97) "
                         "is how sure it is."},
                {"icon": "list", "tone": "info", "title": "Length-prefix names",
                 "text": "Where available: `01m22s235 - idx0001.wav`, so the same "
                         "sounds sort together across firmware versions."}]},
            "Results also go to callouts.csv and music_titles.csv. Better call-out "
            "names: pick a higher **Voice recognition quality** under these options "
            "(slower; bigger model).",
            "Extracted without them? **Auto-name now** names the sounds already in the "
            "project folder, no new extract. Sounds that already have a name keep it, so "
            "running it again names only what is left.",
        ]),
        ("Re-extracting", [
            {"note": "Extracting into a folder with files in it **overwrites your "
                     "edits** (after a confirmation). Use one project folder per "
                     "firmware version.", "kind": "warn"},
            "- Leave the hidden **.checksums.md5** alone: it is how the Replace tabs "
            "and Write tell what you changed.\n"
            "- Into an **archived** project, your edits are set aside and put back "
            "over the fresh extract.\n"
            "- After an extract, **Extract** stays gray until the card, folder or an "
            "option changes, so a second click can't redo it.",
        ]),
        ("\"The source image has changed\"",
         "The image you extracted from is no longer the same file, so the **Original** "
         "names on the Replace tabs may be wrong. Re-extract, or **Dismiss** to silence "
         "it for this image, even after a restart (the next change brings it back)."),
    ],
    "Replace Audio": [
        ("Scan and assign", [
            "Pick a new sound for any slot; the app fits it to the card when you build.",
            {"flow": [
                {"icon": "search", "title": "Scan",
                 "text": "lists every sound slot in the project folder Extract made"},
                {"icon": "audio", "title": "Assign",
                 "text": "a file of your own to each slot you want changed"},
                {"icon": "write", "title": "Build",
                 "text": "on the **Write** tab; there is no separate stage step"}]},
            "- Almost any audio file works: mp3, wav, ogg, flac, m4a and more.\n"
            "- Drop a sound file from your desktop or a folder on a row to make it "
            "that row's replacement.\n"
            "- Any sample rate or bit depth (16, 24 or 32-bit, float or integer). "
            "Length, rate and volume are fitted for you when you build.",
        ]),
        ("Loudness", [
            "Each replacement is matched to the loudness of the sound it replaces, "
            "so it sits with its neighbours.",
            "- The match measures the speech level, not the loudest peak, so one "
            "stray click in your recording can't leave the voice too quiet. It also "
            "brings a hot music clip down.\n"
            "- How loud you exported your file makes no difference. To make a sound "
            "louder or quieter than stock, use the boxes below, not your editor.",
            {"cards": [
                {"icon": "gear", "tone": "info", "title": "Whole build",
                 "text": "**Replacement loudness** in Advanced Audio Options: match "
                         "(default) or full scale (on SAM and Spike 1: keep each "
                         "replacement's own level), plus a ±12 dB offset. Moves "
                         "every replacement together."},
                {"icon": "wave", "tone": "ok", "title": "One clip",
                 "text": "**Loudness for this clip**, beside the Replacement preview. "
                         "Stacks on the build-wide offset; the Level column shows "
                         "which clips you leveled."}]},
            "- **Apply to all shown** puts the same offset on every row the list "
            "shows: set Type to Music first to move only the songs (Stern mixes its "
            "music quietly, under the callouts).\n"
            "- Boosts are soft-limited, never clipped. The build log says which "
            "setting built the card.",
        ]),
        ("Music modes",
         "Spike 2, the latest version of each game (not James Bond 007 Premium/LE, James Bond 60th or Star Wars Premium/LE, whose game programs cannot grow). One card can carry more "
         "than one set of sounds, and the machine's service menu picks the set: **Music "
         "Mode** under Adjustments > Machine Settings > Audio Content (on a game whose "
         "Adjustments have Standard Adjustments: at the end of that list).\n\n"
         "- Right-click a sound > **Music modes** > **Mode 2 (Custom A): choose a "
         "sound…** (modes 2 to 4 are offered; **Add a music mode…** adds more, up to "
         "8). Mode 1 is the sound as it plays now: its replacement, or the stock one.\n"
         "- In a mode a sound has no file for, it plays its mode 1 sound. One file can "
         "go in several modes; it takes the sound bank's room once.\n"
         "- **Name the music modes…** names them on the machine: the Music Mode "
         "setting's help line reads like \"1 = Standard, 2 = Orchestral\" (with many "
         "modes or long names it shortens them to fit). The machine offers modes up to "
         "the highest one any sound has a file for.\n"
         "- A mode's file follows **Allow replacements longer or shorter than the original** "
         "(Advanced…) like a replacement: on, it plays at its own full length; off, a "
         "file longer than the sound it stands in for is cut to that length. Either "
         "way it is matched to that sound's loudness.\n"
         "- Some songs play in parts: a short opening the Sound Test names (\"SE GZ MX "
         "TUNE 16\") and then a longer piece of music with no name of its own, often "
         "looped. A file for the opening part plays in place of the whole song, once "
         "or looped as the song was, and also where the game plays that song without "
         "its opening (\"SE GZ MX TUNE 16 NO INTRO\"); its length is the whole song's, "
         "and it matches the song's longest part's loudness.\n"
         "- Each music mode's file has a loudness of its own: **Music modes** > **Loudness of "
         "mode 2's sound…**, or play it there and use the box beside the Replacement "
         "preview, which then reads **Mode 2's loudness**. The loudness set "
         "on the sound itself is its own replacement's: it never reaches its mode "
         "files, and on a sound with no replacement the stock sound stays as it is.\n"
         "- Needs an image build, not a direct SD write. Every file takes room in the "
         "sound bank; past its 2 GB the files go into extra sound banks of their own "
         "beside it (image-sc01.bin and on), so they are not left out for it. A file "
         "for a sound the game plays together with other sounds (a song with an intro, "
         "or a medley) takes a copy of those sounds into its extra bank. A file for a "
         "sound the game does not play through its sound list stays in the main bank "
         "and is left out when that is full; the log names it."),
        ("Play in turn",
         "Stern Spike 2, the latest version of each game. A "
         "sound can play more than one file: each time the game plays it, the next one "
         "plays, and after the last it starts again.\n\n"
         "- Right-click a sound > **Play in turn** > **Add a sound to play in turn…** "
         "(up to 15 more). Sound 1 is the sound as it plays now: its replacement, or the "
         "stock one. The row shows how many it plays in turn.\n"
         "- **At random** in the same menu plays one of them at random each time "
         "instead, never the same one twice in a row: several songs for one "
         "multiball, like a jukebox. **One after another** goes back to taking turns.\n"
         "- **Play sound 2 (…)** previews one; **Take off sound 2 (…)** drops it.\n"
         "- Each file plays for as long as the sound it stands in for: a longer one is "
         "cut to that length, and it is matched to that sound's loudness.\n"
         "- **Loudness of sound 2 (…)…** gives one file a loudness of its own, from "
         "-12 to +12 dB (0 keeps it matched). While **Play sound 2** has it in the "
         "Replacement player, the loudness box there is that file's too. Sound 1's is "
         "the sound's own loudness box.\n"
         "- Which one plays first after the machine is switched on is not fixed; every "
         "play after that is the next in turn.\n"
         "- In a music mode a sound has a file of its own for, that file plays every time, "
         "unless that mode's file has sounds in turn of its own: on a sound with music mode "
         "files, the menu has a part for each mode (headed **Mode 2 (…)**), with "
         "its own One after another / At random and loudness. Its own sound's part plays in "
         "every mode the sound has no file for. A mode's sounds play as long as its file.\n"
         "- Needs an image build, not a direct SD write. Each file takes room in the "
         "sound bank, and in extra sound banks beside it once that is full, as a music "
         "mode's files do."),
        ("Jukebox",
         "The Beatles 1.29. **Jukebox**, beside **Find originals…**, gives the five song "
         "modes songs of your own: each time a song mode starts, the game plays one of them, "
         "drawn at random, with its own intro video. No setting and no choosing: every start "
         "throws the dice.\n\n"
         "- **Add songs…** picks one or more audio files (up to 128).\n"
         "- **…** on a song: **Choose an intro video…** gives it the video its song mode "
         "opens with, the song's name in it. A song without one opens with its song mode's "
         "own intro.\n"
         "- **How often**: a Common song comes up three times as often as a Rare one, a "
         "Normal one twice as often.\n"
         "- A song never comes back within five song modes, so none plays twice in a game.\n"
         "- Any song can come up in any of the five song modes. A song plays to its end, and "
         "again from the start if the mode lasts longer; the mode's end stops it.\n"
         "- The rest of a song mode's screens (its level clips, its Champion name) stay as "
         "they are: make them the same for every song on the Video and Text tabs.\n"
         "- An extract of a card built with a jukebox brings it back.\n"
         "- Needs an image build, not a direct SD write."),
        ("Replace from folder",
         "**Replace from folder…**, beside the project folder, picks a whole folder "
         "of your files at once: each file goes to the slot with its name.\n\n"
         "- Any file type, any capitals: a .wav pairs with a slot that is .ogg.\n"
         "- Subfolders are searched. If two slots share a name, put the file in a "
         "folder named like its slot's folder.\n"
         "- The log names what was left out: files that match no slot, match more "
         "than one, or share a name with another file in the folder.\n"
         "- What comes back are ordinary picks: the next build applies them and "
         "**Clear replacements…** drops them.\n\n"
         "> Keep your files in their own folder OUTSIDE the project folder. The "
         "project folder, or anything inside it, is refused."),
        ("Find originals",
         "**Find originals…**, beside **Replace from folder…**, finds the files "
         "your picks were made from in a folder of yours, by how they sound: the "
         "names, the level, the sample rate and the file type don't matter.\n\n"
         "- For picks that are copies off a card, like the ones **Transfer Mods to "
         "New Version** takes from an extract of a built card. Those were converted "
         "once already by the Write that built that card; with your own files "
         "picked instead, the next Write converts from them.\n"
         "- Every pick on the tab is looked for, and every slot a build changed on "
         "disk with no pick left. Files inside an extract are copies off a card and "
         "are never offered.\n"
         "- Where the folder has the same sound twice (a WAV master and an MP3 "
         "export), the better copy is used. A file longer than the copy was cut to "
         "length by Trim / pad when the card was built, and is cut the same way "
         "again.\n"
         "- Amber rows are worth a listen: ▶ plays the copy and the file found. "
         "Nothing changes until **Use these files**, and what comes back are "
         "ordinary picks."),
        ("Clearing and undo",
         "Your picks are saved in the project folder itself, so they survive "
         "closing the app and changing the card. They never vanish on their own.\n\n"
         "- **Right-click** a row (Shift-click or Ctrl-click to select several): "
         "**Remove replacement** drops a pick not built yet; **Revert to "
         "original** puts the card's own sound back in a slot already changed.\n"
         "- **Clear replacements…** (the ⋯ More menu at the top) drops every pick "
         "on this tab. Sort by the Replacement column to see your picks together.\n"
         "- A cleared slot that a build or Emulate Start already wrote gets the "
         "card's own file back too, so list, build and emulator agree. Your own "
         "files are never touched.\n"
         "- A slot changed some other way (a file copied over by hand) keeps what "
         "it has: **Revert all changes…** on the Write tab restores everything."),
        ("Change markers", [
            {"cards": [
                {"icon": "plus", "tone": "ok", "title": "Green",
                 "text": "Picked this session. The next build applies it."},
                {"icon": "check", "tone": "info", "title": "✓ changed on disk",
                 "text": "The file in your project folder differs from the extract "
                         "(an earlier build, or a file you copied over it). The next "
                         "build packs it."},
                {"icon": "warn", "tone": "warn", "title": "⚠ not on this card",
                 "text": "In your project folder but not on the card, so the build "
                         "can't place it."}]},
            "- \"Changed on disk\" is about the project folder only: your source card "
            "image is never touched.\n"
            "- So editing files by hand works: drop your versions over the originals "
            "in the project folder, press **Scan**, and they show as changed.\n"
            "- The counter shows every change the next build will pack, not just "
            "this session's.\n"
            "- \"Not on this card\" is usually a mod pack from an older extract whose "
            "names changed. Importing the pack again removes the strays; **Transfer "
            "Mods to New Version** on the Mod Pack tab carries them over by content.",
        ]),
        ("Listening",
         "Two players side by side: **Original (stock)** and **Replacement (your "
         "file)**. Starting one pauses the other; ■ on either silences both.\n\n"
         "- **Previous** and **Next**, either side of each Play, play the row above "
         "or below, following your sort, search and filters. Under Replacement "
         "they play a row's replacement where it has one, its original where not.\n"
         "- **Play sequentially** plays down the list on its own, following your "
         "sort, search and Type filter. It stops at the end, on ■, on a click on "
         "another row, or when you open a replacement picker. The playing row is "
         "selected, so F2 or a right-click works on it right there.\n"
         "- **Play replacements** (turns Play sequentially on too) plays your "
         "replacement wherever a row has one, so the list sounds like the built "
         "card. Anything still stock-sounding is a clip you haven't replaced."),
        ("Finding things",
         "Click a column header to sort (again to flip). **Search** filters by "
         "name, including transcribed callout words and matched song titles.\n\n"
         "| Filter | Shows |\n"
         "|---|---|\n"
         "| Type: Music | Songs and bank tracks. On a game that names no music, "
         "anything 20 seconds or longer |\n"
         "| Type: Sound FX | Sounds named by the game's Sound Test menu |\n"
         "| Type: Callouts | Speech (needs Auto-name call-outs to have run) |\n"
         "| Show: Changed | Slots you replaced or that differ from the extract |\n"
         "| Show: Unchanged | Only what you haven't touched yet |\n\n"
         "On Stern games the **Requests** column counts the game code's sound "
         "requests that play each sound (hover it for their numbers and Sound Test "
         "names); **None** marks a sound no request plays.\n\n"
         "**Export CSV** saves the whole table (every slot, not just the filtered "
         "view) for a spreadsheet."),
        ("Where is this on the card?",
         "Right-click a slot, then **Find in Partition Explorer**. Sounds on a Spike 2 "
         "card live inside a bank, so it opens that bank (image.bin, or "
         "image-scNN.bin for music) and says so."),
        ("Renaming a sound",
         "Right-click a slot, then **Properties…** to fix its name (say, a callout "
         "the transcriber misheard).\n\n"
         "- The name follows the sound itself, so a later extract of this or a "
         "newer game version names it again.\n"
         "- Blank puts the stock name back.\n"
         "- On Stern games with a Sound Test menu, the dialog suggests the menu's "
         "names (also saved in sound_test_names.csv). Play a number on the "
         "machine's Sound Test menu, then type that number to find its entry."),
        ("Blip-free callouts (always on)",
         "Every replaced sound plays your audio all the way through, with no "
         "scrap of the original inside it. There is nothing to switch on.\n\n"
         "- The machine needs a few bytes of each original sound at boot. The "
         "build keeps those bytes in the game program, so the card can carry "
         "only your audio.\n"
         "- It makes the game program slightly bigger, so it needs the card "
         "built as an image (the Linux filesystem driver, as full-size videos "
         "do). A Direct-SD write can't do that, so about 6 ms of the original "
         "plays twice inside each replacement there.\n"
         "- Write Complete says which one your card got.\n"
         "- To get rid of the scrap on a card built before, just build it "
         "again: every replaced sound is redone from your files."),
        ("Longer replacements (Advanced Audio Options)",
         "Lets a Spike 2 replacement be longer than the sound it replaces. "
         "Optional; confirmed on a real machine (no loop, correct cut-off).\n\n"
         "- Off, a longer clip is trimmed to the original's length.\n"
         "- On, your clip is added at the end of the sound bank and the game is "
         "pointed at it; every other sound is untouched. The preview shows the "
         "whole clip with a green line where the original ended.\n"
         "- On, a clip at least 0.1 s shorter than the original also gets its own "
         "length the same way, so the game stops playing it where your audio ends "
         "instead of holding it through silence: the next callout comes sooner, and "
         "a song loops or moves on sooner. Off, it is padded with silence to the "
         "original's length.\n"
         "- It needs the card built as an image (the Linux filesystem driver). "
         "A Direct-SD write trims as before.\n\n"
         "### How much fits\n"
         "1. **The 2 GB bank.** The game can open a sound bank only up to about "
         "2 GB, and each lengthened sound adds its whole length on top (on "
         "Godzilla 1.16, room for about 45 minutes of stereo). Past that, the "
         "lengthened sounds go into **extra sound banks** of their own beside it "
         "(image-sc01.bin and on, the way Stern's music titles keep their songs), "
         "so the 2 GB does not trim them, songs the game plays in parts (an intro, "
         "the song, an outro) included. A few sounds stay in the main bank and are "
         "trimmed there when it is full (for example one the game never plays through "
         "its sound list, or one that shares its sound ids with a music mode's file "
         "kept in the main bank); the log names them.\n"
         "2. **The games partition.** Lengthened sounds share it with full-size "
         "videos, and a stock 8 GB card may have only a few hundred MB free. When "
         "room runs short, longer sounds are trimmed to fit it; songs marked "
         "**Keep this song whole if the bank fills up** are kept whole first. The "
         "log names each one and the SD card size that would keep them whole.\n\n"
         "> SD card size on the Write tab (Windows and Linux) builds for a bigger "
         "card and gives the games partition more room."),
        ("Save and load settings",
         "**More > Save settings to a file…** keeps this tab's picks, ticks and "
         "options in one small file. **Load settings from a file…** puts them back, "
         "on this card or another.\n\n"
         "- Slots the file doesn't set keep what they have; slots this card lacks "
         "are skipped.\n"
         "- The file only names your sound files, it doesn't hold them."),
    ],
    "Replace Video": [
        ("Scan and assign", [
            "Pick a clip of yours for any video slot; the build puts it on.",
            {"flow": [
                {"icon": "search", "title": "Scan", "text": "lists every video slot"},
                {"icon": "file", "title": "Pick", "text": "a clip of yours for a slot"},
                {"icon": "compare", "title": "Compare",
                 "text": "Original (stock) beside Replacement (your file)"},
                {"icon": "write", "title": "Build",
                 "text": "on the **Write** tab: picks apply then"}]},
            "- No stage step: the assets folder is the one Extract made and Write reads.\n"
            "- Drop a video file from your desktop or a folder on a row to make it "
            "that row's replacement.\n"
            "- The log says at once whether a pick \"already matches this slot\" (copied "
            "in, no re-encode) or \"will be re-encoded to match this slot\". "
            "Transparency is kept where the original has it.\n"
            "- Picks are stored in the project folder, not the card: they survive "
            "closing the app or pointing Extract at another card image.",
        ]),
        ("Replace from a folder", [
            "**Replace from folder…**, beside the project folder, picks each file in a "
            "folder of yours for the clip with its name: a whole set in one go.",
            "- Names pair whatever the file type or capitals (.mp4 for a .mov clip "
            "pairs); each is converted to suit its slot when you build. A clip set to "
            "go on as-is that comes back as another file type is set to convert.\n"
            "- Subfolders count. When two slots share a name, put the file under a "
            "folder named like its slot's.\n"
            "- The log names files left out: named like no slot, like several, or "
            "sharing a name with another file.\n"
            "- The rest are ordinary picks: in **Replacement**, applied by the next "
            "build, dropped by **Clear replacements…**.",
            {"note": "Keep your files OUTSIDE the project folder. It holds the card's own "
                     "files, so choosing it, or anything in it, is refused.", "kind": "warn"},
        ]),
        ("Right-click a slot",
         "| Pick | What it does |\n"
         "|---|---|\n"
         "| What this slot needs… | the exact format that goes on untouched, plus an "
         "ffmpeg command ([more](#what-the-machine-can-play)) |\n"
         "| This clip's length | how long this one clip plays ([more](#clip-length)) |\n"
         "| Show scene contents… | the Scenes tab, on the scene that plays it |\n"
         "| Random clips | more clips for this slot, one played at random each time "
         "([more](#random-clips)) |\n"
         "| Remove / revert | drops a pick, or puts back a file a build changed "
         "([more](#clearing-and-undoing)) |"),
        ("Clearing and undoing",
         "Right-click a slot, or a selection (Shift-click a range, Ctrl-click to add), "
         "to drop picks. **Clear replacements…** (More menu, the ⋯ button at the top) "
         "drops every pick on this tab.\n\n"
         "- **Undo** and **Redo** at the top (Ctrl+Z; Ctrl+Y or Ctrl+Shift+Z) take back, "
         "or make again, your last changes one at a time: a pick, a clear, Replace from "
         "folder, a clip's own conversion, length, colors or random clips, and the boxes "
         "over the list. They last until the app closes or another project opens.\n"
         "- Sort by **Replacement** to put every pick together.\n"
         "- A slot a build, or Start on the Emulate tab, already wrote gets the card's "
         "own file put back, so the list, the next build and the emulator agree. Your "
         "own files are never touched.\n"
         "- A slot changed some other way (copied over by hand, or built before the "
         "app kept a saved original) keeps what it has: **Revert all changes…** on the "
         "Write tab restores it."),
        ("Convert column", [
            "**Convert** says what the build will do with each pick (a row can read "
            "\"…\" while it works it out). Export CSV carries it too.",
            "| Convert | Means |\n"
            "|---|---|\n"
            "| As-is | already matches the slot: copied straight in |\n"
            "| Repackage | the slot's video in the wrong container: rewrapped, every "
            "frame kept |\n"
            "| Re-encode | the picture is converted: slow, and the only one that costs "
            "quality |\n"
            "| As-is ⚠ audio | adds a soundtrack the machine will play: strip it first |\n"
            "| ✗ needs .mov | the build would refuse the container |\n"
            "| ✗ wrong format | goes on, but plays sound over a black picture |",
            "### Use my files as-is\n"
            "One checkbox for EVERY pick; flip it any time and Convert re-answers, no "
            "re-picking.\n\n"
            "- **On:** files are copied in byte for byte and must be game-ready. The ✗ "
            "answers show only then.\n"
            "- **Off:** anything not a match is converted to suit the slot, still at "
            "full size.",
        ]),
        ("What the machine can play", [
            "A Spike 2 card takes a clip untouched only when it is a true drop-in for the "
            "one it replaces.",
            {"cards": [
                {"icon": "check", "tone": "ok", "title": "Plays",
                 "text": "Same container, **H.264**, 8-bit 4:2:0, the slot's size and "
                         "frame rate. Song videos: a key frame every few frames."},
                {"icon": "error", "tone": "err", "title": "Sound, black picture",
                 "text": "MKV, HEVC, ProRes, 10-bit or the wrong size. Spike 2 decodes "
                         "only H.264, in hardware."}]},
            "Anything else is converted first (at full size), and the build log says "
            "which clip and why. A song video with key frames far apart stutters and "
            "slows the whole game, so it is converted too.",
            "### Encoding your own clips\n"
            "Right-click > **What this slot needs…** lists what goes on untouched "
            "(container, codec, H.264 profile and level, size, frame rate, key-frame "
            "spacing, audio track or not), read off the slot's own clip, plus an ffmpeg "
            "command with only the flags that must match: add your own bitrate and "
            "preset.",
            "### Sound in a video\n"
            "Most game clips are silent and the game plays its own sound. A replacement "
            "with audio plays it on top. Converting matches the slot (silent stays "
            "silent); a file copied as-is shows **As-is ⚠ audio**. Slots with their own "
            "audio keep it.",
        ]),
        ("Wrong-format clips already on",
         "A ⚠ by **Format** means the clip in the slot RIGHT NOW can't be decoded "
         "(ProRes, HEVC, 10-bit), usually one put on as-is before the app checked. "
         "Select the row: a callout under the preview says so.\n\n"
         "- **Format** and **Audio** describe the clip in the slot now, so after a good "
         "pick they show the old one until the next build (the callout turns amber).\n"
         "- **Original (stock)** shows the factory clip whenever its backup exists, and "
         "Convert measures your file against it, so a clip cut to the machine's real "
         "spec still reads As-is."),
        ("Random clips",
         "Spike 2, the latest version of each game. Right-click > **Random clips** > "
         "**Add clips to play at random…** gives a slot more clips than its own: each "
         "time the game plays it, one is picked at random, never the same twice in a "
         "row, and the slot's own clip is one of them.\n\n"
         "- The row shows a shuffle badge with the count; the same menu takes a clip "
         "off.\n"
         "- Only clips the game plays by name (modes, battles, awards, bonuses). A clip "
         "a scene plays on its own says **Why not this clip?** instead.\n"
         "- Needs an image build, not a direct SD write."),
        ("Clip length",
         "Right-click > **This clip's length**: follow the **Trim / pad** box (default), "
         "match the stock clip, keep your file's full length, or type seconds.\n\n"
         "- A clip with its own length shows it after the **Length** cell.\n"
         "- Trim / pad always measures against the stock clip, even on a replaced "
         "slot.\n"
         "- Clips under a second (a sixth of one Batman card's 6331, down to one-frame "
         "stills) show milliseconds, like 0:00.033, not an empty-looking 0:00. The "
         "preview shows their first frame."),
        ("Compare report",
         "More > **Export compare report (CSV)…** saves a row for every replacement, "
         "every random clip and every mode's row of a shared clip, beside the game's "
         "own clip it plays in place of.\n\n"
         "- Both lengths in seconds to two decimals, the difference, and the length it "
         "will have on the card after Write (the stock length when Trim / pad applies, "
         "your own when the clip goes on as-is).\n"
         "- Resolution, frame rate, frames, codec, audio and file size of each, and a "
         "note when Write cuts, pads, scales or changes the frame rate."),
        ("Size limits", [
            "How big a replacement may be depends on the game.",
            {"cards": [
                {"icon": "disk", "tone": "info", "title": "Most games",
                 "text": "**Same size or smaller** fits. Bigger is re-encoded down to the "
                         "slot's byte budget. A clip in the slot's format goes in with no "
                         "quality loss."},
                {"icon": "check", "tone": "ok", "title": "Barrels of Fun",
                 "text": "**No byte budget.** The update's offsets are rewritten around "
                         "the clip."},
                {"icon": "sd", "tone": "warn", "title": "Stern Spike 2",
                 "text": "**No byte budget per slot.** An image build puts clips on at "
                         "full size; the card's free room is the limit."}]},
            "### Stern Spike 2: room on the card\n"
            "- Full-size clips and lengthened sounds share the free room on the card's "
            "games partition. A stock 8 GB card may have only a few hundred MB.\n"
            "- **SD card size on the Write tab (Windows and Linux)** builds for a bigger "
            "SD card with more room.\n"
            "- A build that won't fit is stopped before anything is written to the card "
            "image, and says how much room it needs.\n"
            "- A clip is squeezed to its slot's byte size only on a direct SD write, when "
            "this computer can't write whole files to the card (Windows needs WSL2), or "
            "when its picked file was moved or deleted.",
        ]),
        ("Best quality from your own files", [
            "Stern Spike 2. A pick that isn't an exact match is converted, by default at "
            "the bitrate of the clip it replaces.",
            {"cards": [
                {"icon": "film", "tone": "info", "title": "Default",
                 "text": "**Stock bitrate.** Fits where the old clip was."},
                {"icon": "star", "tone": "ok", "title": "Best quality",
                 "text": "Tick **Best quality** (or toolbar **Best quality…**): each clip "
                         "gets the bits its picture needs."}]},
            "- Too big? Build for a 16 GB or 32 GB SD card on the Write tab; a build that "
            "won't fit says so before copying.\n"
            "- Converted clips are kept, so a rebuild converts only what changed.",
            "### Finding your original files\n"
            "Card built on another PC, or from oddly named files? **Best quality…** finds "
            "them by how they look, not by name or file type.",
            {"flow": [
                {"icon": "folder", "title": "Pick",
                 "text": "your built card, its stock card, your videos folder"},
                {"icon": "search", "title": "Find", "text": "minutes the first time"},
                {"icon": "check", "title": "Use",
                 "text": "untick any, then **Use these files at best quality**"}]},
            "- Color is told from black-and-white, and of several copies the best wins.\n"
            "- Check amber rows. \"already on the card untouched\" means a rebuild from "
            "that file won't improve the clip.",
        ]),
        ("Checking a card you already built", [
            "**Check card…** (More menu, ⋯ at the top) lists the clips on a built card "
            "image whose bitrate is low enough to look blocky. Seconds, image only, no "
            "extract.",
            {"cards": [
                {"icon": "down", "tone": "warn", "title": "Squeezed to fit",
                 "text": "Shrunk into its slot. Build an **image file** (not a direct-SD "
                         "write) with WSL working and it goes on whole."},
                {"icon": "film", "tone": "info", "title": "Just low in bitrate",
                 "text": "Your own export (only a better export helps) or an older app's "
                         "converted copy (a rebuild helps): the card can't tell."}]},
            "- Building again from your original replacement files converts at the "
            "bitrate of the clip it replaces.\n"
            "- Whole clips need room on the games partition. For many squeezed clips or "
            "a big rebuild, use **SD card size on the Write tab (Windows and Linux)**.\n"
            "- A few stock clips (long attract loops) sit under the bar by design.",
        ]),
        ("Colors (Spike 2)", [
            "### The Color column\n"
            "Each replaced clip shows a palette: click it to attach or detach the color "
            "profile. Select several clips and pick a profile in the **Colors** bar to give "
            "it to all of them.",
            {"cards": [
                {"icon": "palette", "tone": "ok", "title": "Green",
                 "text": "Color profile attached: the individual files profile is baked "
                         "in at build (re-encoded)."},
                {"icon": "palette", "tone": "err", "title": "Red",
                 "text": "No color profile attached: goes on as it is."},
                {"icon": "lock", "tone": "info", "title": "Blue lock",
                 "text": "The game's own clip, never changed. **Advanced** on the toolbar "
                         "gives it a palette; detaching puts the original back."}]},
            "Under each player, **Original** (or **Replacement**) and **With its color "
            "profile** switch that player between the clip as it is and the clip through "
            "its color profile, attached or not, as a Compare player does. Only the "
            "player changes; the palette is what attaches it.",
            "The player of the file a profile is attached to opens on **With its color "
            "profile**, and turns to it when you change that profile in the **Colors** "
            "bar: the Replacement player for a replaced clip, the Original player for a "
            "game's own clip (its Replacement player stays empty).",
            "Select several rows (Ctrl-click, Shift-click) with the **Colors** bar open "
            "and a profile you pick goes to every one of them that is not locked, each "
            "attached.",
            "To keep a copy on your PC, right-click a row (or several) and pick **Save "
            "this clip with its color profile…**: the clips are saved to a folder you choose with "
            "their color profile baked in.",
            "### Preview colors\n"
            "Switches above the players show the clips as the machine will (preview "
            "only; no re-encode), drawn the same way Scenes draws a picture, color ranges "
            "and curves included, while they play. All off is your PC's own colors; "
            "click a name to open it on the Color profile tab.",
            {"flow": [
                {"icon": "image", "title": "Whole screen", "text": "the overlay"},
                {"icon": "palette", "title": "Individual files",
                 "text": "picks with a color profile attached"},
                {"icon": "eye", "title": "Machine screen",
                 "text": "every clip, unless the gear menu lets unattached files skip it"}]},
        ]),
        ("Compare clips", [
            "Select up to four rows (Ctrl-click, Shift-click) and press **Compare**: "
            "they play side by side, big, beside the **Colors** bar. One clip shows its "
            "Original beside its Replacement.",
            "- Click a clip: the Colors bar changes that clip's profile, and you see it "
            "against the others as you move a slider or pick a profile (Spike 2).\n"
            "- The clip you clicked is the one you hear; the others are muted.\n"
            "- **Play all**, **From the start** (every clip from its first frame, in "
            "step) and **Loop**. Each clip can switch between Original and Replacement.\n"
            "- A game's own clip is marked on its player: **Locked**, or with **Advanced** "
            "ticked at the top of Compare, **Game's own clip** and a palette under it. "
            "Attach its color profile there and the player turns to **With its color "
            "profile**.\n"
            "- **Close** or Esc goes back to the list.",
        ]),
        ("Which mode plays a clip (Spike 2)", [
            "The **Played in** column names the battles, multiballs and other modes of the "
            "game that play each clip, read from the card's game program (Stern titles "
            "whose modes the app can tell apart, such as Godzilla). The list beside "
            "**All / Changed / Unchanged** shows one mode's clips only.",
            "Some modes share a clip: on Godzilla, the battle vs Gigan and the Ghidorah and "
            "Gigan tag team play two of the same clips. Such a clip has a **row for each "
            "mode**: the second row (marked ↳) says **Same clip as** the first until you "
            "choose a replacement in it.",
            {"flow": [
                {"icon": "film", "title": "Find",
                 "text": "the mode's own row of the clip (↳)"},
                {"icon": "check", "title": "Choose",
                 "text": "a replacement in that row"},
                {"icon": "copy", "title": "Build",
                 "text": "only that mode plays it"}]},
            "- That mode's clip goes on the card as a new clip, so it needs an **image file** "
            "build (a direct-SD write leaves it out); the other mode keeps the clip it had.\n"
            "- Clear the replacement and the row is the **Same clip as** the first again.\n"
            "- **Not played**: nothing in the game asks for the clip, so the machine never "
            "shows it; a replacement there changes nothing.",
            "**Sounds with a clip** (Spike 2): under the panes, the sounds the game plays "
            "with the clip, read from its program: kept with the clip, asked for right after "
            "it, or named after it. Each is named by its file in the project's audio folder; "
            "its play button plays it there, and its name shows it on the **Audio** tab. A "
            "clip with none of those lists the sounds that may be its (named like it, or "
            "asked for in the same part of the program). A sound the game picks at random, "
            "or a clip's own audio track, is not listed.",
            "**When it plays** (Spike 2): what the emulator saw the game do with each clip. "
            "Play a game on the **Emulate** tab and the playfield window's **CLIPS** list "
            "names each clip as it plays, with the switch made just before it (**after "
            "RIGHT RAMP**) and **loops** when the game starts it again each time it ends. "
            "The Video tab keeps what was seen for the project, so a battle's clips can be "
            "told apart by their shots. The words the game draws over a clip are on the "
            "game's screen while it plays.",
            "The same column also says what the card's game program shows about a clip, with "
            "no emulator run: **In turn with 2 others** (the game plays a set of clips one "
            "after the other, each time the moment comes), **1 of 6** (one of a set it picks "
            "from as it plays) and **loops** (it asks for the clip as a loop). Which shot "
            "starts a clip is only known from the emulator.",
        ]),
        ("Save and load settings",
         "**More > Save settings to a file…** keeps this tab's picks, ticks and options; "
         "**Load settings from a file…** puts them back, on this card or another. Slots "
         "the file doesn't set keep theirs, slots this card lacks are skipped. The file "
         "names your files, it doesn't hold them."),
        ("Scene editor", [
            "The **Scenes** tab draws a scene as the machine does, at one moment, and you "
            "edit it in place. Needs the scene's tree (Extract or **Re-read from card…**). "
            "Edits keep themselves; nothing to save.",
            "### Select and move\n"
            "- Click it in the preview or under **Layers**. Ctrl-click (Cmd on a Mac) "
            "adds or removes; Shift-click in Layers takes a range.\n"
            "- After a click in **Layers** or **Contents**, Up and Down pick the row "
            "above or below (Shift+Up/Down in Layers takes a range).\n"
            "- Drag to move, drag a corner to resize, arrows to nudge (Shift: 10 px).\n"
            "- A resize keeps the layer's X and Y (its top-left stays put); **Resize from** "
            "under **Keep its shape** switches it to **Middle** to grow and shrink from the center.\n"
            "- Drag a row in **Layers** above or below another to re-order it; drop an "
            "added layer on a group's row to move it into that group. The game's own "
            "layers stay in their group.\n"
            "- **Ctrl+Z** undo, **Ctrl+Y** or **Ctrl+Shift+Z** redo.",
            "### The panel\n"
            "- Position, size (**W px / H px**), **Turn °** (clockwise; 90° buttons; your own turn, on top of any turn the game gives it, which the panel names under it), "
            "tint and opacity, hide, and layer order (later draws on top).\n"
            "- A picture shows its size and scale; **Draw 1:1** draws it pixel for pixel.\n"
            "- Text: a corner or **W px / H px** resizes its box and the words wrap inside "
            "it; **Size %** scales the words.\n"
            "- Text: **Font controls** opens the **Font** bar on the right edge: "
            "the line's font and **Size** (the sizes the scene was made at draw sharpest), "
            "**Italic**, **Slant** and letter **Width**, letter and line **Spacing**, "
            "**Across** (Left / Center / Right) and **Up/down** "
            "(Top / Middle / Bottom) in its box, wrapping, shrink to fit and line breaks, "
            "**Fit box to text**, and **Add** / **Remove** a drop shadow, in "
            "the preview and in the game. **Font as shipped** puts the font and style back. "
            "Its **Color** gives the line a color of its own: a wheel, **Brightness**, an "
            "exact color, and **Save a copy...** / **Load...** with your **Saved** colors. "
            "The line is drawn in exactly that color and the color profile no longer "
            "changes it; **Default** puts the game's color (and the profile) back. "
            "A score panel line the game paints as it plays shows the game's colors there "
            "instead. "
            "Lines the "
            "game fills in itself on Godzilla's mode screens (a battle's title and "
            "instructions) always sit in the middle of their box and shrink to fit it; the "
            "preview shows them that way.\n"
            "- Text: most text is a font "
            "with baked-in colors, so **Tint** recolours it.\n"
            "- Text the **game fills in** as it plays (a jackpot or award title, a "
            "battle's name) has a gear on its Layers row and a teal dotted outline when "
            "you hover or pick it; the "
            "words on the card are a stand-in for the game's own line. Hover the gear to "
            "see which line (or which mode) fills it; its **T** finds that line on the "
            "Text tab, where the words are changed. The box's size, place and font set "
            "here hold for whatever the game puts in it.\n"
            "- A line the **game paints** in its own colors (the score panel) has a violet "
            "brush on its Layers row and a violet dash-dot outline when you hover or pick "
            "it. The Selected panel's **Filled in by the game** and **Painted by the game** "
            "bars light up for the line you pick and say \"Not this one\" otherwise; "
            "controls that don't apply to it are grayed. Until the project's card has been "
            "read for the boxes the game program names, the Filled-in marks are guesses and "
            "the bar says so: **Re-read from card** there reads them.\n"
            "- A project extracted from a card a Write had already changed says **From a "
            "written card** (or **From a modified card**) beside Revert: As shipped and "
            "Reset go back to that card, so pictures and text that Write added stay. Layers "
            "it hid can be put back with their red stop sign.\n"
            "- **Picture…** and **Text…** add new items.",
            "### Moment and switchable parts\n"
            "- **Moment** picks the point in the timeline; Play runs it, Stop goes back.\n"
            "- **Switchable parts** previews each look the game's code picks between "
            "(which monster Battle Select shows). Preview only.\n"
            "- A layer drawn in only some of a part's looks names them on its Layers row "
            "(the Planet X map's icons: Loop, Select, Destroyed, each in the same place). "
            "Select it and **Show this look** switches the part to that look.\n"
            "- A grayed layer isn't drawn at this moment: click it to show and edit it. "
            "Edits hold at every moment.",
            "### Eyes and hiding",
            {"cards": [
                {"icon": "eye", "tone": "info", "title": "The eye",
                 "text": "Hides a layer **in the preview only**. **H** toggles the "
                         "selection; **Alt+click** an eye solos it."},
                {"icon": "x", "tone": "warn", "title": "Hide in the game",
                 "text": "The mark at a row's end: a green tick is in the game, a red "
                         "stop sign hidden (click to swap; with several rows selected, "
                         "all of them). Write leaves a hidden one off the card; the row "
                         "is struck through."},
                {"icon": "trash", "tone": "err", "title": "Delete",
                 "text": "**Delete** (or right-click) asks first. A layer you added is "
                         "taken out; the game's own are hidden in both. **Undo** brings "
                         "it back."}]},
            "- A new scene opens with eyes shut on layers hidden in the game; **Revert** "
            "puts eyes back.\n"
            "- Selecting shows a layer even with its eye shut; it never changes an eye.\n"
            "- A crossed-out eye: off because its switchable part shows another look. The "
            "eye turns it on in the preview.\n"
            "- The game's own parts are hidden, never deleted: its code finds them by "
            "name.\n"
            "- A row's picture button opens it on **Images**; a text row's **T** opens "
            "**Text**.",
            "### Onto the card\n"
            "- Edits are listed on **Write**. Moves, resizes, tints, hides and order can "
            "go straight to an SD card; an added picture or text needs an image build.\n"
            "- **Revert** puts a scene, or every scene, back to the last Write or as "
            "shipped: its layout, not its color profiles or replaced pictures (**Reset…** in the "
            "project menu puts those back). **Export picture…** only makes a picture for you.\n"
            "- On a running Emulate (**Apply my replaced assets on top**), edits reach the "
            "game live: most screens at their next showing, ones loaded at start (score "
            "display, Battle Select) after a restart. Untick **Include my Scenes tab "
            "edits** to run without them.",
            "### Good to know\n"
            "- An older project reads its scenes off the card the first time (about ten "
            "seconds, once).\n"
            "- Drag the dividers to resize panes; double-click resets one.\n"
            "- Zoom: Ctrl (or Shift, or Cmd) + wheel, or the zoom buttons; middle-drag "
            "to pan.\n"
            "- Rows of W's or AAA are placeholders the game fills in, like high score "
            "initials.\n"
            "- Godzilla's score panel: select a score line for four color swatches, picked "
            "as the machine shows them (**Revert** puts the game's back). The game program "
            "paints them, so Write adds a program step.",
        ]),
        ("Save and load scene edits", [
            "**Save / load edits**, at the head of the Scenes page, saves edits and the "
            "pictures they add to one .zip.",
            {"cards": [
                {"icon": "scenes", "tone": "info", "title": "One or all edited scenes",
                 "text": "Their edits and pictures. One scene also carries its Text-tab "
                         "words."},
                {"icon": "save", "tone": "ok", "title": "The whole look",
                 "text": "**Every scene with pictures, text and color profiles:** scenes, "
                         "every replaced picture, Text edits, profiles (the game's own "
                         "pictures and lines too) and overlay. Not sounds, videos or the "
                         "machine screen."}]},
            "### Loading\n"
            "- Scenes match by path, so an LE file loads on the Pro. Missing scenes and "
            "unplaceable or too-long text are left out and named; clashing picture names "
            "are renamed.\n"
            "- Every load writes a report to the project's **logs** folder: each scene "
            "loaded, kept as yours, not on this card, or starting out otherwise here "
            "(moved, resized, hidden or colored differently), and anything left out.\n"
            "- Pictures go into **Shared pictures**. Nothing is deleted or overwritten.\n"
            "- A file with the game's own pictures or lines colored unlocks them here, so "
            "they show.\n"
            "- When the file would change something you edited yourself (a scene, a "
            "picture, a line of text, the overlay, color profiles), it lists each one "
            "beside the file's "
            "and asks: **Cancel**, **Skip conflicts** (load only the rest), **Replace "
            "all**, tick the ones to replace and **Replace ticked only**, or **Revert my "
            "scenes, then load** (every scene back as the game shipped it, then the whole "
            "file). Before any of "
            "yours is replaced it saves them to a file in the project's **Backups** "
            "folder (untick that to skip it); load that file to put them back.",
        ]),
    ],
    "Replace Images": [
        ("How it works", [
            "Pick a picture of your own for any slot, and the next build on the "
            "**Write** tab puts it on the card.",
            {"flow": [
                {"icon": "search", "title": "Scan",
                 "text": "lists the game's pictures in the folder Extract made"},
                {"icon": "image", "title": "Pick",
                 "text": "a replacement per row: almost any image format"},
                {"icon": "fit", "title": "Auto-fit",
                 "text": "scaled to the original's size and format, transparency kept"},
                {"icon": "write", "title": "Build",
                 "text": "on the Write tab: there is no separate stage step"}]},
            "- The folder is the one **Extract** made, the same one Write reads.\n"
            "- Drop an image file from your desktop or a folder on a row to make it "
            "that row's replacement.\n"
            "- Keep the original's resolution for the best result.",
        ]),
        ("Where pictures come from",
         "The **Source** column says where a picture lives. They all replace the "
         "same way.\n\n"
         "| Source | What it is |\n"
         "|---|---|\n"
         "| File | a plain picture file on the card: menus, apron and test art |\n"
         "| Scene texture | art from the game's display scenes; many are animation "
         "frames or sprite sheets |\n"
         "| Radium | pictures inside the scene descriptions: song-title banners "
         "and the like |\n"
         "| Glyph | one letter cut out of a font (see [Fonts](#fonts)) |\n"
         "| Boot screen | the picture shown while the machine starts (SternLogo.png); "
         "an older extract needs Extract again |\n\n"
         "The **Source** dropdown narrows the list to one kind; click the Source "
         "header to sort by it."),
        ("Size limits", [
            "A replacement must fit in the original slot's bytes, so the card's "
            "layout never changes.",
            {"cards": [
                {"icon": "check", "tone": "ok", "title": "Fits",
                 "text": "Drops straight in."},
                {"icon": "minus", "tone": "warn", "title": "Too big",
                 "text": "Re-compressed with fewer colors until it fits."},
                {"icon": "x", "tone": "err", "title": "Still too big",
                 "text": "Skipped: the slot is left unchanged. Use a simpler picture."}]},
            "Font and sprite atlases in scenes are the exception: they are re-encoded "
            "losslessly at the slot's exact size, with no byte limit.",
        ]),
        ("A bigger picture (Spike 2)",
         "On Stern Spike 2 a picture inside a game scene (Source **Radium**, not a "
         "font) can keep its own size, e.g. a longer name banner.\n\n"
         "- Tick **Keep this picture's own size** under the preview, or its box in "
         "the **Keep size** column.\n"
         "- The build grows the scene to fit it. The game draws it from the same "
         "top-left corner, so a wider picture reaches further right.\n"
         "- Needs an image build, not a direct SD write.\n"
         "- A few pictures can't change size (full-screen backgrounds, for one): the "
         "build fits those to the original size and the log names each.\n"
         "- Tested in the PC emulator; no machine has run one yet."),
        ("Color column (Spike 2)", [
            "Every row has a Color mark saying whether a color profile goes into "
            "that picture when you build.",
            {"cards": [
                {"icon": "palette", "tone": "ok", "title": "Green palette",
                 "text": "Attached: the Color profile tab's individual files profile "
                         "is baked in."},
                {"icon": "palette", "tone": "err", "title": "Red palette",
                 "text": "Not attached: it goes on the card as it is."},
                {"icon": "lock", "tone": "info", "title": "Blue lock",
                 "text": "The game's own picture: never changed."}]},
            "- The box under the preview does the same as the palette.\n"
            "- Select several pictures (Shift-click or Ctrl-click) and pick a profile in "
            "the **Colors** bar: all of them get it, attached.\n"
            "- **Preview colors** over the panes draws them as the machine shows them, "
            "and each pane has **Original** / **With its color profile**. Only the "
            "preview changes.\n"
            "- **Compare** puts up to 4 selected pictures side by side beside the "
            "**Colors** bar. Click one: the bar changes its colors while you see the "
            "others.\n"
            "- Tick **Unlock extracted images** under Advanced to give the game's own "
            "pictures a palette too. Detaching one, or locking again, puts the "
            "original back.\n"
            "- To keep a copy on your PC, right-click a row (or several) and pick "
            "**Save this picture with its color profile…** (or **More**): the pictures are saved "
            "to a folder you choose with their color profile baked in.",
        ]),
        ("Replace from folder", [
            "**Replace from folder…**, beside the project folder, gives each file in "
            "a folder of your own to the slot with its name, all in one go.\n\n"
            "- Names pair whatever the file type or capitals (a .png pairs with the "
            "card's .jpg). Subfolders count: when two slots share a name, put the "
            "file in a folder named like its slot's.\n"
            "- Scene pictures and font letters carry a fingerprint of their card, so "
            "another card's copies can't pair by name: **Transfer Mods to New "
            "Version** on the Mod Pack tab carries them over by content.\n"
            "- They come back as ordinary picks in the Replacement column. The log "
            "names files left out: named like no slot, like several, or sharing a "
            "name with another file.",
            {"note": "Keep your files outside the project folder. It holds the card's "
                     "own files, so choosing it, or anything inside it, is refused."},
        ]),
        ("Find originals", [
            "**Find originals…**, beside **Replace from folder…**, finds the files "
            "your picks were made from in a folder of yours, by how they look: the "
            "names, the size and the file type don't matter.",
            "- For picks that are copies off a card, like the ones **Transfer Mods to "
            "New Version** takes from an extract of a built card. Those were squeezed "
            "into the card's format once already; with your own files picked instead, "
            "the next Write converts from them.\n"
            "- Every pick on the tab is looked for, and every slot a build changed on "
            "disk with no pick left. Files inside an extract are copies off a card and "
            "are never offered.\n"
            "- Where the folder has the same picture twice, the biggest best copy is "
            "used. A color picture is never taken for its black-and-white twin.\n"
            "- Each row shows the copy and the file found side by side. Glance down "
            "them: a look-alike (the next frame of an animation, the same letter "
            "from another font) can stand in when the real file isn't in the folder. "
            "Nothing changes until **Use these files**.",
        ]),
        ("Clearing and undo", [
            "Your picks are saved in the project folder itself, so they survive "
            "closing the app (even with another card picked on Extract) and never "
            "disappear on their own.\n\n"
            "- **Some:** select rows (Shift-click a range, Ctrl-click one more) and "
            "right-click. Sort by Replacement to bring your picks together.\n"
            "- **All:** **Clear replacements…** in the More menu (the ⋯ button at the top).\n"
            "- **One animation:** its scene group's right-click menu.\n"
            "- **One slot:** right-click it to drop a pick not built yet, or revert a "
            "file already changed.\n\n"
            "A slot a build (or Emulate's Start) already wrote gets the card's own "
            "file back too, so the list, the next build and the emulator agree. Your "
            "own files are never touched.",
            {"note": "A slot changed another way (a file copied over it by hand, or "
                     "a build from before the app kept an original) keeps what it has: "
                     "**Revert all changes…** on the Write tab restores those."},
        ]),
        ("Scene groups and search",
         "**Group by scene** nests each picture under its scene or animation, in "
         "play order.\n\n"
         "- Right-click a group to give every frame one replacement, blank the "
         "animation (transparent), clear its picks, or rename it (factory names "
         "like `unnamed_instance_14` say little; yours is kept and searchable).\n"
         "- **Search** matches a file name or any scene a picture is in (name, your "
         "rename, id or hash), so a hit may not have the words in its file name: "
         "Group by scene shows which scene matched."),
        ("Fonts", [
            "A font is a grid of letters (an atlas) the game draws text from. Three "
            "ways to change one:",
            {"cards": [
                {"icon": "image", "tone": "warn", "title": "The whole grid",
                 "text": "Restyle it, but keep every letter in place: the game cuts "
                         "fixed boxes, so a moved letter scrambles the text."},
                {"icon": "edit", "tone": "ok", "title": "One letter",
                 "text": "Source **Glyph**: one picture per letter (e.g. `U+0041 A`), "
                         "put back in its exact box."},
                {"icon": "text", "tone": "info", "title": "A desktop font",
                 "text": "**Fonts…** > **Import font file…** fits a TTF or OTF: every "
                         "letter fits its box, on the baseline, ink color matched."}]},
            "### The Fonts window\n"
            "- Type your own text to see it in the real letters and the game's "
            "spacing, pending edits included.\n"
            "- **Apply** writes the letters (build on Write as usual). **Revert font**, "
            "**Revert all fonts** and **Undo** (one write) go back.\n"
            "- A typeface is baked per size and per scene, so rows read \"copy 2 of "
            "3\". The tick by the buttons makes Apply, Blank font and Revert font "
            "reach every copy.\n"
            "- An outline font (black, behind the letters) is named above the "
            "buttons; **Remove it** blanks it only in this font's scenes.\n"
            "- **Outline**: your own border in pixels (0 for none). **Letter width**: "
            "narrower letters, for a gap between ones that touch.\n"
            "- **Blank font** erases a font's letters (how a shadow font goes). It "
            "asks first, and Revert font undoes it in one go.\n"
            "- **Behind** puts the preview on something other than black.\n"
            "- **Color** repaints the letters on Apply, no font file needed. The scene "
            "multiplies it (the line under the controls names the scene colors): a "
            "font a scene tints black stays black.\n"
            "- Fonts under 30px are marked \"tiny\": a desktop font rarely survives "
            "that small.",
        ]),
        ("Scenes tab",
         "The **Scenes** tab lists every scene with the pictures, fonts and text it "
         "is built from, and previews it as the machine draws it, with your "
         "changes. A picture's right-click **Show scene contents…** opens it there.\n\n"
         "- Double-click an item to jump to its row here, in Fonts or on Replace Text.\n"
         "- Click a heading to sort: image count finds big scenes, Video the ones "
         "with a clip.\n"
         "- **Screen** shows a mode's screens (intro, awards, victory) one at a time; "
         "◀ ▶ step through. **Speed** overrides a moving scene's own frame rate.\n"
         "- **Behind** sets a light backdrop or checkerboard, to see black borders.\n"
         "- **Re-read from card…** re-reads only the layouts off the Extract tab's "
         "card, leaving your pictures and fonts alone (a full re-extract overwrites "
         "them). When that card is not the one the project was extracted from, it "
         "offers the project's own card instead.\n"
         "- **Export picture…** saves a PNG; on a moving scene, **Export video…** "
         "saves an MP4 (needs ffmpeg). **Export all pictures…** / **Export all "
         "videos…** do every listed scene into a folder, in the background, never "
         "overwriting a name already there."),
        ("Text in a scene",
         "Right-click a line in the Scenes **Contents** list to change how that one "
         "scene draws it. The preview follows each change.\n\n"
         "| Item | What it does |\n"
         "|---|---|\n"
         "| Text color… | the line's real color (the font is white so the scene "
         "can tint it) |\n"
         "| Move… | shifts the line's box by the pixels you type |\n"
         "| Alignment | Left, Center or Right |\n"
         "| Font size… | a percentage of this scene's size; shrinking is lossless, "
         "past the master art it blurs |\n"
         "| Blank this font | in this scene, or everywhere (one atlas serves every "
         "scene: prefer this scene) |\n\n"
         "- An edit reaches every keyframe of the line, outline included.\n"
         "- A size change resizes every other line in the scene in that font; the "
         "log names them when you write.\n"
         "- **Back to the original layout** drops the edit. Nothing reaches the card "
         "until Write, which lists these with your other changes.\n"
         "- The words: pick the line in the preview and type them in **Words** under "
         "Selected, or change them on Replace Text. It is the same edit either way, and "
         "the preview draws it at once (\"shows: …\", \"(not built yet)\").\n"
         "- To proof-read every line, leave the search box empty and press its ▲ ▼ (or "
         "the ones beside Words): each line of text of every scene is picked in turn, "
         "where it sits. Typed words narrow it to the lines with them."),
        ("Save and load settings",
         "**More > Save settings to a file…** keeps this tab's picks, ticks and "
         "options in one small file. **Load settings from a file…** puts them back, "
         "on this card or another one.\n\n"
         "- Slots the file doesn't set keep what they have; slots this card doesn't "
         "have are skipped.\n"
         "- The file only names your pictures, it doesn't hold them."),
    ],
    "Replace Text": [
        ("Scan and edit", [
            "Change the words the game shows on its display.",
            {"flow": [
                {"icon": "search", "title": "Scan",
                 "text": "loads the editable lines from the project folder Extract made"},
                {"icon": "edit", "title": "Edit",
                 "text": "pick a row and type; the original stays beside it"},
                {"icon": "write", "title": "Write",
                 "text": "edits save at once and go onto the card at the next Write"}]},
        ]),
        ("Scene text vs game-program text", [
            {"cards": [
                {"icon": "scenes", "tone": "info", "title": "Scene text",
                 "text": "Lives in a scene file; the Scene column names it."},
                {"icon": "gear", "tone": "info", "title": "Game-program text",
                 "text": "Drawn by the game code itself: titles, battle names, award "
                         "lines. The Scene column reads **game program**."}]},
            {"note": "A scene's line is often a placeholder the code writes over. Where "
                     "the app can tell the game writes a line itself, that scene line is "
                     "locked (Apply to every scene and Replace everywhere skip it): "
                     "edit its game-program row instead. If a line still shows the old "
                     "words on the machine, do the same.", "kind": "tip"},
        ]),
        ("Length limits", [
            "The **Max** column is each line's budget in bytes (letters). A row reading "
            "**96 (grows)** can take up to 96.",
            "| Edit | What happens |\n"
            "|---|---|\n"
            "| Same length or shorter | Padded and patched in place |\n"
            "| Longer scene text | The scene file is rewritten at the new length. "
            "Its box doesn't grow, so check it in the Scenes preview |\n"
            "| Longer game-program text | Placed in a new area of the game program, "
            "with everything that used the old line pointed at it |\n"
            "| Over the budget | Refused, with the reason |",
            "- Longer lines need the card built as an image (the Linux filesystem "
            "driver, as full-size videos do). A Direct-SD write skips them, names why, "
            "and writes everything else.\n"
            "- A few game-program rows can't move; they keep their old budget and say "
            "so when an edit is refused. The build checks every line against the card.\n"
            "- A grown game program has booted on a real machine. A scene rewritten "
            "longer is proven in the PC emulator only.\n"
            "- To keep every line at its original budget, untick **Advanced: grow the "
            "game program / a scene for longer text** on the Write tab.",
            {"note": "Keep your stock card to hand when you write longer lines.",
             "kind": "warn"},
        ]),
        ("Replace everywhere",
         "**Replace everywhere…** (beside Search, and on the right-click menu) is "
         "find-and-replace over the whole list.\n\n"
         "- Every row whose ORIGINAL holds the words gets the change, so EBIRAH to "
         "BIOLLANTE reaches the battle title, its name row and the settings caption "
         "in one go.\n"
         "- Match case is on by default (the originals are upper-case).\n"
         "- It counts matching rows as you type. Rows that would go over budget are "
         "listed, not changed, so you can shorten them by hand.\n"
         "- Opened from an edited row, it fills in the word you changed."),
        ("Names inside a longer line",
         "Some names are only the tail end of a longer line: EBIRAH is the end of "
         "GODZILLA VS EBIRAH. That tail gets its own row.\n\n"
         "1. Edit BOTH rows.\n"
         "2. Make the long line END with the new name: GZ VS BIOLLANTE and "
         "BIOLLANTE.\n\n"
         "The app moves the pointer for you. If the two don't agree, the build log "
         "says so and leaves that line alone."),
        ("Which mode shows a line (Spike 2)",
         "The **Shown in** column names the battles, multiballs and other modes of "
         "the game that show each game-program line, read from the card's game "
         "program (Stern titles whose modes the app can tell apart, such as "
         "Godzilla).\n\n"
         "- A line several modes show has a **row for each mode** under it "
         "(marked ↳). Left blank, that mode shows the line's text; given its own, "
         "only that mode shows it.\n"
         "- Two lines that read the same are one row until then: on a card where the "
         "Gigan and Megalon battles' awards were both renamed to the same words, "
         "each battle gets its row back.\n"
         "- When other modes share the string, a mode's own text is a copy placed "
         "in a new area of the game program, so it needs the card built as an "
         "image, like longer lines."),
        ("Apply to all",
         "**Apply to every scene with the same original text** makes the same edit "
         "everywhere that exact line appears (many lines repeat once per scene)."),
        ("Seeing the line in its scene",
         "**Show in Scenes…** (also on the right-click menu) opens the Scenes tab on "
         "the scene that draws the line, with the line picked out: its font, color "
         "and the art behind it.\n\n"
         "- Your edits show there before anything is written (the Contents row says "
         "\"(not built yet)\"), so you can check a longer line fits its box.\n"
         "- A game-program line opens on the screen whose own text reads the same "
         "(a closing ! . or ? aside): the game puts its line in that box as it runs, "
         "so the box's words are a stand-in and the preview shows your edit there. "
         "When several screens hold it, the Scenes search lists them all.\n"
         "- A line no screen's text reads like, but whose **Shown in** names a battle or "
         "other mode, opens on that mode's screens (the Scenes search finds a screen by "
         "the name of the mode that shows it), on the box the game program names for "
         "that screen, else the one that fits the line best: an award line in the award "
         "box, whose own words may be the battle's name.\n"
         "- Other game-program lines have no screen to show."),
        ("Narrowing a big card down",
         "- **Search** finds words in a line or your new text. Typed as **in:** and a "
         "mode's name (in:gigan), it lists the game-program lines that mode shows, "
         "as the **Shown in** column names them.\n"
         "- **Show:** All, Changed or Unchanged. Unchanged is what you haven't done "
         "yet.\n"
         "- **Scene:** the game program or one scene file, each with its line count.\n"
         "- Both are remembered with the project, so you come back to the same view."),
        ("Naming a scene",
         "Spike 2 scene folders have meaningless hash names. Right-click a row, then "
         "**Name this scene…** to give it your own. It shows in the Name column, the "
         "Scene list, and on the Replace Images tab for that scene too."),
        ("Save and load edits",
         "**Save / load** saves every line you changed to a small file and loads it "
         "onto the same lines of this card or another. Text too long for that card "
         "is skipped."),
    ],
    "Color Profile": [
        ("What it does", [
            "A color profile corrects this project's colors: each channel's middle "
            "shades and level, the color strength and the shadow lift. **No change** "
            "leaves the colors alone. There are three profiles:",
            {"cards": [
                {"icon": "sun", "tone": "info", "title": "Whole screen overlay",
                 "text": "Spike 2: the game draws everything through it, its own art "
                         "too. Other machines: the replaced files are corrected when "
                         "staged."},
                {"icon": "image", "tone": "ok", "title": "Individual files",
                 "text": "Spike 2: baked into only the replaced files it is attached to."},
                {"icon": "eye", "tone": "warn", "title": "Machine screen",
                 "text": "Spike 2, preview only: what your machine's screen does. "
                         "Never on the card."}]},
        ]),
        ("Starting points and preview",
         "Pick a starting point, then fine-tune it.\n\n"
         "- **Recommended** is the usual start. **Black and white** suits the "
         "black-and-white playfield editions. Hover one to see how it was made.\n"
         "- Move the sliders and watch the curve graph and the preview. Drag across "
         "the preview to compare before and after (a test card, one of your Images "
         "replacements or another picture).\n"
         "- **See it in the emulator** runs this project's edits with the profile. "
         "Emulate's **Stock colors** tick leaves it out."),
        ("Part of the project",
         "- The profile is a change of this project: Write lists it as pending, "
         "and **Revert all** clears it.\n"
         "- **Save a copy** and **Load** move it between projects. Keep one per "
         "machine.\n"
         "- **Saved profiles** lists the saved copies by file name: pick one to use "
         "it. The one in use shows there, and its starting point is highlighted."),
        ("Individual files (Spike 2)",
         "The overlay reaches the game's own art too, which Stern already made for "
         "that screen. **Individual files** is a second profile, baked only into the "
         "files it is attached to. It starts from Recommended.\n\n"
         "- Attach it one file at a time in the Color column (Images, Video) or the "
         "palette in the Scenes layers, or to several selected at once.\n"
         "- **All images…** / **All videos…** under Which files gives it to every "
         "image or video that is not locked, attached. You are asked first; one "
         "Undo puts them all back.\n"
         "- The game's own pictures show a blue lock until Advanced unlocks them "
         "on the Images or Video tab.\n"
         "- Both can be on: the overlay draws over the baked files like everything "
         "else."),
        ("One profile per file",
         "Any picture, clip or picture added in Scenes can have a profile of its "
         "own.\n\n"
         "1. Click it (a row on Images or Video, a layer in Scenes) with the "
         "**Colors** bar open: **Files** shows the profile baked into it now.\n"
         "2. Pick a starting point or a saved profile, or move a slider: the file "
         "gets it as its own (and is attached if it was not).\n\n"
         "- **Same as the other files** drops it: the file then gets the individual "
         "files profile, the one this tab shows.\n"
         "- **Apply to all profiled images…** / **videos…** (Images and Video, "
         "and a picture in Scenes) gives every file there with a profile "
         "attached the shown file's "
         "profile. Files with none attached are left as they are.\n"
         "- **Apply to all images…** / **videos…** gives it to every file there "
         "that is not locked (each replaced one, and the game's own once "
         "unlocked), attached. For both you are asked first; one Undo puts them "
         "all back.\n"
         "- Hover a file or a Scenes layer to see its Color profile, or None."),
        ("Lines of text (Scenes)",
         "A line of text in the Scenes layers has a palette too, and its own "
         "profile like a file.\n\n"
         "- A line you add has its own palette. The game's lines show a blue lock "
         "until **Unlock extracted images and text** (Advanced, beside Preview "
         "colors) is ticked.\n"
         "- Most fonts have white letters the scene colors, so the profile goes into "
         "the color the line is drawn in.\n"
         "- A font whose letters have colors of their own (Godzilla's orange title "
         "font) keeps them in its font pictures, which every line in that font "
         "shares, in every scene. A line in it switched on gets its own copy of "
         "the font when you build, the profile in it, so only that line changes. "
         "The copy adds to the scene, so it needs an image build.\n"
         "- To correct every line in such a font at once, attach the profile to "
         "its pictures on the Images tab; its lines' palettes then show green "
         "with a link mark, and clicking one says where its color comes from. "
         "The Colors bar's pick still gives such a line a profile of its own.\n"
         "- **Apply to all profiled lines of text…** / **Apply to all lines of "
         "text…** (and **All text…** under Which files) give the shown profile to "
         "every line in every scene. Lines already corrected through their font "
         "are left out, and the question says how many. One Undo puts them all "
         "back.\n"
         "- A profile bends the colors a line already has, so it cannot make white "
         "letters red: white is already full red, and only turning green and blue "
         "down tints it. To pick a line's color outright, use **Color** in the "
         "Scenes **Font** bar. A line with a color of its own is drawn in exactly "
         "it and the profile leaves it alone; the Colors bar's **Font text color** "
         "row shows it (or **Default**). **Apply to all lines of text…** under "
         "it gives that color (or Default) to every unlocked line in every scene, "
         "as one Undo step."),
        ("Machine screen (Spike 2, preview only)",
         "Not a correction but your machine's screen itself. It is never written to "
         "the card, and Revert all leaves it alone.\n\n"
         "- Scenes and the Video tab's players draw through it when its switch "
         "under Preview colors is on.\n"
         "- Until you set one, it is the **Recommended** screen, tuned on a real "
         "Spike 2.\n"
         "- Extra controls: **Color ranges** (one band of hues: hue, width, soft "
         "edge, hue shift, saturation, brightness; grays protected) and **Curves** "
         "(RGB, Red, Green, Blue; drag or type the points).\n"
         "- Every control has a number box and a reset. Save a copy keeps them; "
         "loaded as an overlay or files profile, they are left out."),
        ("Preview colors (Scenes)", [
            "The row under the Scenes preview draws the scene as the machine will, "
            "with a switch for each step:",
            {"flow": [
                {"icon": "image", "title": "Individual files",
                 "text": "the files it is attached to"},
                {"icon": "sun", "title": "Whole screen overlay",
                 "text": "over everything"},
                {"icon": "eye", "title": "Machine screen",
                 "text": "the Recommended one until you set it"}]},
            "- Switch each on and off to see what it does. All off is your PC's "
            "own colors.\n"
            "- Pictures, videos and test cards go through the Machine screen. Lines "
            "of text don't: they keep their own color and get only the overlay.\n"
            "- The gear menu's **Files with no color profile attached skip the "
            "Machine screen** lets red-palette files skip it, to compare them with "
            "the game's art. They still get the overlay.\n"
            "- Click a name to open that profile. Only the preview changes, never "
            "the card.",
        ]),
        ("Color profiles bar (Scenes, Images, Video)",
         "The rainbow **Colors** tab on the right edge of Scenes, Images and Video "
         "slides out this tab's controls, so you tune with the page and each "
         "file's color switch in view.\n\n"
         "- One set of profiles everywhere: a saved profile picked on Images is the "
         "one Scenes and Video use too.\n"
         "- **Overlay**, **Files** and **Machine screen** pick the profile, a dot "
         "marking those in use. Images and Video open on Files the first time.\n"
         "- **Copy** and **Paste** carry one profile's numbers (ranges and curves "
         "too) to another. **Undo** and **Redo** (Ctrl+Z, Ctrl+Y) work per profile.\n"
         "- Scenes and the Video players redraw after each move while **Show it in "
         "this preview** is ticked. The Images preview doesn't draw through "
         "profiles, so it has no such switch.\n"
         "- On Scenes the scene list steps aside: the Scenes tab on the left edge "
         "brings it back.\n"
         "- Drag the bar's left edge to resize it (double-click puts it back). Each "
         "tab remembers whether its bar was open."),
    ],
    # The Modes tab's own tips are in PREVIEW_HELP, read through sections_for;
    # the mode maker is in every copy since PAD-763 (core/preview.RELEASED).
    # The key stays so every notebook tab has an entry.
    "Modes": [],
    "Attract": [
        ("What it's for",
         "Stern Spike 2. Put your own photos, clips and text cards between the screens the game shows in "
         "attract mode, each for as long as you like. The page lists the game's own attract screens in "
         "order (the last scores, PRESS START, the high scores and champions, the tutorial clips, the logos), "
         "read off the game's program, with yours between them.\n\n"
         "- **Add** on a game screen: photos (several at once make a slideshow), a clip or a text card, "
         "after or before it.\n"
         "- Drag an item, or use its arrows, to move it between the game's screens.\n"
         "- **seconds**: how long it stays up. A clip at 0 plays to its end.\n"
         "- A screen marked **at times** shows only now and then (after a game, or with one of the game's "
         "settings on); your items next to it show every time round.\n"
         "- Photos and clips are made into the game's clip format when the card is built, with your color "
         "profile, and carried in mod packs and Move Your Mods like your other files.\n"
         "- Your item gives way to the game: a flipper button moves on to the next screen and Start begins "
         "a game at once.\n"
         "- **Run in emulator** starts the emulator with this project's changes.\n"
         "- Needs an image build, not a direct SD write."),
        ("Insider Connected",
         "A card with attract items of your own keeps its scores off Insider Connected: they stay on the "
         "machine. The page and the Write log say so."),
        ("Which games",
         "Aerosmith, The Beatles, Foo Fighters, Godzilla, Guardians of the Galaxy, James Bond 007, Jaws, "
         "John Wick, Jurassic Park (Home Edition), King Kong, Led Zeppelin, The Mandalorian, Star Wars, "
         "Stranger Things (LE), Teenage Mutant Ninja Turtles and Uncanny X-Men. On the other Spike 2 games "
         "the page says why not yet."),
        ("Attract flipper sounds",
         "Stern Spike 2, every game and version. Most games play a sound or a callout when "
         "a flipper button is pressed in attract mode, with no game being played; James "
         "Bond 007 plays none. "
         "**Flipper sounds** on the **Attract** page gives the flipper "
         "buttons sounds of your own there.\n\n"
         "- **Add a sound…** (up to 16). Each press of either flipper button plays the "
         "next one, and after the last it starts again.\n"
         "- **Play sound 2 (…)** previews one; **Take off sound 2 (…)** drops it.\n"
         "- A press while one is still playing does not start another.\n"
         "- **Time between sounds** spaces them out: any time, or at most one every 10 "
         "seconds up to one every 5 minutes; a press before then plays nothing.\n"
         "- They do not play while the game takes the initials for a high score.\n"
         "- They ride one of the game's own sounds, so each plays for at most that "
         "sound's length (about 2 seconds on Star Wars, almost 15 on James Bond 007 LE, "
         "45 on Jaws); a longer file is cut to it, and the log says so.\n"
         "- The game's own sound at the press does not play over yours.\n"
         "- Not on TMNT 1.58 (Pro or LE) or Venom LE 1.06 yet; the menu says why.\n"
         "- Needs an image build, not a direct SD write."),
    ],
    "Write": [
        ("What a build does",
         "**Build** copies the untouched original and puts in every file that differs "
         "from the extract baseline, from every session, not just today's.\n\n"
         "- Sounds are re-encoded; videos, pictures and text are patched in, on most "
         "games at the same size, so the build drops in for the original.\n"
         "- On Stern Spike 2, videos and lengthened sounds go on at full size, in the "
         "free room on the games partition ([SD card size](#sd-card-size-stern-spike-2)).\n"
         "- **Modified Files** is only a preview; no need to wait for its scan."),
        ("Building again",
         "A rebuild onto this app's own untouched build **updates it in place**: only "
         "what changed since is written, and anything taken back gets its stock content "
         "back. Minutes, not hours, on a big mod.\n\n"
         "- Its record is the **.pad-build.json** beside it. Answer **No**, or delete "
         "it, to build from the original.\n"
         "- A different original, a file changed since, a failed copy or an app update "
         "starts over from the original; the log says why."),
        ("Building from a multi-boot card",
         "A multi-boot original gives a multi-boot build: the **first** game carries "
         "your changes, the other games and the menu are copied as they were. To "
         "change another game, build its own image and put it on from the Multi-boot "
         "tab (point its row at your build, update in place)."),
        ("SD card size (Stern Spike 2)",
         "Videos and grown sounds go onto the card's **games partition**, which has only "
         "the room Stern left: a few hundred MB on a stock 8 GB card.\n\n"
         "If your machine's SD card is bigger, pick its size under **SD card size**, "
         "below the Build Image line. The games partition grows to fill it; the rest of "
         "the card stays as it was.\n\n"
         "- The image is then that size: it needs an SD card at least that big, and "
         "flashes slower.\n"
         "- Only room: nothing fitted to its slot gets bigger. Lengthened sounds past "
         "the 2 GB the game can open in one sound bank go into extra banks of their "
         "own.\n"
         "- Only bigger sizes are offered, and one smaller: see below. Multi-boot cards "
         "are sized on the Multi-boot tab. Not on macOS yet. A direct write and Port + "
         "build keep each card's own size.\n\n"
         "### Smaller 16 GB card\n"
         "Stern's 16 GB image (James Bond 1.06, Jaws, Rush...) is 15.49 GB, and some "
         "SD cards sold as 16 GB hold a little less, so it won't fit them. **Smaller "
         "16 GB card** builds a 14.82 GB image instead: the games partition gives up "
         "671 MB of its free room, and nothing else on the card changes.\n\n"
         "- The build takes a couple of minutes more: the files at the end of the "
         "games partition are moved further in, then read back and checked.\n"
         "- Each build is made whole from the original, never updated in place.\n"
         "- The Build / flash dialog points at it when a 16 GB image won't fit the "
         "SD card you picked.\n\n"
         "### Make the image as small as it can be\n"
         "A finished image still carries all the free room on its games partition: "
         "gigabytes on a card built for a bigger SD card. Tick **Make the image as "
         "small as it can be**, under SD card size, and once everything is on the "
         "card its games partition is cut down to what it holds, with 268 MB left "
         "free, and the image file ends there. The note under it says about how big "
         "your original comes out; what the build adds comes on top.\n\n"
         "- The SD card size above is the room the build has while it runs; the image "
         "that comes out is never bigger than that size, and often much smaller.\n"
         "- The build takes a few minutes more: the files at the end of the games "
         "partition are moved further in, then read back and checked. Each build is "
         "made whole from the original.\n"
         "- A card with less than 134 MB to take off keeps its size.\n"
         "- The machine only writes to the games partition to install a code update, "
         "so a card made this small may not have the room for one.\n"
         "- Not on macOS yet, and not for a multi-boot card or a direct write.\n\n"
         "### Editions\n"
         "For one card that holds several editions of the same game, say a Standard "
         "and a 70th Anniversary look, picked in the game's own menu. Spike 2, the "
         "latest version of each game (not James Bond 007 Premium/LE, James Bond 60th or Star Wars Premium/LE, whose game programs cannot grow), image builds.\n\n"
         "1. Each edition is its own project from the same card. Press **Name the "
         "editions...** and give every project the same names in the same order: "
         "Standard, 70th Anniversary.\n"
         "2. Write each one. Its card gets **EDITION** in the operator menu "
         "(Adjustments > Machine Settings > Attract Mode, its help line naming the editions; "
         "on a game whose Adjustments have Standard Adjustments, the last row of that list).\n"
         "3. On the Multi-boot tab, add the images in that order, edition 1 first, "
         "and tick **No menu: boot the edition the game's EDITION setting names** "
         "in Menu settings.\n\n"
         "- The card shows no menu. A change to EDITION takes effect at the next "
         "power-up.\n"
         "- The editions share the machine's settings and high scores, so every "
         "edition has to carry the same settings: if one has music modes, give them "
         "all music modes.\n\n"
         "### When it won't fit\n"
         "Before anything is written to the card image, a build adds up what goes on "
         "the games partition.\n\n"
         "- Longer sounds are trimmed to the room left.\n"
         "- Videos that won't fit: the build is refused, with the numbers and the "
         "smallest SD card size that could take it. The file at the output is left as "
         "it was, and if a bigger size fits, the app offers to switch and rebuild.\n"
         "- A video that has to be converted is counted once it is, so that refusal "
         "can come after the conversions; the converted videos are kept in the "
         "project.\n"
         "- An update that no longer fits is built from the original instead.\n"
         "- A few small files are only estimated, so a build right at the limit can "
         "still stop at the copy at the end.\n"
         "- If the card or this computer can't grow, the note under SD card size says "
         "why, and a build is refused with that reason first.\n\n"
         "### The file name\n"
         "A name carrying its card size, as Stern's do (`…Release.8G.sdcard.raw`), is "
         "renamed for the new size, so both builds sit side by side. Any other name "
         "stays the same at every size, so the bigger build replaces the other: use "
         "**Change…** to keep both."),
        ("Output name",
         "The **Build Image** line shows the exact file the build makes: in the "
         "project's **build** folder, one per project, overwritten each time, named "
         "unlike the stock file (e.g. `…-modified.raw`).\n\n"
         "**Change…** picks another folder and name (say, a local drive for a NAS "
         "project). A missing folder is made, or you're told why it can't be before "
         "any work starts."),
        ("Modified Files and undo",
         "- Click a column header to sort; again to flip; a third time for the scan's "
         "order.\n"
         "- **Export CSV** saves the rows, to compare two projects in a spreadsheet.\n"
         "- **Revert all changes…** opens the project menu's **Reset…** with everything "
         "ticked: the whole project back as extracted (not on any card)."),
        ("Build / flash an SD card", [
            "On Stern Spike 2 and CGC, **Build / flash SD card…** does both; tick "
            "either part, or both. Other machines have a plain **Build**.",
            {"flow": [
                {"icon": "write", "title": "Build", "text": "a fresh card image"},
                {"icon": "sd", "title": "Flash",
                 "text": "it, or any saved image, onto an SD card"},
                {"icon": "play", "title": "Test", "text": "on the machine"}]},
            "- Flashing needs Administrator, and refuses an image too big for the card.\n"
            "- **Keep the SD card's settings, audits and high scores** (Stern Spike "
            "2) reads the card's data partition first and puts it back after the "
            "image, so the machine starts where it left off.\n"
            "- The dialog remembers your last ticks per manufacturer.",
            {"note": "Flashing **erases the whole card**.", "kind": "warn"},
        ]),
        ("Direct write", [
            {"note": "**Write to SD card / SSD** (where available) changes the card "
                     "itself. Take it out of the machine first, and always keep a "
                     "backup image.", "kind": "warn"},
        ]),
        ("USB install stick (JJP)", [
            "On Jersey Jack the button is **Build / make USB install stick…**: it "
            "formats the stick FAT32 and copies the ISO's files on, the only stick a "
            "JJP machine reads.",
            {"note": "balenaEtcher, dd or Rufus' DD mode sticks fail with 'Failed to "
                     "mount USB stick'.", "kind": "warn"},
            "1. Plug it into the backbox computer. (The front slot works, but can be "
            "thirty times slower: hours to install.)\n"
            "2. Leave the purple security key in, or it stops on \"Security key not "
            "found\".\n"
            "3. Power on; the installer runs by itself. (The Utilities USB-update menu "
            "is for small delta updates only.)",
        ]),
        ("Onto the game's SSD (JJP)", [
            "The stick dialog's **Onto:** row writes the install ISO straight onto the "
            "game's SSD in a dock on this PC, as the machine's installer would, and "
            "reads it back. No stick or key needed to write (the key is to play).",
            {"note": "This **erases the disk**, and needs Administrator.",
             "kind": "warn"},
            "On a disk already holding this install, **Write:** can swap just the boot "
            "menu or one image (same game version), keeping settings and scores. The "
            "disk is checked to be this install before a byte is written.",
        ]),
    ],
    "Mod Pack": [
        ("What it's for", [
            "A mod pack is a small zip of only your changed files, to share. It works "
            "with the Project Folder at the top.",
            {"cards": [
                {"icon": "upload", "tone": "info", "title": "Export",
                 "text": "your changes, into one pack"},
                {"icon": "download", "tone": "info", "title": "Import",
                 "text": "a pack, onto a matching extract"},
                {"icon": "copy", "tone": "ok", "title": "Transfer mods",
                 "text": "onto another version or model"},
                {"icon": "modpack", "tone": "ok", "title": "Port + build",
                 "text": "onto stock cards, built, in one click"}]},
        ]),
        ("Export", [
            "**Export** packs every change since you last extracted, from every session.",
            {"note": "Re-extracting makes the folder's files the new baseline: export "
                     "first, and keep each firmware version in its own folder.",
             "kind": "warn"},
        ]),
        ("Import",
         "**Import** writes only the files this extract has; the pack knows which game "
         "and version it came from.\n\n"
         "- Everything else is skipped and counted. **Details** lists each with why. "
         "For a pack from another card (LE onto Pro), use "
         "[Transfer mods](#transfer-mods).\n"
         "- Staged Defaults, high-score defaults and your image group and scene names "
         "come along, ready for the next Build.\n"
         "- Music modes come along too: the pack holds their files, and Import puts "
         "them in the project's **Music mode files** folder.\n"
         "- Files swapped on the Partitions tab (like SternLogo.png) can't be applied: "
         "Import puts them in the project's **card_files** folder for one right-click "
         "**Replace** there."),
        ("Port + build", [
            "**Port + build onto card image(s)…** does it all for one or more **stock** "
            "card images: a new firmware, the other model (Pro, Premium, LE), or several.",
            {"flow": [
                {"icon": "extract", "title": "Extract", "text": "each card"},
                {"icon": "copy", "title": "Transfer", "text": "your mods onto it"},
                {"icon": "write", "title": "Build", "text": "its modded image"}]},
            "Extracts are kept for next time. Audio slots that now hold a different "
            "sound are skipped; the log names everything skipped.",
        ]),
        ("Transfer mods",
         "**Transfer mods from another extract** (where available) carries your edits "
         "onto a newer firmware's extract, or the other model's.\n\n"
         "| Field | What it is |\n"
         "|---|---|\n"
         "| 1: your old extract | Where your mods come **from**. Always needed. |\n"
         "| 3: a clean twin | Optional: a stock extract of the same old version, so "
         "factory changes aren't taken for yours, and audio and text can move too. |\n\n"
         "- Audio is matched by content, so renumbered slots don't matter. A sound's "
         "music modes go where it goes.\n"
         "- The log shows the plan before you confirm, and why anything can't move; "
         "unmatched text is listed in full in **unmatched-text.txt**.\n"
         "- Running it again **replaces** the last run; your own re-pointing is kept.\n"
         "- From a card this app built, fill field 3 with that card's stock extract to "
         "carry both the baked-in mods and the folder's own."),
    ],
    "Partition Explorer": [
        ("What it's for", [
            "Browse a card image (.raw / .img) like a file manager: pull a file off "
            "an old modded card to reuse, or dump a folder to compare two cards.",
            {"note": "Browsing never changes the card. Only **Replace with…** writes "
                     "to it, and only after you confirm."},
        ]),
        ("Open and browse",
         "Pick the card in **Card Image** and press **Open**.\n\n"
         "- The app opens the first Linux (ext4) partition. Switch with the partition "
         "dropdown. FAT and extended partitions are listed but can't be browsed.\n"
         "- Expand folders in the tree. Each loads as you open it, so even a full card "
         "opens at once.\n"
         "- Pick a file to see it in **Preview**: text as text, images and fonts as a "
         "picture with their format and size. Anything too big or of another kind: "
         "extract it instead."),
        ("The Changed column",
         "**Changed** marks the files PAD replaced on THIS card image, with the date "
         "of the last swap. The mark stays after you close the app.\n\n"
         "- It only knows what PAD did. An edit made outside PAD leaves no mark.\n"
         "- If the image is swapped or rebuilt underneath, the marks are dropped.\n"
         "- **Show:** filters the tree to All, Changed (opened out) or Unchanged.\n"
         "- **Find** always searches the whole partition; it clears the filter first."),
        ("Properties and Extract",
         "- Right-click a file > **Properties…**: its full on-card path (as when the "
         "partition is mounted), partition, size and type, plus every swap PAD made "
         "to it on this image and the file each came from.\n"
         "- **Extract Selected** saves the picked file, or a folder and all inside it.\n"
         "- **Extract Whole Partition** dumps everything, handy for diffing two cards."),
        ("Replace a file on the card", [
            "Right-click a file > **Replace with…** to swap in your own: a boot or game "
            "script, a font, the Stern splash screen (sda2, "
            "/usr/local/spike/SternLogo.png; also on Replace Images as \"Boot screen\"). "
            "Your file does NOT have to be the same size.",
            {"cards": [
                {"icon": "check", "tone": "ok", "title": "Same size",
                 "text": "Written straight over the old file's blocks. Nothing to install."},
                {"icon": "disk", "tone": "info", "title": "Bigger or smaller",
                 "text": "The image is mounted through the Linux filesystem driver "
                         "(**WSL2** on Windows) to find or free space. Needs free "
                         "space on that partition; you are told the numbers if not."}]},
            "- The confirm box says which of the two it will be before anything is written.\n"
            "- The file keeps its name, place and permissions, and its Stern validation "
            "record (size too) is refreshed. Files the record doesn't list (the whole "
            "OS partition, for one) have nothing to refresh; the log says so.",
            {"note": "A replace writes into the image at once and there is no undo. "
                     "Work on a copy if the image is precious.", "kind": "warn"},
        ]),
    ],
    "Default Settings": [
        ("What it's for", [
            "Set the operator-adjustment DEFAULTS baked into a card (free play, volume, "
            "pricing, brightness and more), so a fresh card boots the way you want. "
            "The Card Image is the master image set on the Extract tab.",
            {"note": "**Fresh cards only.** A machine uses these on a fresh flash or "
                     "after a factory reset. A machine already set up keeps its own "
                     "settings: Stern keeps them in the card's data partition, "
                     "apart from the game program, and a card made from Stern's "
                     "download has none.",
             "kind": "warn"},
        ]),
        ("Edit and build", [
            {"flow": [
                {"icon": "edit", "title": "Set", "text": "a **New default** for any row"},
                {"icon": "check", "title": "Staged", "text": "by itself, ● marks it"},
                {"icon": "write", "title": "Build", "text": "the next card gets it baked in"}]},
            "- **On card** is the default in the image now (Stern's, unless changed here "
            "before). Rows are grouped: Game, Sound, Lighting, Insider Connected, High "
            "scores.\n"
            "- The log names each change and both values when you leave the field.\n"
            "- The master image is never changed, and the validation record is refreshed.\n"
            "- **Reset Fields** puts every row back to the image's own and clears the "
            "staged changes.\n"
            "- A Range that looks wrong may be the firmware's own: Led Zeppelin 1.22's "
            "two ELECTRIC MAGIC champions default to 2,000,000 under a stated minimum of "
            "5,000,000. The row counts as unchanged until you edit it, and an edit is "
            "pulled into the range (the game rejects anything else).\n"
            "- Click a row's **Range** to change its **Lowest** and **Highest** value; "
            "a changed range shows as 'a - b (card c - d)' and is built in beside the "
            "default. A default outside a narrowed range moves into it. Not offered for "
            "on/off settings, PAD's own choice lists or Master Volume.\n"
            "- Hover a setting's name to see if the machine edits it outside Adjustments.",
        ]),
        ("Presets",
         "Save the form as a named preset with **Save As…** and pick it from the "
         "dropdown any time (its values stage at once).\n\n"
         "- **Apply this preset automatically to every card I build** belongs to the "
         "picked preset: every Write build gets it, without visiting this tab.\n"
         "- Only the settings a game has are applied, so one preset works across titles.\n"
         "- Leave it off when different machines need different defaults."),
        ("Master Volume",
         "The volume the machine comes up at. **On card** is the number the game was "
         "built with: 30 on Led Zeppelin, 10 on Godzilla, 24 on John Wick.\n\n"
         "- The setting's own default is 64 on every Stern card, one past the 63 the "
         "firmware accepts, so the machine ignores it and uses that built-in number.\n"
         "- Setting this row changes both, including the one a factory reset reads.\n"
         "- Fresh cards only, as always: a set-up machine keeps its volume until a "
         "factory reset."),
        ("High scores",
         "The **High Scores** block at the bottom is the board a fresh card boots "
         "with (Stern ships the design team's initials). Every place on the board is "
         "listed, named or not.\n\n"
         "- Each place takes new initials, a player name and, where the firmware has "
         "it, a score.\n"
         "- Each field is capped at the room that place has in the firmware. Initials "
         "are always 3.\n"
         "- **Allow High Scores** and **Reset High Scores After** sit just above it.\n"
         "- A machine that already has scores keeps them."),
        ("All settings (and \"Debug\")", [
            "Under the form is every adjustment in the firmware, with the caption the "
            "machine prints and its id. The **Menu** column says where the machine "
            "shows it:",
            {"cards": [
                {"icon": "list", "tone": "ok", "title": "Adjustments",
                 "text": "The ordinary operator menu."},
                {"icon": "gear", "tone": "info", "title": "Service menu",
                 "text": "Edited on another screen: volume, speakers, software update, "
                         "tournament, redemption."},
                {"icon": "eye", "tone": "warn", "title": "Debug",
                 "text": "No menu shows it: factory tuning, mech timings, developer "
                         "leftovers."}]},
            "- Read from the menu's own pages in the game program, not guessed. A build "
            "whose menu can't be read flags nothing.\n"
            "- Click a header to sort, again to reverse, a third time for the firmware's "
            "order. Values sort as numbers.\n"
            "- **Double-click** a row to set its default, Debug ones too. It stages like "
            "the form; **Back to card value** unstages it. Values are in the firmware's "
            "own units (the form converts a few, like the volume).",
            {"note": "A row set this way has no help text or safety checks. A factory "
                     "value set to something the game never expected is on you.",
             "kind": "warn"},
        ]),
        ("Coin door (Home Editions)", [
            "Jurassic Park The Pin and Star Wars Home Edition ship without a coin door. "
            "Their game ignores the door's interlock switch, though the cabinet board "
            "still has its input. The **Coin door** box appears on those cards only.",
            "- Tick **This machine has a coin door fitted** and the next Build makes the "
            "game use the door as a Pro does: opening it puts up **48V DISABLED / CLOSE "
            "COIN DOOR** until it is shut.\n"
            "- The service buttons work with the door open or shut, as before.\n"
            "- The game's own **COIN DOOR BALL SAVER** setting works then too (off as "
            "shipped, as on a Pro): with it on, opening the door during a ball saves "
            "that ball. **COIN DOOR DISABLE TILT** has nothing to act on, as these "
            "machines have no tilt switch.\n"
            "- Staged with the project and carried by mod packs. A card that has its "
            "coin door already is left as it is.",
            {"note": "Only with a door and its interlock switch fitted. With nothing on "
                     "that input the game reads the door as open all the time and keeps "
                     "the message up.", "kind": "warn"},
        ]),
        ("Final wizard (ends the game)", [
            "On Godzilla, James Bond 007, Jaws, John Wick, Jurassic Park and Elvira's House "
            "of Horrors, playing the final wizard ends the player's game: every ball they "
            "have left ends the moment it starts. No setting of the game's changes that. "
            "The **Final wizard** box appears on those cards only.",
            "- Tick **The final wizard does not end the game** and the next Build changes "
            "the game so the player goes on to their remaining balls after it.\n"
            "- It changes the game itself (same card size), so it works on a machine that "
            "is already set up.\n"
            "- The other Player Challenge games end as they always have.\n"
            "- Staged with the project and carried by mod packs.",
            {"note": "A Player Challenge game that is the final wizard itself plays on after "
                     "it as well."},
        ]),
        ("Show hidden settings on the machine", [
            "**Show hidden settings in the machine's menu…** moves where the Feature "
            "Adjustments page stops, so the machine lists and edits the Debug settings "
            "after it.",
            "- The page is one straight run: everything up to your pick comes along. You "
            "can't show one and skip its neighbour.\n"
            "- Staged for the next Build by name, so a different game version can't "
            "show the wrong ones.\n"
            "- The tail often mixes useful settings with factory test entries and the "
            "game's own bookkeeping flags.\n"
            "- Titles whose menu couldn't be fully read don't offer the button.",
            {"note": "This changes one instruction in the game's program (same card "
                     "size, validation refreshed). Checked against the firmware but not "
                     "yet on a real machine.", "kind": "warn"},
        ]),
    ],
    "Emulate Spike1": [
        ("What it runs", [
            "Runs a Stern Spike 1 card image on this PC. Pick the card, press **Start**, "
            "and the game boots to its own attract on its own display, with sound.",
            {"cards": [
                {"icon": "image", "tone": "info", "title": "2015-2016 dot-matrix games",
                 "text": "WrestleMania, KISS, Game of Thrones, Ghostbusters and more."},
                {"icon": "text", "tone": "info", "title": "2012 home models",
                 "text": "Transformers The Pin and its siblings: no dot matrix, two "
                         "8-digit 16-segment displays."}]},
            "The game is an ARM program, so an emulator runs it with a software model "
            "of the machine's boards.",
        ]),
        ("Getting started", [
            "This tab is Windows only: the emulator runs inside WSL as root (no "
            "password needed on Windows).",
            {"flow": [
                {"icon": "sd", "title": "Pick", "text": "a Spike 1 card image"},
                {"icon": "download", "title": "Start",
                 "text": "the first time downloads the emulator, checked against this app"},
                {"icon": "play", "title": "Play",
                 "text": "later starts are quick; a card picked before is reused"}]},
            "- Nothing is compiled on your PC and no packages are needed.\n"
            "- **Fix setup** installs whatever is missing and says what is left. Start "
            "does the same by itself, so you only need it when something went wrong.\n"
            "- Network blocks the download? Fix setup offers a file picker: fetch the "
            "file on another machine; it is checked against the same checksum.",
        ]),
        ("The app's own Linux",
         "**Fix setup** can install a private WSL distro, **PAD-Runtime**, with the "
         "emulator already in it. Your own distro is not touched, and a PC with WSL "
         "but no distro can still run a game.\n"
         "- A one-time download of about 414 MB. Start never does it: use **Fix "
         "setup**, **Install** on the Visual Pinball tab's PAD runtime row, or "
         "**Update emulator Linux…** on the Stern Spike 2 Emulate tab (shown there "
         "when the installed one is older than this app).\n"
         "- Once installed, everything the app sends to Linux runs there: the "
         "emulators, extract and write, the disk tools and the card builder.\n"
         "- Set `PAD_RUNTIME=0` to use the PC's default distro instead."),
        ("Freeing space",
         "Right-click **Fix setup** to give space back. Each choice says what it will "
         "delete first, refuses while a game runs, and reports what it freed.\n\n"
         "| Choice | Deletes |\n"
         "|---|---|\n"
         "| Delete the emulator's data | the extracted games, card caches and save states |\n"
         "| Delete downloaded files | the emulator and the runtime image (re-downloadable) |\n"
         "| Remove the app's Linux | the PAD-Runtime distro itself |\n\n"
         "The emulator's work lives on a disk of its own, so removing the runtime "
         "keeps your save states."),
        ("Playing",
         "The display window shows the machine's screen; on a 2012 home model, its two "
         "16-segment displays with the words they spell underneath. A switch/LED "
         "window beside it lists every switch by name and position, read from the "
         "running game.\n\n"
         "| Key | Does |\n"
         "|---|---|\n"
         "| Arrow keys | flippers |\n"
         "| 1 | Start |\n"
         "| 5 | coin |\n"
         "| T | tilt |\n\n"
         "- Keys work in the display window; the full legend is in the window.\n"
         "- Click a switch to pulse it, as a rolling ball would. Right-click to hold "
         "it closed.\n"
         "- The coin door and service buttons are drawn as on the real door, and the "
         "trough shows each ball. Coin up and press Start to serve a ball and play a "
         "full game."),
        ("2012 home models",
         "Transformers The Pin and its siblings have no coin door, no service buttons "
         "and no operator menu, so those are drawn dead.\n"
         "- **Test mode:** hold both flippers for three seconds.\n"
         "- Their sound runs at the rate the game's own DAC asks for, not CD rate."),
        ("Save states", [
            "Snapshot a running game, mid-ball, and come back to it later.",
            {"flow": [
                {"icon": "save", "title": "Save now",
                 "text": "into a named slot; the game freezes a second or two"},
                {"icon": "refresh", "title": "Load",
                 "text": "swaps the running game for the slot, even after a restart"},
                {"icon": "play", "title": "Resume",
                 "text": "right where it was: display, switches and sound live"}]},
            "- A slot loads only into the title it was saved from.\n"
            "- Each takes about 15-50 MB on the WSL disk, survives emulator rebuilds "
            "and stays until deleted. **Rename** and **Delete** are on the same list.",
        ]),
        ("Good to know",
         "- **Volume** and **Mute** are this tab's speaker, live on a running game. The "
         "game's own volume is on the coin door, as on the machine.\n"
         "- The operator adjustments baked into the card are on the **Default "
         "Settings** tab, which works without the emulator.\n"
         "- **Restart WSL…** clears a wedged emulator (a frozen window, a game that "
         "will not stop). It closes **all** WSL sessions and takes about 15 seconds; "
         "your card and settings are untouched."),
    ],
    "Emulate JJP": [
        ("What it runs",
         "Runs the real Jersey Jack game on this PC, in its own resizable window, with "
         "sound. The game is a native Linux program, so it simply runs: no CPU "
         "emulation. It boots through its own startup into attract."),
        ("The purple USB key", [
            {"note": "The purple JJP security key is required and cannot be worked "
                     "around: the game's code is encrypted, and the key holds the "
                     "decryption key.", "kind": "warn"},
            "- Without it the game stops at once with \"Sentinel key not found\", as a "
            "real machine does.\n"
            "- A key is per title: one game's key will not start another.\n"
            "- Plug it into this PC before **Start**; the app hands it to the emulator.\n"
            "- Key on another PC? Pick **On another PC** in the Security key card, enter "
            "the key server and bus ID, and **Test**: **Start** borrows it over the "
            "network and **Stop** hands it back.",
        ]),
        ("Getting started", [
            {"flow": [
                {"icon": "lock", "title": "Plug in", "text": "the game's purple key"},
                {"icon": "folder", "title": "Pick", "text": "a JJP game ISO"},
                {"icon": "play", "title": "Start",
                 "text": "the first time restores several GB, a few minutes; later quick"}]},
            "The ISO is mounted **read only** and the game runs on a temporary overlay "
            "in memory.\n"
            "- What it writes (settings, high scores, the manual pages it renders on "
            "first boot) is thrown away on Stop.\n"
            "- Every start begins from a known state, and a crash cannot harm the image.",
        ]),
        ("Playing",
         "The switch matrix opens with the game: every switch and light drawn on the "
         "game's own playfield photograph, and the switches listed by name.\n"
         "- Click a switch to pulse it, as a rolling ball would.\n"
         "- Right-click to hold it closed: balls in the trough, the coin door.\n"
         "- The game reacts exactly as on the machine."),
        ("Good to know",
         "- **Volume** is this PC's level for the game and its boot menu, not the "
         "machine's own setting. It changes a running game at once.\n"
         "- WSL has no sound card, so sound goes through Windows. If music sounds "
         "wrong, judge by ear: a plain test tone passes cleanly even when music is "
         "distorted.\n"
         "- **Fix stuck state** restarts WSL to clear a wedged emulator (a frozen "
         "window, a game that will not stop). It closes **all** WSL sessions and takes "
         "about 15 seconds; your ISO and settings are untouched."),
    ],
    "Emulate DP": [
        ("What it runs",
         "Runs the real Dutch Pinball game on this PC, with sound, into attract. The "
         "emulator stands in for the machine's controller board and gives you every "
         "switch.\n\n"
         "| | The Big Lebowski | Alice's Adventures in Wonderland |\n"
         "|---|---|---|\n"
         "| Windows | one | two: the main screen and the round one |\n"
         "| Disk image | the machine's `.img` | the `full_image` installer |\n"
         "| Update zip on top | Yes | No |"),
        ("Getting started", [
            {"flow": [
                {"icon": "disk", "title": "Pick", "text": "the machine's disk image"},
                {"icon": "plus", "title": "Add",
                 "text": "an update zip, if you like (The Big Lebowski)"},
                {"icon": "play", "title": "Start",
                 "text": "the first time copies the game out: several GB, a few minutes"}]},
            "- The disk image is the only place most of the game's pictures and sounds "
            "are; update zips carry only what changed.\n"
            "- The update can be the official zip or one the Write tab built. It is laid "
            "over the image's version the way the machine installs it, so you can play "
            "a mod before it goes on a USB stick.\n"
            "- Both files are only read. Later starts are quick.\n"
            "- While a game is starting, **Start** is **Cancel**: it stops the copy and "
            "throws the half-copied game away.",
        ]),
        ("Playing",
         "The switch window opens beside the game: its own drawing of the machine "
         "with every switch on it (for Alice, a list), and all the switches by name.\n"
         "- Hold a switch with the mouse (a flipper, a ball in the scoop). "
         "Right-click to latch it until you right-click again.\n"
         "- Closed it? **Switches window** brings it back.\n\n"
         "### Keys (switch window focused)\n"
         "| Key | The Big Lebowski | Alice |\n"
         "|---|---|---|\n"
         "| Flippers | N and M | the Shift keys |\n"
         "| Start | 1 | 1 |\n"
         "| Coin | 3 | |\n"
         "| Service | 7, 8, 9, 0 | 7 Escape, 0 Enter, 8 and 9 volume |"),
    ],
    "Emulate BoF": [
        ("What it runs",
         "Runs the real Barrels of Fun game on this PC, in its own window, through its "
         "hardware check into attract. The game is a native Linux program; the "
         "emulator answers it as the FAST controller, its lighting boards and (Dune, "
         "Winchester) BoF's mechanism board would.\n\n"
         "| Game | Runs here |\n"
         "|---|---|\n"
         "| Dune | Yes |\n"
         "| Winchester Mystery House | Yes |\n"
         "| Labyrinth | Yes |\n"
         "| Bon Jovi | not yet: its .fun is a signed disk image with no board profile. "
         "Image Info says how an owner can help. |"),
        ("Getting started", [
            {"flow": [
                {"icon": "file", "title": "Pick",
                 "text": "the `.fun` update file, or one the Write tab built"},
                {"icon": "play", "title": "Start",
                 "text": "the first time unpacks 2-4 GB, a minute or two"},
                {"icon": "emulate", "title": "Play",
                 "text": "and check a mod before it goes on a USB stick"}]},
            "- The file is only read.\n"
            "- The last two builds are kept, so the same file starts quickly again; a "
            "rebuilt mod is unpacked fresh.\n"
            "- While a game is starting, **Start** is **Cancel**: it stops the unpack "
            "(slow on a slow or busy drive) and throws the half copy away.",
        ]),
        ("Playing",
         "The switch window opens beside the game: its own playfield drawing with "
         "every switch on it, and all the switches by name.\n"
         "- Hold a switch with the mouse (a flipper, a ball in a scoop). Right-click "
         "to latch it until you right-click again.\n"
         "- **Plunge** puts the shooter-lane ball into play, **Drain** sends one back "
         "to the trough, **Coin door** opens or shuts it.\n"
         "- The game's window moves and resizes like any other; the picture scales.\n"
         "- Closed the switch window? **Switches window** brings it back.\n\n"
         "### Keys (switch or game window focused)\n"
         "| Key | Does |\n"
         "|---|---|\n"
         "| Z and / (or Shift) | flippers |\n"
         "| 1 | Start |\n"
         "| 5 | coin |\n"
         "| Space | Launch |\n"
         "| P | Plunge |\n"
         "| D | Drain |"),
        ("Good to know",
         "- Each game keeps its settings, audits and high scores between runs, as a "
         "machine does.\n"
         "- Sound follows **Mute**; the game's own volume is in its service menu."),
    ],
    "Emulate AP": [
        ("What it runs",
         "Runs the real American Pinball game on this PC, in its own window, with "
         "sound, into attract. The game carries its own stand-in for the controller "
         "board; the emulator gives it the Python it runs on, a full trough, the coin "
         "door shut, and every switch.\n\n"
         "| Game | Runs here | Playfield picture |\n"
         "|---|---|---|\n"
         "| Houdini | Yes | Yes |\n"
         "| Oktoberfest | Yes | No: lights as a grid, switches as a list |\n"
         "| Hot Wheels | Yes | No: lights as a grid, switches as a list |\n"
         "| Legends of Valhalla | Yes | Yes |\n"
         "| Galactic Tank Force | Yes | Yes |\n"
         "| Barry-O's BBQ Challenge | not yet | |"),
        ("Getting started", [
            {"flow": [
                {"icon": "gear", "title": "Set up",
                 "text": "once: downloads the games' Python, about 1 GB"},
                {"icon": "file", "title": "Pick",
                 "text": "the `.pkg` game-code file, or one the Write tab built"},
                {"icon": "play", "title": "Start",
                 "text": "a new .pkg is unpacked once, under a minute"}]},
            "- Until set-up is done the tab says so, with **Set up emulator…** to do it "
            "now. The same button installs the app's own Linux when this PC lacks it "
            "(this emulator is not built for the PC's own WSL distro).\n"
            "- The file is only read. A rebuilt mod is unpacked fresh.\n"
            "- **Cache…** shows what is kept and deletes it.\n"
            "- While a game is starting, **Start** is **Cancel**.",
        ]),
        ("Playing", [
            "The virtual playfield opens beside the game, as on the Stern Emulate tab: "
            "switches and lights on the playfield picture where there is one, lit in "
            "the game's colors. A green dot is a switch the game sees made.",
            {"flow": [
                {"icon": "play", "title": "Start", "text": "serves a ball to the shooter lane"},
                {"icon": "up", "title": "Plunge", "text": "puts it into play"},
                {"icon": "grip", "title": "Hit", "text": "press the switches it would hit"},
                {"icon": "down", "title": "Drain",
                 "text": "ends the ball, or re-serves it during ball save"}]},
            "There is no ball physics. Ball save is the first seconds after the ball "
            "reaches the playfield (12 on Legends of Valhalla).\n"
            "- Hold a switch with the mouse; hold the right button on one to rip it "
            "(a spinner spinning).\n"
            "- Closed the playfield, or lost it behind the game? **Playfield window** "
            "beside Stop brings it to the front.\n\n"
            "### Keys (playfield or game window focused)\n"
            "| Key | Does |\n"
            "|---|---|\n"
            "| Arrow keys | flippers |\n"
            "| 1 | Start |\n"
            "| 5 | coin (two or four make a credit) |\n"
            "| Space | Action button |\n"
            "| T | tilt |\n"
            "| Letters beside switches | press them |\n"
            "| F / D | plunge / drain |\n"
            "| C | open or shut the coin door |\n"
            "| Backspace, -, =, Enter | service buttons |\n"
            "| Pause or F9 | freeze the game (playfield window) |",
        ]),
        ("Good to know",
         "- Hot Wheels and Galactic Tank Force play through American Pinball's own "
         "player, which only one game at a time can use.\n"
         "- **Volume** and **Mute** change the sound while it plays; the game's own "
         "volume is in its service menu.\n"
         "- **Stop** ends the game and closes the switch window. So does closing any "
         "of the game's windows with its X."),
    ],
    "Emulate Spooky": [
        ("What it runs",
         "Runs the real Spooky Pinball game on this PC, in its own window, with sound. "
         "The emulator answers the game as its controller board would, with a full "
         "trough, and gives you every switch. Pick the update file named as the "
         "machine wants it: the emulator tells the games apart by that name.\n\n"
         "| Game | Update file | Runs here |\n"
         "|---|---|---|\n"
         "| Beetlejuice | `v….beetlejuice` | Yes |\n"
         "| Scooby-Doo | `v….scooby` | Yes |\n"
         "| Texas Chainsaw Massacre | `tcm-….pkg` | Yes |\n"
         "| Evil Dead | `….ed` | Yes |\n"
         "| Looney Tunes | `….looney` | Yes |\n"
         "| Halloween | `code_H78.pkg` | Yes |\n"
         "| Ultraman | `code_UM.pkg` | Yes |\n"
         "| Rick and Morty | `rm-gamecode-….pkg` | Yes |\n"
         "| Alice Cooper's Nightmare Castle | `ac-gamecode.pkg` | Yes |\n"
         "| Jetsons | `Jetsons_Code.zip` | Yes, DMD in a window of its own |\n"
         "| Domino's | `DOM_v6.zip` | Yes, DMD in a window of its own |\n"
         "| Rob Zombie | `rzupdate_V26.zip` | Yes, DMD in a window of its own |\n"
         "| Total Nuclear Annihilation | | not yet: its update cannot be opened |\n"
         "| America's Most Haunted | | not yet: its update has no game program |\n\n"
         "The DMD games' window has the display, every switch, the balls and the "
         "sound, and needs no app Linux."),
        ("Getting started", [
            {"flow": [
                {"icon": "file", "title": "Pick",
                 "text": "the update file, or one the Write tab built"},
                {"icon": "play", "title": "Start",
                 "text": "the first time unpacks it in the app's Linux, a few minutes"},
                {"icon": "refresh", "title": "Load",
                 "text": "the game takes a minute or two, as on the machine"}]},
            "- The file is only read; the unpacked copy is kept, so the next start skips "
            "that. **Cache…** beside Browse… shows what is kept and deletes it.\n"
            "- The first Start of Rick and Morty or Alice Cooper also downloads the "
            "Python those two run on (once, a few minutes).\n"
            "- The game draws on this PC's graphics card through WSL. Where WSL has no "
            "graphics card it draws on the processor, much slower.\n"
            "- While a game is starting, **Start** is **Cancel**: it throws a "
            "half-unpacked copy away.",
        ]),
        ("Playing", [
            "The virtual playfield opens beside the game once it reaches attract, as on "
            "the American Pinball and Stern Emulate tabs. Spooky ships no playfield "
            "picture, so the switches are a list; a green dot is a switch the game sees "
            "made.",
            {"flow": [
                {"icon": "play", "title": "Start", "text": "serves a ball to the shooter lane"},
                {"icon": "up", "title": "Plunge",
                 "text": "presses Launch; the game fires the ball"},
                {"icon": "grip", "title": "Hit", "text": "press the switches it would hit"},
                {"icon": "down", "title": "Drain",
                 "text": "ends the ball, or re-serves it during ball save"}]},
            "- There is no ball physics. Hold a switch with the mouse; hold the right "
            "button on one to rip it (a spinner spinning).\n"
            "- Closed the playfield? **Playfield window** beside Stop brings it back.\n\n"
            "### Keys (playfield window focused)\n"
            "| Key | Does |\n"
            "|---|---|\n"
            "| Arrow keys | flippers |\n"
            "| 1 | Start |\n"
            "| 5 | coin |\n"
            "| Space / Down | Launch / Action button |\n"
            "| T | tilt |\n"
            "| Letters beside switches | press them |\n"
            "| F / D | plunge / drain |\n"
            "| Backspace, -, =, Enter | service buttons |\n"
            "| Pause or F9 | freeze the game |\n\n"
            "The same keys work in the game's own window, except the ones the game uses "
            "there itself (Beetlejuice: Enter starts, Space launches, the arrows flip).",
        ]),
        ("Good to know",
         "- **Volume** and **Mute** (and the VOL bar in the playfield window) set the "
         "game's sound live. The game's own volume is in its service menu.\n"
         "- **Stop** ends the game and closes the playfield; so does closing the "
         "game's window.\n"
         "- The game keeps its settings, audits and high scores between runs, as a "
         "machine does."),
    ],
    "Emulate PB": [
        ("What it runs",
         "Runs the real Pinball Brothers game on this PC, in its own window. Each game "
         "is two Linux programs (the rules and the screen); the emulator stands in "
         "for the controller boards (Predator's FAST boards, or the I/O boards the "
         "others share), with six balls in the trough.\n\n"
         "| Game | Runs here |\n"
         "|---|---|\n"
         "| Predator | Yes |\n"
         "| Alien | Yes |\n"
         "| ABBA | Yes, but the screens stay dark: its updates carry no pictures or "
         "videos |\n"
         "| Queen | Yes |"),
        ("Getting started", [
            "Pick the `.upd` update for the version you want. Pinball Brothers ships a "
            "full update, then follow-ups with only what changed: pick the follow-up, "
            "with the rest in the same folder, and the emulator uses them all.\n\n"
            "| Game | Pick | Also in the folder |\n"
            "|---|---|---|\n"
            "| Predator | `pbpp_predator_game_1_0_1.upd` | the full "
            "`pbpp_predator_game_1_0.upd` |\n"
            "| Alien | `pbap412.upd` | `pbap411.upd`, and the first time "
            "`clonezilla-live-alien40.iso` |\n"
            "| ABBA | `pbap145.upd` | `pbap141.upd`, and the first time "
            "`clonezilla-live-alien40.iso` |\n"
            "| Queen | `pbq0210G.upd` | `clonezilla-live-queen20d.iso` (about 10 GB) |\n\n"
            "- Alien's restore image is the machine's own Linux, which Alien and ABBA "
            "both run on. Queen's holds its pictures, videos and sound.\n"
            "- Pick a restore image itself to play the game as it left the factory. The "
            "files are only read.",
            {"flow": [
                {"icon": "gear", "title": "Set up",
                 "text": "Predator only: about 700 MB of sound and video libraries, once"},
                {"icon": "file", "title": "Pick", "text": "the update, as above"},
                {"icon": "play", "title": "Start",
                 "text": "the first time unpacks it, a few minutes"}]},
            "- **Set up emulator…** does the set-up ahead of time; otherwise the first "
            "Start does it. Alien and ABBA need none.\n"
            "- First-start unpack: Predator about 5 GB, Alien's restore image about "
            "3.5 GB, a full Alien or ABBA update about 2.5 GB. It is kept, so the same "
            "file starts quickly again; **Cache…** beside Browse… shows and deletes it.\n"
            "- While a game is starting, **Start** is **Cancel**: it throws a "
            "half-unpacked copy away.",
        ]),
        ("Playing", [
            "The virtual playfield opens beside the game once it reaches attract, as on "
            "the American Pinball and Stern Emulate tabs. These games ship no playfield "
            "picture, so the switches are a list; a green dot is a switch the game sees "
            "made, and the lights are the LEDs the game has lit.",
            {"flow": [
                {"icon": "play", "title": "Start", "text": "serves a ball to the shooter lane"},
                {"icon": "up", "title": "Launch", "text": "Space fires it into play"},
                {"icon": "grip", "title": "Hit", "text": "press the switches it would hit"},
                {"icon": "down", "title": "Drain", "text": "sends it back to the trough"}]},
            "- There is no ball physics. Hold a switch with the mouse; hold the right "
            "button on one to rip it (a spinner spinning).\n"
            "- **Queen** has no Launch button: both flippers launch, and also start the "
            "song picked on the song select each ball begins with (F does both).\n"
            "- Closed the playfield? **Playfield window** brings it back.\n\n"
            "### Keys (playfield or game window focused)\n"
            "| Key | Does |\n"
            "|---|---|\n"
            "| Arrow keys | flippers |\n"
            "| 1 | Start |\n"
            "| 5 | coin |\n"
            "| Space | Launch button |\n"
            "| T | tilt |\n"
            "| Letters beside switches | press them |\n"
            "| F / D | plunge / drain |\n"
            "| Backspace, -, =, Enter | the coin door's buttons |\n"
            "| Pause or F9 | freeze the game |",
        ]),
        ("Good to know",
         "- **Volume** and **Mute** (and the VOL bar in the playfield window) set the "
         "game's sound live. The game's own volume is in its service menu.\n"
         "- **Stop** ends the game and closes the playfield.\n"
         "- The game keeps its settings, audits and high scores between runs, as a "
         "machine does."),
    ],
    "Emulate": [
        ("What it does", [
            "Runs the real Stern Spike 2 game on this PC, in its own window, at 60 fps "
            "on the graphics card, with sound and keyboard.",
            {"flow": [
                {"icon": "sd", "title": "Pick a card",
                 "text": "**Browse…** to a card image"},
                {"icon": "play", "title": "Start",
                 "text": "**Start emulator**"},
                {"icon": "emulate", "title": "It boots",
                 "text": "splash, boot, then attract or the operator menu, as a machine does"},
                {"icon": "stop", "title": "Stop",
                 "text": "kills every part of it, then checks nothing survived"}]},
            "- If leftovers are stuck where nothing inside WSL can clear them, Stop says "
            "so and offers a WSL restart.\n"
            "- **On a Mac** the window is Screen Sharing: the picture renders inside the "
            "container and the app opens the viewer once the game is up (the VNC "
            "password is `pinball`). All the emulator's windows live in that one "
            "desktop: click a window once to give it the keyboard, drag title bars to "
            "arrange them.",
        ]),
        ("Getting set up", [
            "The tab checks this PC before you press anything. A ready PC shows "
            "nothing; one that is not gets an amber notice naming each missing piece "
            "and what it is for.",
            {"flow": [
                {"icon": "search", "title": "Check setup…",
                 "text": "looks only, writes the full answer to the log"},
                {"icon": "download", "title": "Set up emulator…",
                 "text": "lists every change first, then installs"},
                {"icon": "play", "title": "First Start",
                 "text": "a few minutes, once"},
                {"icon": "check", "title": "Later runs",
                 "text": "start in seconds"}]},
            {"cards": [
                {"icon": "gear", "tone": "info", "title": "Windows",
                 "text": "Runs in WSL. **Set up emulator…** installs what is missing. "
                         "No password, nothing on the Windows side changes."},
                {"icon": "gear", "tone": "info", "title": "macOS",
                 "text": "Runs in a Docker container that already carries every package. "
                         "The button gets Docker (Colima) if it is missing."},
                {"icon": "gear", "tone": "info", "title": "Linux",
                 "text": "A notice but **no button**: the work needs sudo, so it prints "
                         "the command to run."}]},
            "The first Start builds the game's Linux from your card and compiles two "
            "small programs: several minutes with no game window, the log saying what "
            "it does. Later runs only rebuild what an app update changed.",
        ]),
        ("Set up emulator…",
         "Installs what the amber notice names. It lists every package and file it "
         "will change first, and **No** leaves the machine exactly as it was.\n\n"
         "### On Windows\n"
         "- Installs the packages inside WSL, registers the kernel's handler for "
         "32-bit ARM programs (which is what the game is), and turns on systemd in "
         "`/etc/wsl.conf` so that handler survives a WSL restart.\n"
         "- Two compilers, not interchangeable: the ARM one builds the hardware shim; "
         "plain gcc (with libc6-dev, which gcc does not always bring) builds the "
         "renderer that draws the picture.\n"
         "- If Ubuntu's \"universe\" component is off (apt says \"has no installation "
         "candidate\"), turning it on is the first step. Packages go on one at a time, "
         "so one apt cannot get never blocks the rest.\n"
         "- On Ubuntu 25.10 and 26.04, qemu-user-static is just another name for "
         "qemu-user-binfmt, so that is the one installed. If your Ubuntu does not "
         "publish qemu-user-static at all, the button fetches Ubuntu 24.04's copy, "
         "checks it, and installs the file without changing your package sources.\n"
         "- Anything no fetch can supply: the button goes away, and the notice names "
         "your release and gives the two wsl commands to switch to one that has it.\n\n"
         "### Feature-only pieces\n"
         "Some missing pieces cost a feature, not the emulator, and are listed under "
         "the feature's name:\n\n"
         "- **Save states need:** busybox-static and criu. Without them every title "
         "still runs; only save slots do nothing (\"The emulator runs on this PC. "
         "Save states do not yet.\"). No Ubuntu publishes criu, so the button builds "
         "it from source and says how long first. If only these cannot be had, your "
         "Linux is left alone and save states stay off. Linux desktops are never "
         "asked for them.\n"
         "- **Multi-boot cards need:** make, which builds a multi-boot card's boot "
         "menu. Every desktop is asked for it.\n\n"
         "### On Linux and macOS\n"
         "- **Linux:** the notice prints the command, for apt or (on Arch and its "
         "spins) pacman, with the AUR-only ARM cross compiler on its own line.\n"
         "- **macOS:** `docker` is only a client, so a Homebrew or MacPorts docker has "
         "nothing to run a container with. The button installs Colima (and the docker "
         "client if missing) with whichever of Homebrew or MacPorts you have, then "
         "starts it, every line in the log. You never type a command; macOS asks for "
         "a password in its own dialog when one is needed."),
        ("Check setup…", [
            "Always there, on every platform. It **changes nothing**, so it is safe to "
            "press any time, even while a game runs.",
            "- The log gets the whole answer, even when nothing is wrong: which "
            "packages are there, whether the 32-bit ARM handler is registered and "
            "survives a WSL restart, who the distro logs in as, whether it can start "
            "Windows programs, the sound path and the Windows Python it found, the "
            "display, and a last line saying whether this PC can run the emulator.\n"
            "- On a Mac it reports Docker instead (the container carries the packages).\n"
            "- The amber notice only speaks when something is broken; this button tells "
            "\"all fine\" apart from \"never asked\".",
            {"note": "When a run goes wrong, this log is the thing to send.",
             "kind": "tip"},
        ]),
        ("Update emulator Linux… (Windows)",
         "Shows only when the Linux this app installed is from an older version of it.\n\n"
         "- Until you press it, the emulator runs in your PC's default distro, which "
         "lacks the emulator's tools, so things may not work.\n"
         "- Nothing is lost: your cards, extractions and save states are still in the "
         "old one. The button moves you to the current runtime.\n"
         "- Replacing removes the old one, so it asks first and says what is inside.\n"
         "- A PC that never had the runtime is not asked and keeps its own distro."),
        ("Start Docker / Get Docker… (macOS)",
         "A Mac runs the emulator (a Linux program) in a container, so Docker is to "
         "macOS what WSL is to Windows.\n\n"
         "- **Start Docker** starts the engine you have: Docker Desktop, OrbStack, "
         "Rancher Desktop or Colima.\n"
         "- **Get Docker…** opens the Docker Desktop download page, on a Mac with no "
         "package manager for Set up emulator… to use.\n"
         "- It shows only when Docker is not ready and there is nothing to install, "
         "and goes away once Docker is ready.\n"
         "- The app looks for docker in Homebrew's, MacPorts' and Docker Desktop's "
         "places as well as PATH; `PAD_DOCKER` points it elsewhere.\n"
         "- Windows and Linux never need Docker to emulate."),
        ("The card it runs", [
            "This tab ignores the Input box: it runs the card image you pick here.",
            "- The card is mounted **read only** and run in place: nothing is extracted, "
            "nothing writes to it. A stock card and your own build both work.\n"
            "- The path is remembered per project.\n"
            "- **Boot selector** ticks itself when the card carries a boot menu (a "
            "multi-image card); pick the build with the flipper buttons, as on the machine.",
            {"cards": [
                {"icon": "check", "tone": "ok", "title": "Green line",
                 "text": "The card the project was extracted from, or one PAD built from it."},
                {"icon": "warn", "tone": "warn", "title": "Amber line",
                 "text": "Another project's build or an unrelated card. **Browse…** to one "
                         "unticks Apply, so it runs as it is."}]},
            "**Use the extracted card** and **Use the last build** switch back to the "
            "project's own cards. The last build is the newest card in the project's "
            "build folder that PAD built from this project.",
        ]),
        ("Run my edits without a build", [
            "Tick **Apply my replaced assets on top, without rebuilding the card** and a "
            "run plays the card you picked plus your edits. No card is built and "
            "nothing is written to the card image.",
            {"flow": [
                {"icon": "edit", "title": "Pick",
                 "text": "replacements on the Replace tabs"},
                {"icon": "save", "title": "Apply",
                 "text": "Start puts them in the project folder, as a build would"},
                {"icon": "copy", "title": "Patch",
                 "text": "copies of just the card files they land in (e.g. image.bin + .sidx)"},
                {"icon": "play", "title": "Run",
                 "text": "the game reads those over the read-only card"}]},
            "- Start takes as long as your edits need to re-encode; after that only "
            "what changed since is redone.\n"
            "- **Assets folder** beside it is the Write tab's, shown read only.\n"
            "- **Include my Scenes tab edits** and **Stock colors: leave out my color "
            "profile** appear under it when they apply; hover them for what they do.\n"
            "- **Show it through the machine's screen** draws the game through your "
            "Machine screen (Color profile tab), so this PC shows the colors the "
            "machine's own screen will. It sits next to Boot selector and Topper and "
            "works with or without replaced assets, on any card; a change takes effect "
            "at the next Start. Emulator only: a Write never carries it.\n"
            "- **Boot-menu card:** edits are prepared from the first game image on it "
            "and applied over whichever image you pick at the menu. To edit another "
            "image, build it on its own and rebuild the multi-boot card.\n"
            "- **A card PAD built:** edits are prepared from the card the project was "
            "extracted from (if it is still there, same game version) and run over the "
            "built one. The log names that card.",
            {"note": "If the edits cannot be delivered (no assets folder, nothing to "
                     "compare them with, or an edit that traces back to no file on the "
                     "card), the run says so and does not start, rather than quietly "
                     "playing the stock card.", "kind": "warn"},
        ]),
        ("Card cache",
         "The first boot of a card copies it to a local cache, so later boots start in "
         "seconds instead of minutes.\n\n"
         "- The copy starts the moment you pick a card (\"Copying card: …\" in the "
         "status line), so it is often done before you press Start.\n"
         "- **Cache…** beside Browse lists every cached card with its size and last "
         "boot, and deletes any of them. The same cards are in **Manage disk space** "
         "(⚙ settings menu).\n"
         "- Deleting is always safe: the card re-copies on its next boot. When disk "
         "space runs low the cache drops the longest-unbooted cards by itself."),
        ("Country, Power and Topper", [
            "The row under the card is the cabinet it is fitted to. Both choices are "
            "remembered for every project and take effect at the next Start.",
            "- **Country (DIP switches):** sets the CPU board's eight country DIP "
            "switches and the country stored in the machine (the one the boot screen "
            "shows, with its coin settings). A changed country opens the game's Guided "
            "Setup to confirm it, as a real machine does. **As set in the game** leaves "
            "both alone, but a country picked earlier stays stored.",
            {"cards": [
                {"icon": "check", "tone": "ok", "title": "60 Hz mains",
                 "text": "How the emulator has always run."},
                {"icon": "check", "tone": "ok", "title": "European machine",
                 "text": "A 50 Hz board on 50 Hz mains. Runs normally."},
                {"icon": "warn", "tone": "warn", "title": "US machine",
                 "text": "A 60 Hz board on 50 Hz mains. Some games refuse; the line under "
                         "Power says which. A refusal stays on screen."}]},
            "- **Topper:** some machines have a second screen above the backbox "
            "(Mandalorian's hologram, Venom's, Stranger Things' projector); the emulator "
            "opens a window for it at that panel's real size. Untick to run without "
            "one, as a cabinet without the accessory does (losing what needs it).",
        ]),
        ("Starting up",
         "The game window and the virtual playfield come out over this app by "
         "themselves. It can take a few seconds: Windows will not put a window in "
         "front of the one you just clicked, so the rig keeps asking.\n\n"
         "| Status line | Means |\n"
         "|---|---|\n"
         "| Passing Tech Alerts… | The boot's operator readout; the emulator steps past it |\n"
         "| Stuck at Tech Alerts | It pressed several times and nothing changed: read its hint |\n"
         "| Game running | Up. It does not guess between attract, the menu and a game |\n\n"
         "- **What it costs:** about 15% of one CPU core waiting, about a third of a "
         "core running, plus 1–2 GB of memory, shown live in the status line.\n"
         "- **No time limit:** it runs until you press Stop emulator or close its "
         "window.\n"
         "- **Restart game**, beside Stop emulator, boots the game again, as "
         "switching the machine off and on does: the game window goes back to the "
         "boot screen and the virtual playfield stays open."),
        ("Sound and video",
         "- **Volume** and **Mute** set the emulator's own sound, live, and are "
         "remembered. They are not the game's volume (the coin door's -/+), which "
         "stays as the machine has it.\n"
         "- The sound plays on your PC speakers: through WSL on Windows, through "
         "ffplay on a Mac.\n"
         "- Silence after the boot chime usually means it is still at Tech Alerts.\n"
         "- **Clips play:** the machine's video decoder is a chip this PC lacks, so "
         "ffmpeg on the Linux side decodes each clip for the game. Scenes, text, "
         "lamps, switches and sound all work.\n"
         "- That Linux ffmpeg is not the one this app puts on your PATH. Missing, "
         "everything else works but clips do not; the run checks first and names "
         "the package."),
        ("The virtual playfield", [
            "A second window beside the game draws the machine's playfield, every "
            "insert lit live and every switch clickable: click one and the game reacts "
            "as if the ball rolled over it.",
            "- **The picture** is the game's own playfield drawing, read from your "
            "card. It shows as an **X-ray** (light lines on dark) so the lit inserts "
            "stand out; the **X-ray / Drawing** switch "
            "in its top corner shows the drawing as the game ships it instead, and the "
            "window remembers your pick.\n"
            "- **Down the right:** the keyboard reference (a row lights when the game "
            "sees that switch), the coin-door buttons (click and hold **BACK**, **-**, "
            "**+**, **SELECT** for the operator menu), a coin door open/close button "
            "(open cuts 48V, like the real interlock) and the ball trough, each "
            "position clickable.\n"
            "- A click on a VUK, scoop or eject drops a ball in: it stays there until "
            "the game kicks it out, as on the machine. Click it again to take it out.\n"
            "- **Down the left:** the cabinet's own lighting, live: the topper, the "
            "speaker lights (a ring, like the lights round the speakers), the "
            "expression lighting blades (a column a side) and a UV lighting kit, on "
            "the games that have them. They are there from the start, dark until the "
            "game lights them: many games leave the topper and speakers off in "
            "attract. Games "
            "with no playfield drawing show them the same way in the LED grid, and "
            "show the SHAKER MOTOR panel too. "
            "Untick **Expression lights** in the side panel's CABINET LIGHTS box to "
            "hide the blades and speaker lights; the window remembers it.\n"
            "- **Insert colors:** an RGB insert is drawn in the color the game "
            "gives it. A single-color insert can only be told how bright to be, and "
            "on the machine it glows in its own color, which the game files don't "
            "name, so it is drawn white. Give each its color in the side panel's "
            "INSERT COLORS box (hover a row to see which insert it is); the window "
            "keeps them for that game. The **Real LEDs / All RGB** switch at the top "
            "left of the picture shows the inserts as the machine has them (Real "
            "LEDs) or as if every insert were RGB (All RGB).\n"
            "- The keyboard works with this window focused too.\n"
            "- It builds itself from the title, so every Spike 2 game gets one. The "
            "switches appear a minute or so into a run, once the game lists them.\n"
            "- **Pause** (or F9), in either window or on the bottom bar, freezes the "
            "whole game, video and sound too. **Resume** carries on from that frame. "
            "The bar also has **Restart game** (as on the Emulate tab), Volume and "
            "Mute.",
        ]),
        ("Save states", [
            "**Save state** on the playfield window (Windows and Mac) checkpoints the whole "
            "running game into a slot; **Load state** brings that exact moment back, "
            "mid-game too, even in a later session.",
            "- Every game has its own **ten slots**; one game's saves never load into, "
            "overwrite or show among another's. The tab lists the picked card's slots "
            "(other games' are counted under the list; no card picked shows all).\n"
            "- **Rename** and **Delete** manage them; the line under the list totals "
            "them against free space.\n"
            "- **Launch** starts the emulator straight into the selected slot, or loads "
            "it into the run that is up.\n"
            "- A load after you replaced assets plays the new video and audio; art "
            "already on screen keeps its saved look until the game redraws it.\n"
            "- They need busybox-static and criu in WSL. Without them every title runs; "
            "only slots do nothing, and the tab says so before Start. **Set up "
            "emulator…** gets both.\n"
            "- On a Mac the emulator's container brings them. Docker Desktop cannot "
            "freeze a running game, so there a run starts without save states and the "
            "log says why; colima, which **Set up emulator…** installs, can.",
            {"note": "Each slot takes about 50–150 MB of the emulator's disk, and a save briefly "
                     "needs about 1.5 GB free. Saving freezes the game and its sound for "
                     "a few seconds. A slot only loads on the same app build, game and "
                     "firmware it was saved on: after an update older slots are refused "
                     "with a note. The ⓘ beside the section spells out the cost.",
             "kind": "warn"},
        ]),
        ("Reset windows",
         "Puts the emulator's windows back at their default place and size.\n\n"
         "- The rig reopens each window where you last dragged it, without checking "
         "that spot is still on screen. A window left on an unplugged second monitor "
         "comes back out of reach.\n"
         "- Works on every platform, with or without a game running."),
        ("Game display",
         "Where the game window goes, on Windows: pick a **Monitor** and how it "
         "sits there.\n\n"
         "- **Where I leave it:** the game window opens where you last dragged it, "
         "with its frame, as it always has.\n"
         "- **Full screen:** the game's picture fills the monitor you pick. Made for "
         "a second screen or a cabinet's own LCD.\n"
         "- **Window:** a window of the **Width** and **Height** you give, its top "
         "left corner **X** and **Y** pixels from the top left of that monitor "
         "(1360 x 768, the machine's own screen, to start).\n"
         "- **Borderless** takes away the title bar and frame. A new choice starts "
         "borderless.\n"
         "- Every change is saved at once and applies to a running game within half "
         "a second: no restart. Monitor 1 is the main one, the rest left to right. "
         "If the chosen monitor is unplugged, the game goes on the main one until it "
         "is back.\n"
         "- The Visual Pinball tab's window layouts set this too, for the game's "
         "screen in a cabinet."),
        ("Black game window",
         "On Windows the usual cause is a WSL that logs in as **root**: the renderer "
         "cannot reach WSLg's shared memory and draws nothing, while sound, switches "
         "and the playfield all work.\n\n"
         "- **Check setup…** names it. **Install emulator Linux…** fixes it: the "
         "emulator gets its own Linux with an ordinary user, and your own WSL distro "
         "is not changed. Or give your distro an ordinary user, make it the default "
         "and restart WSL. The rig will not guess a user for you.\n"
         "- The log's \"picture:\" lines say whether there is a picture (only when "
         "that changes). \"STILL BLACK\" while video frames go in means the game is "
         "drawing black, so **Restart WSL…** is not the cure.\n"
         "- `PAD_GL_PICCHECK` sets the seconds between checks, or 0 to switch them off."),
        ("Restart WSL…", [
            "The cure for faults that live in WSL, not the game:",
            "- a game window that will not close (its X does nothing);\n"
            "- crackly or stuttery sound after a long session;\n"
            "- stale graphics libraries after a driver or WSL update: the run carries "
            "on in software (a few percent slower) and says so in the log, and this "
            "puts the graphics card back.",
            {"note": "It closes **everything** running in WSL, not just the emulator, so "
                     "it asks first and is grayed out while a run is up: stop the game "
                     "first. Nothing on disk is lost.", "kind": "warn"},
            "- A Stop that cannot finish offers the same restart by itself.\n"
            "- Afterwards the tab checks the PC again (the ARM handler only survives on "
            "a distro that boots systemd). If it came back unable to run the emulator, "
            "it says so with **Set up emulator…** beside it.",
        ]),
    ],
    "Compare": [
        ("What it does",
         "Pick two card images of the same game (two releases, or a modded card and "
         "its stock base) and see what changed from A to B:\n\n"
         "- files added, changed and deleted, per kind: videos, images, scenes, music "
         "banks\n"
         "- the sounds\n"
         "- adjustment defaults and the high-score board\n\n"
         "**Copy Report** puts the whole report on the clipboard as plain text."),
        ("Two project folders", [
            "Pick a project folder for A and for B (**Folder…**) to check two versions "
            "of a mod, or a mod against the stock extract. Every manufacturer has this, "
            "not only the ones whose cards can be compared.",
            {"flow": [
                {"icon": "folder", "title": "Folder A", "text": "say, version 1.0 of your mod"},
                {"icon": "folder", "title": "Folder B", "text": "and version 1.1"},
                {"icon": "compare", "title": "Compare",
                 "text": "added, changed, moved and deleted files"}]},
            "- Files are compared as they are in the folders now, so a replacement you "
            "picked counts even though the folder was extracted from the stock card.\n"
            "- By kind: sounds, videos, images, the Text tab's strings, everything else. "
            "A file renamed or moved is one **Moved** row.\n"
            "- **Project settings** lists what a build uses that no file holds: a "
            "sound's Level, a clip's length or conversion, which files get the color "
            "profile.\n"
            "- Stern sounds pair up by slot, whatever names the two extracts gave them.\n"
            "- The first compare of two big projects reads every file once (a few "
            "seconds per GB); after that it is quick.\n"
            "- **Double-click** a file row to open the file straight from its folder.",
        ]),
        ("Reading the report",
         "Every list is complete: a version that renumbers 4,000 sounds lists 4,000 "
         "rows.\n\n"
         "- **Rows per list** (12 / 25 / 50 / 100 / All, next to Copy Report) sets how "
         "many show; the rest fold into one \"… and N more\" line. It only redraws "
         "(the cards are not read again) and is remembered. Copy Report always has "
         "every row.\n"
         "- **Double-click** \"… and N more\" to open just that list, keeping your place.\n"
         "- **Double-click** a file row to open the file itself in your usual program. "
         "Only that file is read off its card (A for a deleted file, B otherwise), so "
         "it is quick. Spike 2 stores videos without a file type, so the app names the "
         "copy .mp4 / .png / .jpg / .wav / .ogg from its first bytes; a file it doesn't "
         "know may not open."),
        ("How files are diffed",
         "Straight off the cards, no Extract needed, in seconds. Every moddable file "
         "on a Spike 2 card is in the card's validation record with its size and a "
         "digest, so \"modified\" means Stern's own digest changed. A scene counts as "
         "modified when any file in its folder changed. Sounds work differently (next)."),
        ("Sounds", [
            "All sounds are packed in one file (image.bin), and Stern repacks it on "
            "every build, so two releases with the same sounds still differ byte for "
            "byte. Compare never judges sounds by that.",
            {"cards": [
                {"icon": "sd", "tone": "", "title": "From the cards alone",
                 "text": "Only the sound and fragment counts and the size."},
                {"icon": "wave", "tone": "ok", "title": "After Extract Both",
                 "text": "Sounds changed, moved to a new slot, added or removed. "
                         "**Double-click** one to play it."}]},
            "- Sounds are matched by content first, so one inserted sound doesn't read "
            "as a thousand changed.\n"
            "- The match is on the audio. A repack changes the first decoded frame of "
            "every sound; the report steps over it and a \"Codec lead-in\" row says how "
            "many pairs needed it.\n"
            "- The extracts are found by the card each one came from, whatever their "
            "names or order.",
        ]),
        ("Extract Both", [
            {"flow": [
                {"icon": "folder", "title": "Pick a folder",
                 "text": "the one to HOLD both, not a project folder"},
                {"icon": "extract", "title": "Card A", "text": "extracted to its own sub-folder"},
                {"icon": "extract", "title": "Card B", "text": "then the same"}]},
            "Use it when the report says WHAT changed and you want both versions' files "
            "side by side (and to see which sounds changed). Each sub-folder is named "
            "after its card file. Canceling, or saying no to an overwrite, stops the "
            "pair there; card B is not left queued.",
        ]),
        ("Adjustments and high scores",
         "Both game programs are read the same way the Defaults tab reads them: "
         "settings added or removed, defaults that changed, and high-score places "
         "whose initials, name or score changed. These are the cards' built-in "
         "defaults; a machine's live settings and scores are in the card's data "
         "partition, apart from the game program."),
    ],
    "Multi-boot": [
        ("What it does", [
            "Builds ONE card that holds several complete game images and shows a "
            "menu at power-up, so stock code and your builds live on one machine "
            "without swapping cards.",
            {"flow": [
                {"icon": "plus", "title": "Add images",
                 "text": "the first one is the primary"},
                {"icon": "gear", "title": "Set the menu",
                 "text": "titles, pictures, music, countdown"},
                {"icon": "write", "title": "Build / flash",
                 "text": "one green button"},
                {"icon": "multiboot", "title": "Power up",
                 "text": "flippers choose, START boots"}]},
            "- The countdown boots the remembered choice by itself.\n"
            "- The **first image is the primary**: the card boots from its files, and "
            "the machine falls back to it if the menu ever fails.\n"
            "- Up to **16 images** on a Stern card. From five on, the menu scrolls "
            "three at a time with a counter under the cards.\n"
            "- One card in the menu can stand for several games and boot one at "
            "random (see [Random cards](#random-cards)).\n\n"
            "| | Stern Spike 2 | Jersey Jack | Barrels of Fun |\n"
            "|---|---|---|---|\n"
            "| You build | an SD card | an install stick, or the SSD | one .fun update |\n"
            "| Images | up to 16 | 2, same game version | stock + up to 3 builds |\n"
            "| Random cards | Yes | No | Yes |\n"
            "| Compact build | Yes | No | No |\n"
            "| Run in emulator | Yes | Yes | No |",
        ]),
        ("Random cards", [
            "**Add image or random…** at the foot of the list adds ONE menu card "
            "that boots one of several games, whether you pick it or the countdown does.",
            {"cards": [
                {"icon": "copy", "tone": "info", "title": "Over images on the card",
                 "text": "“Surprise me” beside the very builds it rolls between."},
                {"icon": "folder", "tone": "ok", "title": "Games of its own",
                 "text": "Picked as files, or a whole folder. Forty song sets of one "
                         "title look like one stock card."},
                {"icon": "sd", "tone": "", "title": "Base card + edits",
                 "text": "One stock card and a folder of song sets: the jukebox card. "
                         "See [below](#base-card-and-edits-folder)."}]},
            "### How it picks (Edit image…)",
            {"cards": [
                {"icon": "question", "tone": "info", "title": "Truly random",
                 "text": "Can give you the same one twice. A tick can rule out the "
                         "one it booted last."},
                {"icon": "refresh", "tone": "ok", "title": "Shuffle",
                 "text": "Plays every game before any repeats, remembered across "
                         "power-ups, like a music player. Never the last one twice."}]},
            "- **What it shows:** the games' logos fanned like a hand of cards, in a "
            "pile or a grid, a big ?, the shuffle symbol, each logo in turn, a slot "
            "reel, a picture of your own, or nothing. It has its own music and "
            "confirm sound.\n"
            "- **Select** under the preview shows what the machine draws once the "
            "roll lands: the chosen build, named.\n"
            "- Its **Games** box changes which games it holds (**Add files…**, "
            "**Add folder…**, or ticks for images already on the card). It always "
            "keeps at least two, and a change needs a rebuild.",
        ]),
        ("Base card and edits folder",
         "A song set does not need a whole 8 GB card. **Add base card + edits "
         "folder…** (under **Add image or random…**) takes the stock card plus a "
         "folder of only the files the set changes; everything else is read from "
         "the base.\n\n"
         "- **Add random group from edits folders…** takes one stock card and a "
         "folder of such sets.\n"
         "- Both check the pair first and say why they refuse one: a set edited "
         "from a different card, from another app version, half-built, or changed "
         "since.\n"
         "- Both lock **Compact build** on."),
        ("The tab, top to bottom",
         "One column that never rearranges itself:\n\n"
         "1. **The card path**, with **From SD card…**, **Browse…** and **New card**.\n"
         "2. **The preview**: the boot menu, drawn by the menu program itself.\n"
         "3. **The images table**, with four checks above it (Card image, Images, "
         "Built, Ready to flash). Hover one for the reason behind its mark.\n"
         "4. **The size strip**: the SD card size needed, **Compact build**, and a "
         "bar of what fills the card.\n"
         "5. **The action bar**: **Menu settings…** and **Recover images…** on the "
         "left; **Build / flash card…** (green) and **Run in emulator** on the right.\n\n"
         "Everything the tools print goes to the **Log** at the foot of the window."),
        ("The card path",
         "The path box is the card this tab works on.\n\n"
         "- **A card already there** can be read: pick it with **Browse…**, or type "
         "it and press Enter, and every field fills from it. You are then editing "
         "THAT card. Typing alone never reads a card.\n"
         "- **Nothing there yet** is where **Build / flash card…** writes a new one.\n"
         "- **From SD card…** reads the card in the reader, either the **boot menu "
         "only** (titles, pictures, sounds, settings; no game versions; a build "
         "then writes the menu back onto that card) or the **whole card** into a "
         ".raw you name, which then loads like any card on disk.\n"
         "- Pointing the box elsewhere throws nothing away; typing the path back "
         "picks the card up again. Only **New card** empties the tab.\n"
         "- The whole form comes back on the next launch, per project, but not in "
         "editing mode."),
        ("A card someone else built",
         "A multi-boot card you were given loads and draws its menu, but its "
         "images and media point at files on the PC that built it. The rows say "
         "“not on this machine”, and no update, rebuild or added image "
         "can run.\n\n"
         "**Recover images…** fixes that:\n\n"
         "1. Pick a folder. Each image is written there as a normal card image of "
         "its own, with the boot menu taken out.\n"
         "2. The card's pictures and sounds are copied out beside them.\n"
         "3. The rows point at those files, and the card now works like one you "
         "built.\n\n"
         "It only reads the card. It is grayed when every image is already on this "
         "PC, and for a card read as its menu only (read the whole card)."),
        ("The images table",
         "One row per image, in menu order, each with its own title, subtitle, "
         "picture, animation, music, confirm sound and game code version.\n\n"
         "- The dim **+** row at the end adds an image.\n"
         "- Each row's icons: **✎** opens it, **−** takes it off the card, **▲ ▼** "
         "move it. A double-click, Enter or a right-click works too.\n"
         "- The line under the table names the .raw the selected image came from.\n\n"
         "### Editing one image\n"
         "**✎** opens its title and subtitle, its music and confirm sound, and ONE "
         "list of what its card shows: the game's logo, a picture, the game's "
         "attract video, a video file, or nothing. A video's first frame is the "
         "still shown when the card is not highlighted. The right side of the "
         "dialog draws the card as the menu will."),
        ("Menu settings",
         "**Menu settings…** on the action bar holds everything that belongs to the "
         "whole menu rather than one image:\n\n"
         "- the heading, the lines under the cards, and one text size for every card\n"
         "- the move and confirm sounds (*auto* takes a click and a stinger from the "
         "primary image, *synth* makes tones) and the volume\n"
         "- the countdown (0 = wait for START) and which image is highlighted at "
         "power-up\n"
         "- the menu program's WSL path. Leave it empty and the app builds and "
         "installs it itself; a folder of your own is checked, never written into.\n\n"
         "### The menu's words\n"
         "| Line | What it says | Emptied |\n"
         "|---|---|---|\n"
         "| **Heading** | SELECT GAME CODE, or your own line | the top is left bare |\n"
         "| **Counter** (5+ cards) | < 3 / 7 > | tick it off for artwork cards |\n"
         "| **Instructions** | the menu's own button line | the menu keeps its own |\n"
         "| **Countdown says** | starting The Beatles in 9 s | just the game and seconds |\n\n"
         "- Your countdown word (Launching, Booting...) also replaces LOADING on "
         "the screen while the game starts.\n"
         "- The menu's own button line follows the buttons the machine has (an "
         "ACTION button is only mentioned where there is one). Words you type do not.\n"
         "- The preview shows every change as you type. A card that never asked for "
         "these is written exactly as before."),
        ("The SETTINGS card",
         "**End the menu with a SETTINGS card** (Menu settings; Stern, on by "
         "default) adds a gear card after the last image when an image's game has "
         "an adjustable color profile. A card built before this setting shows none "
         "until rebuilt.\n\n"
         "On the machine, **Settings > Color correction** tunes each game's color "
         "with no computer: Start from (As built, Recommended, No change, Black and "
         "white), brightness, contrast and saturation, then middle shades and color "
         "level per channel and darkest shades, with a test card corrected live. "
         "Then **Save for this "
         "game** or **Save for every game**.\n\n"
         "- The new values reach the game at its next start. The game files on the "
         "card are never written; on any failure the game runs as built.\n"
         "- No countdown runs inside Settings, and two idle minutes leave it "
         "without saving."),
        ("Editions: no menu",
         "**No menu: boot the edition the game's EDITION setting names** (Menu "
         "settings; Stern) is for a card whose images are all editions of one game, "
         "each written with the same edition names on its Write tab (Editions). "
         "Add them edition 1 first.\n\n"
         "On the machine there is no menu. The operator sets **EDITION** in the "
         "game's menu (Adjustments > Machine Settings > Attract Mode, or the last row of "
         "Standard Adjustments) and the edition it names boots "
         "at the next power-up. No setting yet means edition 1.\n\n"
         "- The build refuses an image without EDITION, another game or version, "
         "other edition names, or settings captioned differently: the editions "
         "share one settings store.\n"
         "- No random card and no image with its own high scores on such a card.\n"
         "- Untick it to give the card its menu back."),
        ("Settings, audits and high scores", [
            "A Stern Spike 2 machine keeps its settings, audits and high scores on "
            "the SD card, in the card's data partition, apart from the game "
            "program. A multi-boot card takes that partition from the **first "
            "image**.",
            {"cards": [
                {"icon": "sd", "tone": "ok", "title": "Keep what the machine has",
                 "text": "Read your current SD card into a .raw (**From SD card…**, "
                         "whole card) and make it the first image."},
                {"icon": "download", "tone": "warn", "title": "A fresh download",
                 "text": "Stern's image has none: the machine starts from factory "
                         "settings and runs its Guided Setup."}]},
            "- Every image of the same game shares them, across code versions, as a "
            "Stern update keeps them.\n"
            "- **Keep its own high scores on the machine** (✎ on an image) gives "
            "that image its own settings and audits too. Its first boot starts "
            "from a copy of the shared ones, so reset its high scores once in "
            "the service menu.\n"
            "- Flashing the whole card writes the image's copy over the machine's, "
            "unless you tick **Keep the SD card's settings, audits and high "
            "scores** in the flash dialog. When only the menu changed, **Only the "
            "boot menu** is quicker and keeps them too.",
        ]),
        ("Sounds",
         "Every sound row (the menu's move and confirm, an image's music and "
         "confirm) has a **▶ Play** beside **Browse…**, played through the "
         "preview's volume and Mute.\n\n"
         "- A WAV file plays straight off disk. A word (auto, synth, menu) plays "
         "what the last preview made for THAT row. If nothing plays, tick **Sound** "
         "under the preview to make it; the Log says why.\n"
         "- An image's confirm sound plays **when you press START** on it. "
         "Scrolling plays the menu's move click instead.\n"
         "- An image's confirm falls back to the menu's. Edit image names the "
         "sound that image will really play; Menu settings names the images that "
         "have their own.\n"
         "- Every sound list also offers the WAVs this menu already uses, so one "
         "clip on every image is a pick, not a Browse each time. Only files on "
         "this PC are offered."),
        ("The preview",
         "The preview redraws itself about a third of a second after any change, "
         "using the same media the build will put on the card. Selecting a row "
         "shows that image highlighted.\n\n"
         "- **The flipper buttons** under it (or the arrow keys, once clicked) move "
         "the highlight and wrap at the ends, as on the machine.\n"
         "- **Frame** steps through the highlighted image's animation; **Play** runs it.\n"
         "- **Sound** (off at first) plays the image's music loop and the move "
         "sound, at the Menu settings volume. Ticking it also makes the move and "
         "confirm sounds, which arrive when that run finishes.\n"
         "- Right-click the picture to hear the highlighted image's confirm sound.\n\n"
         "> The very first preview on a new PC takes a few minutes: the menu program "
         "is built once, from a card. The Log says so while it runs."),
        ("Bypass game validation",
         "Always on for every image; there is no box. A modified image would fail "
         "the machine's check (GAME VALIDATION ERROR), and one image's failure "
         "would latch onto the next, since the images share one saved grade.\n\n"
         "- Every image has its validator switched off and its saved grades "
         "ignored at boot (proven on a TMNT).\n"
         "- A card already built is repaired by **Apply / Update**, with no "
         "rebuild, and read back to confirm."),
        ("Build / flash card…", [
            "One green button, and a dialog that says what it will do before it "
            "does it.",
            {"cards": [
                {"icon": "plus", "tone": "info", "title": "New path: build",
                 "text": "Every image copied in, the menu added, and everything "
                         "checked afterwards."},
                {"icon": "refresh", "tone": "ok", "title": "Loaded card: update",
                 "text": "A changed title, picture or setting: seconds. A changed "
                         "image: only the changed files, about a minute."},
                {"icon": "sd", "tone": "warn", "title": "Flash to an SD card",
                 "text": "Writes the finished card in the same run. You pick the "
                         "SD card next."}]},
            "- Adding, removing or reordering images on a card built the older way "
            "needs a fresh card; the dialog says so.\n"
            "- Reading the card again throws unapplied edits away.\n"
            "- **Only the boot menu** starts ticked only for a card this app has "
            "already flashed. Otherwise the whole card is written, which a new SD "
            "card needs. Tick it yourself if your SD card already holds that "
            "image; it checks first.\n"
            "- **Keep the SD card's settings, audits and high scores** writes the "
            "whole card but puts the machine's own back on it.\n"
            "- Every run first makes sure the menu program is built, before any "
            "media. If a step refuses, the tab shows the Log line, naming the step.",
            {"note": "Nothing is written to an SD card until you pick it in the "
                     "SD-card picker and confirm. Windows asks for administrator "
                     "access for that write.", "kind": "warn"},
        ]),
        ("Size strip and Compact build", [
            "The strip under the table names the Stern SD card size the images "
            "need before anything is written, and re-checks whenever the list "
            "changes. Click it to measure again.",
            "- The size is tried through the real builder, so it is the size the "
            "build will use.\n"
            "- When the card must be bigger than the games, it adds it up: 10.83 GB "
            "of games + 6.21 GB free for updates = 17.65 GB, so 32 GB, not 16 GB. "
            "The free room lets an image be updated in place instead of rebuilt.\n"
            "- When no size fits, it shows the reason (which part ran out, by how "
            "much); the whole sentence is on the tooltip.\n"
            "- **Compact build** (off by default) stores files the images share only "
            "once: three images of one title that needed 32 GB fit 16 GB. The bar "
            "hatches the saving. The first tick reads every image once, with a "
            "percentage.",
            {"note": "Change a compact card only with this app, never with a Stern "
                     "USB update: that would write through the shared files into "
                     "every image at once.", "kind": "warn"},
        ]),
        ("Run in emulator",
         "**Run in emulator** opens the finished card on the Emulate tab with "
         "**Boot selector** ticked, so the same menu appears in the game window "
         "and each image runs as on the machine. It runs under WSL and logs to the "
         "Log, tagged [multi-boot]."),
        ("Building on a Mac",
         "A Mac builds these cards with **Docker Desktop**, since the tools are "
         "Linux tools.\n\n"
         "- The first card you write builds a Linux container, reused after that. "
         "On Apple silicon it runs emulated, so that first time takes a few minutes.\n"
         "- No password is asked for.\n"
         "- Without Docker Desktop, or with it not running, the Log says which and "
         "nothing is written. Reading a card, the preview and the size strip work "
         "without it.\n"
         "- If a step fails, the Log has the container's own output: send that on."),
        ("Jersey Jack (install stick or SSD)", [
            "Pick **Jersey Jack** and the tab takes two JJP install ISOs of the same "
            "game code (stock and a retheme, say) instead of card images.",
            {"flow": [
                {"icon": "disk", "title": "Two ISOs", "text": "same game version"},
                {"icon": "write", "title": "Build / make stick…",
                 "text": "one multi-boot install ISO, onto a USB stick"},
                {"icon": "multiboot", "title": "Install",
                 "text": "like any JJP stick, purple security key in"}]},
            "- Use a USB port on the computer in the backbox.\n"
            "- At power-up: flippers choose, START or **Action** boots, the volume "
            "buttons set the menu's level. A maintenance reboot boots the same image "
            "again without the menu.\n"
            "- The dialog's **Onto:** row can install straight onto the game's SSD "
            "in a dock. Its **Write:** choice can then replace only the boot menu, "
            "or only one image (from its own ISO), keeping settings and scores.\n"
            "- No random cards and no Compact build: it holds exactly two images.",
            {"note": "Both images must be the same game version, because they share "
                     "one settings partition. The build refuses a mismatch and says "
                     "why.", "kind": "warn"},
        ]),
        ("Barrels of Fun (one update file)", [
            "Pick **Barrels of Fun** and the tab takes a game's stock .fun plus up "
            "to three more builds (a mod, say). **Build update…** writes ONE .fun "
            "under the game's own name (lab.fun for Labyrinth).",
            {"flow": [
                {"icon": "file", "title": "Build update…", "text": "one .fun"},
                {"icon": "upload", "title": "FAT32 USB stick",
                 "text": "install it like any update"},
                {"icon": "multiboot", "title": "Next power-up",
                 "text": "the menu shows before the game"}]},
            "- Flippers choose, START or LAUNCH boots, and the countdown boots the "
            "build chosen last.\n"
            "- Each build after the first is stored as its difference from the "
            "first, to stay under FAT32's 4 GB file limit. The size strip says when "
            "it does not fit.\n"
            "- Each card can show a picture or a video clip, play music and the move "
            "and confirm sounds, and a random card can boot one of the builds above "
            "it (**Add random over the images above**).\n"
            "- *auto* picture, clip and music are each build's own (a mod's changed "
            "attract or intro shows); *auto* sounds are the game's menu click and "
            "clock bell.\n"
            "- All builds share one set of settings and scores.\n\n"
            "| Game | Supported |\n"
            "|---|---|\n"
            "| Labyrinth | Yes |\n"
            "| Dune | not yet (it updates differently) |\n"
            "| Winchester | not yet (it updates differently) |",
            {"note": "Installing any normal update afterwards takes the menu away "
                     "again.", "kind": "warn"},
        ]),
    ],
}

# The Image Info WINDOW (the "Info" button beside the Extract / Write image
# pickers) — not a notebook tab, so it lives outside the per-tab dict and is
# appended to the tabs its launch buttons sit on (see _CONTENT_EXTRAS).
_IMAGE_INFO_SECTIONS = [
    ("The ⓘ button",
     "The **ⓘ** beside the image picker opens a read-only window on that image: file, "
     "detected game and format, firmware, on-card asset counts and partitions. Good "
     "for telling firmware versions apart; **Copy Report** is for bug reports. For the "
     "card picked on Select card it takes you there instead, where the same details "
     "sit."),
    ("Where its details come from",
     "Only from the image and its file name (or, for a card in a reader, the card).\n\n"
     "- **Version** (Stern) is read from the card's update index, so renaming the file "
     "can't change it. If the name disagrees, both show and the card wins.\n"
     "- **Version ID** (like VEN106LE) is built from the title code in the firmware.\n"
     "- All counts are read off the card, no Extract needed.\n\n"
     "| Count | What it is |\n"
     "|---|---|\n"
     "| Sounds | What an Extract decodes to WAVs |\n"
     "| Sound fragments | The bigger pool of audio pieces sounds are built from |\n"
     "| Sound requests | The sound calls the game code can make (left out if "
     "unreadable) |"),
    ("Adjustments and high scores",
     "**Adjustments** is how many operator settings the firmware has; **High scores** "
     "how many places its board keeps (top four, Grand Champion, every champion). The "
     "machine's current settings and scores live in the card's data partition, not in "
     "the game program; "
     "the Defaults tab sets what a freshly flashed machine starts from."),
]

# Non-tab help appended to the tabs whose UI hosts the feature.
_CONTENT_EXTRAS = {
    "Extract": _IMAGE_INFO_SECTIONS,
    "Write": _IMAGE_INFO_SECTIONS,
}
for _tab, _extra in _CONTENT_EXTRAS.items():
    HELP_CONTENT[_tab] = list(HELP_CONTENT[_tab]) + list(_extra)

# The Scenes tab's own tips (PAD-388: its ? window was empty): the scene sections
# the Replace tabs and Color Profile already carry, in the order the tab is used.
HELP_CONTENT["Scenes"] = [
    sec for _tab, _title in (("Replace Images", "Scenes tab"),
                             ("Replace Video", "Scene editor"),
                             ("Replace Images", "Text in a scene"),
                             ("Color Profile", "Preview colors (Scenes)"),
                             ("Replace Video", "Save and load scene edits"))
    for sec in HELP_CONTENT[_tab] if sec[0] == _title]

# Tips only a copy of the app with a PREVIEW FEATURE switched on shows
# (core/preview.py): {feature id: {tab: [(title, body), ...]}}.  Without a
# code none of this is rendered, so the "?" window of a copy without one
# describes the app that copy is (sections_for).  A body may be a function
# returning the text: it is read when the window renders, so a tip that
# lists what the app has right now (the ports) is never a release behind.


#: The "Which games" table's columns (PAD-380): what differs from one build to the next.
MODES_GAMES_HEAD = ("Game", "Screen, clip, sounds", "Countdown", "Ball save", "Lights", "Also")


def modes_games_rows(ports=None):
    """One row per port, in MODES_GAMES_HEAD's order: the "?" window's "Which games" table, and
    the one in MODE_LIMITS.md (a test keeps them equal)."""
    from ..plugins.stern import mode_assets as MA
    from ..plugins.stern import mode_project as MP
    if ports is None:
        ports = MP.profiles().values()
    rows = []
    for p in sorted(ports, key=lambda p: p.label):
        yes = "✓"
        media = yes if all(p.can(k) for k in ("screen", "clip", "own_sound")) else "no"
        if not p.can("lights"):
            lights = "no"
        else:
            lights = "all" if p.lamps == 0 else "shots"
        also = []
        if p.can("screen") and (p.lcd("hud") or "").endswith(MA.HUD_SCENE):
            also.append("HUD")
        if any("button" in n.lower() for n, _m in p.shots):
            also.append("buttons")
        also += [w for k, w in (("magnet", "magnet"), ("scoop", "scoop"), ("coils", "mechanisms"),
                                ("shield", "shield"), ("building", "building"), ("shaker", "shaker"),
                                ("shows", "light shows"), ("wizard", "mini-wizards"), ("roster", "battle slot"),
                                ("challenge", "challenges"), ("place", "game mode places"),
                                ("done", "starts on game modes completed"))
                 if p.can(k)]                     # PAD-381: what a mode may hold; PAD-392; PAD-615; PAD-710; PAD-747
        if p.stack_note and p.can("stack"):
            also.append("waits for multiballs only")
        if not p.can("stack"):
            also.append("never waits")
        if not p.can("events"):
            also.append("no events")
        if not p.proven:
            also.append("never run")
        rows.append((p.label, media, yes if p.can("countdown") else "no",
                     yes if p.can("ball_save") else "no", lights, ", ".join(also)))   # PAD-589: no "not yet"
    return rows


def _modes_which_games():
    """The Modes tab's "Which games" tip, read off the ports when the window
    renders: a line, then a table of every port (PAD-380: the list was a wall of
    names).  Never raises (the "?" window is not the place for a traceback)."""
    try:
        rows = modes_games_rows()
    except Exception:                                   # noqa: BLE001
        rows = []
    if not rows:
        return ("No game list could be read in this copy of the app. The tab "
                "says whether it can make modes for your card.")
    lead = ("Every build below has played modes in the emulator. "
            if all("never run" not in r[-1] for r in rows) else
            "Every build below but those marked \"never run\" has played modes in the emulator. ")
    return {"text": lead + "Shots, scoring, timers, multiball and holding off the game's "
                           "modes work on all of them; the columns are what differs.",
            "table": {"head": list(MODES_GAMES_HEAD), "rows": [list(r) for r in rows]},
            "after": "- **Countdown no:** the game's voice never says a number on its own.\n"
                     "- **Lights:** *shots* lights just the scoring shots' inserts; *all* "
                     "holds every insert in the mode's color.\n"
                     "- **HUD:** counters, a timer and a gauge at the screen's edges.\n"
                     "- **Buttons:** the flipper and Action buttons count as shots.\n"
                     "- **Magnet, scoop, mechanisms:** what a mode may hold for a moment: the "
                     "magnet, a ball in the scoop, the Mechagodzilla magnet and the bridge.\n"
                     "- **Shield:** a mode may turn the shield targets toward the player while it runs.\n"
                     "- **Building:** a mode may move the building to one of the game's own floors.\n"
                     "- **Shaker:** a mode may shake the cabinet (when the machine has a shaker fitted).\n"
                     "- **Battle slot:** a mode may take one of the game's battles' places on its selection "
                     "screen.\n"
                     "- **Light shows:** the game's own light shows, which a mode can play as it "
                     "starts or ends.\n"
                     "- **Your own light shows:** the Light shows view draws the mode's own named "
                     "shows step by step (spirals, ripples, bounces, fades and more), previewed on "
                     "the playfield picture, for the mode's blocks to run. Most inserts on most "
                     "games are single-color: a show only sets how bright they are, and each glows "
                     "in its own color. **Real LEDs** previews that (give each insert its color "
                     "under Insert colors; white = not set); **All RGB** paints every insert in the "
                     "show's colors.\n"
                     "- **Never waits:** a mode can't be set to wait for the game's modes.\n\n"
                     "> **Not listed?** Pick the card anyway: the app works out its hooks. "
                     "Press Check this game (about two minutes) before trusting them. "
                     "MODE_SDK.md, \"Making a port for another game or version\", covers the rest."}


def _limits(heading):
    """A part of MODE_LIMITS.md, the Mode SDK's "What a mode can and can't do", read
    when the window renders (PAD-386: the tab opens it HERE, never in another app).
    The file stays the one copy of those words; its tests keep its sizes the
    editor's and its games the ports'."""
    def read():
        from ..plugins.stern import mode_runtime as MR
        from .tips_render import md_part
        return md_part(os.path.join(MR.sdk_dir(), "MODE_LIMITS.md"), heading)
    return read


#: The Modes tips' section "What a mode can and can't do" opens on (PAD-386)
MODES_LIMITS_TITLE = "What a mode can and can't do"


PREVIEW_HELP = {
    "modes": {
        "Modes": [
            ("What it's for", [
                "Make a game mode of your own. A mode is a small file the running "
                "game reads, so it plays like one the game shipped with: it scores "
                "through the game's own scoring and plays through its own light and "
                "sound calls.",
                {"flow": [
                    {"icon": "flag", "title": "Starts",
                     "text": "on a shot made a few times, a run of shots, an event, or after another mode"},
                    {"icon": "modes", "title": "Runs",
                     "text": "on its own clock; the shots you pick score what you set"},
                    {"icon": "film", "title": "Shows",
                     "text": "its own screen, clips, sounds, music and lights"},
                    {"icon": "stop", "title": "Ends",
                     "text": "when time is up, on a shot, or on a drain"}]},
            ]),
            (MODES_LIMITS_TITLE, [
                "Stern's own modes are compiled into the game program, and the app "
                "doesn't rewrite that code. Your mode runs beside it, through hooks "
                "the app knows for each build.",
                {"cards": [
                    {"icon": "check", "tone": "ok", "title": "Your modes",
                     "text": "**Wide open.** Start, shots, scoring, screen, clips, sounds, music, lights."},
                    {"icon": "defaults", "tone": "warn", "title": "The game's modes",
                     "text": "**Numbers only.** Timers and awards, not how they play."},
                    {"icon": "lock", "tone": "err", "title": "Everything else",
                     "text": "**Off limits.** Progression, settings, high scores, Insider Connected, and the game's coils but the mechanisms a mode may hold. Spare switches and outputs you add are yours."}]},
                _limits("Quick answers"),
            ]),
            ("Which games", _modes_which_games),
            ("Making a mode", [
                "**New mode**, over the list, asks how you want to build it, with a "
                "tile for each way that says what it asks of you and what it can do:\n\n"
                "- **Blocks** (recommended): rules snapped together, no code.\n"
                "- **C** (best with an AI agent): the Mode SDK, for anything a mode can do.\n"
                "- **Form** (a playground): boxes to fill in, nothing more.\n\n"
                "A project with no mode yet shows the same tiles on the page. The Form "
                "makes a blank mode or one from the example, TARGET RUSH, on the card's own "
                "shots. For a form mode, then:\n\n"
                "1. **Name it.**\n"
                "2. **Starts on:** the shot that starts it and how many times (up to "
                "999); the two *or* lists add up to two more shots whose hits count "
                "together with it. It can also ask for up to three more shots in the same ball, in any order or "
                "in order (any other shot starts the sequence over). *Only after* "
                "holds it until another mode has run this ball or game. On Godzilla it can "
                "instead start when the player picks one of the game's battles on the battle "
                "selection screen: your mode runs in that battle's place. Or it can start once the player "
                "has completed a number of the game's own modes in one game (tick which ones count): a "
                "mini-wizard after four of them, a bigger wizard after all of them.\n"
                "3. **Runs for:** how long it runs.\n"
                "4. **Points per shot:** which shots score and what the first one "
                "pays. A minus number takes that much away on each hit.\n"
                "5. **Ends on** (if you like): a pick of shots, or any shot that "
                "does not score, ends it sooner.\n\n"
                "### Everything else is optional\n"
                "- **Screen:** a panel in your colors or a picture of your own, "
                "showing what each shot paid and the total.\n"
                "- **Clip:** a title card or a video of your own, full screen when "
                "the mode starts or ends.\n"
                "- **Sound:** the countdown, the sound when time is up, and sounds of "
                "its own when it starts, on a scoring shot and underneath.\n"
                "- **Lights:** a color sweep, or the scoring shots lit on the playfield.\n"
                "- **Rules:** how often it can start, whether it runs during the "
                "game's own modes, and an event that starts or ends it.",
                {"note": "Every change saves itself in the project's modes folder about "
                         "half a second after you stop typing. The line at the bottom of "
                         "the form says whether the mode can be built, and a section this "
                         "game can't do is grayed, with the reason."},
            ]),
            ("Try it", [
                "**Try it** builds this project's modes exactly as Write puts them on "
                "a card, then starts the card in the Emulate tab with them.",
                {"flow": [
                    {"icon": "write", "title": "Build", "text": "your modes, as Write would"},
                    {"icon": "emulate", "title": "Run", "text": "the card, on the Emulate tab"},
                    {"icon": "play", "title": "Play",
                     "text": "a mode starts on its shots, or at once with Start mode now"}]},
                "- The button reads **Cancel** while it works, and the line under it "
                "says what is happening. Cancel, here or on the Emulate tab, stops the build.\n"
                "- A mode's own sound is the slow part: about a minute the first time "
                "it changes, reused after that. A set nothing changed since the last "
                "Try it is used as it is.\n"
                "- **End mode** ends whichever of this project's modes is running. The "
                "run is the Emulate tab's, and its Stop stops it.\n"
                "- An edit made while the game runs reaches it within a second; a screen "
                "turned on or off, a new sound or a new clip reaches it at the next Try it.\n"
                "- A refusal is shown beside Try it and on the Emulate tab, with the reason.",
            ]),
            ("Several modes",
             "- A card holds as many modes as you make. The count is under the tab's name, with "
             "modes made of blocks and modes written in C counted apart.\n"
             "- **One runs at a time.** A mode whose shots come up while another is "
             "running does not start then, but its next starting shot after that one "
             "ends starts it.\n"
             "- A card carries one end sound of a mode's own: the first mode that has "
             "one. The Sound section says whose."),
            ("Modes made of blocks", [
                "**New mode > Blocks** makes a small working mode on this card's "
                "shots, built from blocks instead of the form or C.",
                {"cards": [
                    {"icon": "flag", "tone": "info", "title": "When",
                     "text": "Starts each script: the mode starts or ends, a shot is made, "
                             "any shot, every few seconds, some seconds left, the ball "
                             "drains, one of the game's events."},
                    {"icon": "list", "tone": "ok", "title": "Do",
                     "text": "Runs under it, top to bottom: score, a variable, If and If "
                             "... else, a callout, words on screen, light a shot, add "
                             "time, a multiball, a log line, start or end the mode."},
                    {"icon": "blocks", "tone": "warn", "title": "Values",
                     "text": "Snap into a block's slots and nest: hits of a shot this "
                             "ball, points so far, seconds left, sums, compare, and, or, not."}]},
                "- Drag a block from the left into a script, or press it to add it to "
                "the script picked last. A stack's own + adds one too.\n"
                "- A variable holds a number for each player, and goes back to 0 each "
                "ball, each time the mode starts, or each game.\n"
                "- Every change saves itself; the line at the top says what is left to fix.\n"
                "- **Blocks**, **Rule cards**, **Story**, **Playfield**, **Shot table**, "
                "**Timeline**, **Node graph** and **Script** are views of the same mode: "
                "switch between them at any time, and nothing is converted. **Undo** takes "
                "back a change made in any of them.\n"
                "- **Rule cards** write each rule as When … Then, with a choice in every "
                "blank. **Story** shows the mode's life: what it does while it waits, what "
                "starts it, what it does while it runs and what ends it; drag a shot's rule "
                "to another box to change when it works.\n"
                "- **Playfield** is the game's own playfield, read from your card, with the "
                "shots the mode lights in their colors. Press a shot to see and change what "
                "it does. The ◎ beside any shot's list opens the same picture, to pick the "
                "shot on it.\n"
                "- **Shot table** has a row for every shot, so the ones that do nothing yet "
                "show. **Timeline** lays the mode's clock out left to right, and **Node "
                "graph** wires every rule to the variables and timers it shares.\n"
                "- **Script** is the same mode as text, to type: what you type becomes the "
                "blocks as soon as it reads, and a mistake is marked on its line until it "
                "is put right. It is read, never run.",
                {"note": "The app turns the blocks into a mode in C, which Try it and "
                         "Write build like any other. **C it makes** shows it, and "
                         "**Edit as C (one way)…** keeps that C and puts the blocks away, for "
                         "carrying on in C. It is a one-way step: C can't be turned back "
                         "into blocks, so press **Duplicate** first to keep a blocks copy."},
            ]),
            ("Modes written in C", [
                "For what the form can't do.\n\n"
                "- **New mode > C**, named, copies the Mode SDK's template into this "
                "project's modes folder and opens it. **Make it and copy for an agent** "
                "does the same, then copies what to tell an AI agent: the mode's file, "
                "the SDK's guide to read first, and what you said the mode should do. "
                "**Open MODE_SDK.md** opens the SDK's guide.\n"
                "- The folder's name is the mode's trigger name (its test triggers are "
                "*folder*.start and .stop), so keep it to letters, digits and _.\n"
                "- An **assets.json** beside the code names a clip, a picture, music "
                "and calls of the mode's own, and Try it and Write compile the mode in "
                "with them. The Code modes line lists each one.\n"
                "- **Start mode now** starts the open code mode through its .start "
                "trigger, once a Try it has built it into the running game.\n"
                "- The Code page edits the C in the app, its words colored and its lines "
                "numbered: **Save** (or Ctrl+S) writes it. **Open … in my editor** opens it "
                "in your computer's editor instead; **Read again** picks up a change made "
                "there.",
            ]),
            ("The game's own modes",
             "They are listed under yours. Pick one to see its page.\n\n"
             "- **Timers and awards:** type a new value and press Set. Stock puts that "
             "number back to the game's own.\n"
             "- **Shots:** on a game whose port allows it, a shot that counts as one of "
             "its own, or one that takes its place (**instead of**: the mode's own shot "
             "no longer counts, and its light moves to yours), and a rewrite of its shots "
             "in C.\n"
             "- **All timers and awards…**, under the list, shows every number in one "
             "table, and **All to stock** there puts every one back.\n"
             "- A timer that is an operator setting is the same number the Defaults tab "
             "shows. A number the game works out in code can't be changed here: the row "
             "says why.\n"
             "- Changes are saved with the project and put on the card by Write. A "
             "mode's name is changed on the Text tab."),
            ("Cut from a video", [
                "The **Cut from a video** buttons cut this mode's clip, its sound or its "
                "screen's picture from a video file of your own: a film, an episode, anything.",
                {"flow": [
                    {"icon": "film", "title": "Pick", "text": "a video file"},
                    {"icon": "edit", "title": "Trim", "text": "a start time and up to 30 seconds"},
                    {"icon": "fit", "title": "Frame", "text": "keep its letterbox, or fill the frame"}]},
                "The mode keeps only the cut (clip.mp4, end.wav, art.png), never the "
                "video. A title that can't use a clip, a picture or a sound of the "
                "mode's own grays that button, with the reason.",
            ]),
            ("Copy and share",
             "- **Copy to…**, under the list, copies every mode here into another "
             "card's project: pick that project's folder. Each mode goes with its "
             "picture, clip and sounds, and is matched to that card's shots by name.\n"
             "- A mode that loses nothing builds there as it is. One that names a shot "
             "the card lacks is copied as it was: open it there and pick its shots.\n"
             "- Another version of the same game, or its Pro beside the Premium, keeps "
             "every sound number. Another game keeps only the callouts the app "
             "measured on both.\n"
             "- **Port to Pro** (or **Port to Premium/LE**) shows on a game made in "
             "more than one model. It takes every mode here to a project of the other "
             "model in one click: a shot with another name there goes to the shot on "
             "the same switches, and a mechanism that model does not have (the "
             "Premium's bridge) is left out. Each mode keeps its shots and "
             "mechanisms for every model it has been on, so porting back gives them "
             "back. Porting again replaces the earlier port and keeps what you set "
             "for that model there. A mode opened, built or loaded on the other "
             "model's card is matched the same way.\n"
             "- **Save / load** saves the open mode, or every mode, to one .zip holding "
             "each mode's whole folder (picture, clip, sounds and code), to share or "
             "keep. Loading one adds its modes as Copy to… would. A mode already here "
             "exactly as in the file is left as it is. One of the same folder name with "
             "other contents is asked about: **Cancel**, **Keep both** (the file's gets "
             "_2), **Skip conflicts**, **Replace all**, or tick the ones to replace. "
             "Before any is replaced, every mode here is saved to a file in the "
             "project's **Backups** folder (untick that to skip it).\n"
             "- **Load modes from a card image…** takes the modes straight off a card "
             "the app wrote modes onto: another version, model or custom image of this "
             "game too, matched here as a loaded file is. Every card Write builds "
             "carries its project's modes for this (the pictures, clips and sounds "
             "only while they are small; the message names any left behind). A card "
             "built on this PC loads from the project it was built from, whole. An "
             "older card gives back what it holds, and says what did not come back. "
             "**Save a card image's modes to a file…** makes the same .zip without "
             "loading it."),
            ("The rules sheet",
             "**Rules sheet…**, under the list, makes the printable sheet for the cabinet "
             "from the mode files, so it is never out of date: one row per mode (its name "
             "as the game shows it, how it starts with what the 1st / 2nd / 3rd start "
             "take, its stages a line each, and whether it cashes out), the rules every "
             "mode shares under it, and the game and version from the project above it. "
             "A mode made of blocks is played through by the app to word it; a form mode "
             "says its fields; a mode in C says its clock, and the rest is yours to write. "
             "Click a mode to put your own words in any field: yours win, and an empty "
             "field gives the app's back. Untick a mode to leave it off, and move it up "
             "or down. **Save as PDF…** lays it out on one Letter or A4 page when it "
             "fits; **Save as HTML…** saves the same sheet as a web page; **Print…** "
             "prints it, on the paper chosen beside it."),
            ("Five things people ask for", _limits("Examples")),
            ("Why your mode always gives way", _limits("Why your mode always gives way")),
            ("Sizes", _limits("Sizes")),
            ("Before you flash a real machine", [
                {"note": _limits("Before you flash a real machine"), "kind": "warn"},
                "### Scores and Insider Connected\n"
                "A mode scores through the game's own scoring, so its points are not "
                "the game's stock scoring. With modes on the card, players still log in "
                "to Insider Connected and see its message of the day, but the machine "
                "sends it no game, no scores, no high scores and no achievements: the "
                "mode runtime holds those reports back, and the game logs each as a "
                "failed message and plays on. The game is not given the list of "
                "Insider achievements either, so it awards none on the machine.\n\n"
                "The page says so under the title. A title whose port cannot do this "
                "(one worked out before the gate existed) cannot carry modes until its "
                "port is worked out again.",
            ]),
            ("Asking for more", [
                _limits("Asking for more"),
            ]),
        ],
    },
    # PAD-802: the Visual Pinball tab
    "vpx": {
        "Visual Pinball": [
            ("What it's for",
             "Play a Visual Pinball table with the real Stern game behind it. The game "
             "from your own card image runs in the emulator; the table is its playfield. "
             "The game serves the balls, fires the flippers, slings and pops, lights the "
             "table, keeps score, plays its sounds and shows its own screen in a window "
             "of its own."),
            ("Getting started", [
                {"flow": [
                    {"icon": "check", "title": "Setup",
                     "text": "the PAD runtime, Visual Pinball, the controller: each row installs its own"},
                    {"icon": "sd", "title": "Cards",
                     "text": "the folder with your SD card images"},
                    {"icon": "upload", "title": "Patch",
                     "text": "the table you downloaded from its author"},
                    {"icon": "play", "title": "Play",
                     "text": "the game boots by itself, within a minute"}]},
                "- The app ships no tables. The Tables list names each one it knows and "
                "who made it; download it from there.\n"
                "- **Patch a table...** writes a copy named \"(PAD)\" into Visual "
                "Pinball's tables folder. Your download stays as it was.\n"
                "- A backglass (.directb2s) named like the table, beside it or already in "
                "the tables folder, is copied to match the \"(PAD)\" name.\n"
                "- A title plays the newest build of its card in the card folder.\n"
                "- **Windows** sets where Visual Pinball's playfield and the game's screen "
                "go when a table opens. You can drag the game's screen anywhere after that.",
            ]),
            ("Playing",
             "| Key | Does |\n"
             "|---|---|\n"
             "| 1 | Start |\n"
             "| 5 | coin (add coins until the game's screen shows a credit) |\n"
             "| Left and right Shift | flippers |\n"
             "| Left Alt | launch on Rush and Foo Fighters (Visual Pinball's lockbar key) |\n"
             "| Enter | launch on Godzilla |\n"
             "| Esc | leave; the game stops with the table |\n\n"
             "The first time, the game's screen may take the keyboard: click the "
             "playfield once and play on."),
            ("If it does not start",
             "- **Check again** says what is missing.\n"
             "- \"WSL is not installed on this PC\": the emulator runs in WSL. Click "
             "**Install Missing** above the tabs, restart Windows when it asks, then Play.\n"
             "- \"no rig slot free\": a game is already running, on the Emulate tab or "
             "from a table closed without Esc. Stop it on the Emulate tab.\n"
             "- The table loads and nothing happens: `%TEMP%\\padcontroller.log` says what "
             "the controller did, and `%TEMP%\\padvpx-<title>.log` is the game's boot log."),
        ],
    },
}


def sections_for(tab_name):
    """The (title, body) sections the "?" window shows for *tab_name*: the
    tab's own, plus those of every preview feature switched on in this run
    (:data:`PREVIEW_HELP`).  Never raises."""
    out = list(HELP_CONTENT.get(tab_name) or [])
    try:
        from ..core import preview
        for feature, tabs in PREVIEW_HELP.items():
            if preview.enabled(feature):
                out += list(tabs.get(tab_name) or [])
    except Exception:                                   # noqa: BLE001
        pass
    # a body that is a function is read now, at render time (a tip that lists
    # what the app has at the moment); one that fails is left out, not a crash
    sections = []
    for title, body in out:
        if callable(body):
            try:
                body = body()
            except Exception:                           # noqa: BLE001
                body = ""
        if body:
            sections.append((title, body))
    return sections

# Appended to every tab's sections — app-wide behaviours users ask about.
GENERAL_CONTENT = [
    ("The ⚙ settings menu",
     "The gear at the top right holds the app-wide controls:\n\n"
     "- light / dark theme\n"
     "- **Check for updates**, and **Check automatically**: at startup only, hourly, "
     "every 6 hours or daily\n"
     "- **Save automatically**: every 1, 5 (the default), 15 or 30 minutes, or never. "
     "Changes to files are saved the moment you make them; this saves the rest of "
     "the project (the Multi-boot list, the Emulate card, the Extract options, the "
     "Write file name), which otherwise waits until PAD closes\n"
     "- disk-space management, and clearing the downloaded voice models\n"
     "- the prerequisite tools: status, re-check, install\n"
     "- **View disclaimer…**, the first-launch disclaimer again"),
    ("Prerequisites",
     "Each manufacturer needs a few tools. While any is being checked or missing, "
     "a strip under the title lists them:\n\n"
     "| Mark | Means |\n"
     "|---|---|\n"
     "| [?] | still checking |\n"
     "| [✗] | missing: **Install Missing** sets it up |\n"
     "| [✓] | ready |\n\n"
     "Once all are ready the strip hides; the ⚙ menu keeps the status and its "
     "**Install / repair prerequisites…** entry. All green means every check passed, not "
     "that nothing is left: ffplay (for the audio Preview) is checked by none, and "
     "re-running the installer brings the full ffmpeg that has it."),
    ("Reset… (start a project over)",
     "**Reset…** at the bottom of the project menu (the project name at the top) puts parts of the project back the way "
     "they were extracted. Tick what goes, or **Everything**:\n\n"
     "- **Scenes edits**: every scene as shipped, and the score panel's colors\n"
     "- **Color profiles**: the project's and every file's or line's own, switches off\n"
     "- **Replaced images**, **Replaced videos**, **Replaced sounds**: the picks and "
     "the files they changed\n"
     "- **Text edits** and the text colors picked on Text\n"
     "- **Fonts**: every letter back from the game's own font pictures\n"
     "- **Modes**: every mode made in the project (its folder under modes) and every "
     "change to the game's own modes\n\n"
     "It cannot be undone, and works on the whole project only: one scene goes back "
     "with **Revert** on the Scenes tab. Your own files picked from elsewhere stay "
     "where they are; nothing on a card changes until the next Write."),
    ("Recent paths",
     "Every file or folder box remembers recent paths per manufacturer: open its "
     "dropdown to reuse one."),
    ("Change history",
     "Every pick (and the file it replaced), text edit, staged default, build and "
     "revert is logged with date and time in **.history.log** at the top of the "
     "project folder. So a slot that says \"changed on disk\" still shows, months "
     "later, what it was changed with. Open it from **Project ▾ > Change history…**; "
     "it is plain text."),
    ("Moved to another PC?",
     "A project records WHERE each replacement came from, not a copy. Move the "
     "project or your media to another drive and the Replace tabs come up empty.\n\n"
     "1. **Project ▾ > Relink moved files…** lists the files it can't reach.\n"
     "2. Give it one folder to look in.\n"
     "3. Press **Relink**: every slot is re-pointed at once, matched by file name, "
     "so a new drive letter or a re-sorted library still works.\n\n"
     "Nothing is copied, and nothing is written until you press Relink."),
    ("The log",
     "The progress dots and log at the bottom follow every job. Right-click the log "
     "to copy text for a bug report."),
]
