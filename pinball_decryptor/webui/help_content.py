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
        ("Pick the card",
         "Browse… to a dumped card image / update file. Plugins with "
         "direct-media support also offer a \"From SD "
         "card / SSD\" mode that reads the physical media in a reader "
         "(needs Administrator on Windows). The Extract tab reads the card "
         "picked here."),
        ("Is it the right card?",
         "Once a Stern Spike 2 card is picked, the page shows what the "
         "machine puts on the screen while it starts: the game's own "
         "loading screen, or, on a multi-boot card, its boot menu with the "
         "default game highlighted. The menu is drawn by the same tools the "
         "Multi-boot tab uses and takes a few seconds the first time; a card "
         "in a reader shows the first game's loading screen instead. Under "
         "it, Card details lists everything the app can read off the card "
         "(firmware version, edition, games on it, asset counts, "
         "partitions), with Copy for a bug report. Nothing on the card is "
         "changed."),
        ("What works without an extract",
         "The list on the right says what each tab can do. Partitions, "
         "Compare, Emulate and Multi-boot work straight from a card, and so "
         "does Write on machines whose Build / flash dialog can write an "
         "existing card image onto an SD card (Stern, JJP, CGC). The "
         "Replace tabs and Mod Pack (and Write on the other machines) work "
         "on the files an extract pulls off the card, so until the project "
         "folder holds an extract they are greyed out in the list on the "
         "left, with a lock. They still open, under a banner saying what is "
         "missing and where to go next."),
    ],
    "Extract": [
        ("Pick a source",
         "The card comes from the Select card tab (a dumped card image / "
         "update file, or the physical media in a reader); the Extract tab "
         "shows it with a Change button that goes back there."),
        ("Which game is this card?",
         "In \"From SD card\" mode the game on the card you picked is named "
         "under the dropdown, read straight off the card with nothing copied "
         "anywhere — so a stack of cards can be sorted out by plugging each "
         "one in and reading the line. A card carrying a boot menu says so "
         "and how many games are on it. Card details, under the card on the "
         "Select card tab, reads the rest off the card itself: firmware "
         "version, edition, asset counts and partitions. Reading a "
         "card in place needs Administrator on Windows, and the line says so "
         "when it hasn't got it."),
        ("Save card as image",
         "In \"From SD card\" mode, \"Save card as image…\" copies the whole "
         "card, sector for sector, into one .raw file — the reverse of the "
         "Write tab's flash. Use it to back a stock card up before modding "
         "it, to keep a copy of a card someone sent you, or to dump the same "
         "card twice (before and after a change made on the machine) and diff "
         "the two on the Compare tab. The file is as big as the card is, "
         "empty space included, and nothing on the card is changed."),
        ("Detection",
         "Once the game is recognised, its name (and firmware version) "
         "appears in the window's title bar. \"Not recognised\" under the "
         "path usually means the wrong kind of file — or a copy that is "
         "still in progress; try again once the copy finishes. If the file "
         "belongs to a different manufacturer, that line offers a one-click "
         "switch."),
        ("Multi-boot cards hold several games — you get the first",
         "A card with a boot menu carries a complete game per menu entry, and "
         "everything here works on the FIRST one: the extract, the "
         "replacements you make from it, and the card a Build writes. Press "
         "Extract (or Build) on such a card and a notice says so, lists the "
         "games on it, and names the one in play. Nothing is lost — a Build "
         "copies the other games and the menu through untouched, so you get a "
         "working multi-boot card with the first game changed. To change one "
         "of the others, extract THAT game's own image, replace what you want "
         "and build it, then load the card on the Multi-boot tab, point that "
         "game's row at your new build and update the card in place. The "
         "Info button beside the path lists a card's games at any time."),
        ("What gets extracted",
         "The Audio / Video / Images / Text checkboxes choose which asset "
         "types to pull. Everything lands in the Project Folder — the one "
         "folder the Replace, Write and Mod Pack tabs all work out of "
         "(their folder rows are read-only views of this one). These "
         "choices (and the auto-name options) are remembered per "
         "manufacturer across sessions."),
        ("Projects",
         "The folder you extract into IS your project: a hidden project "
         "file appears in it automatically (first extract or first staged "
         "change) recording the manufacturer, stock image and options — "
         "picking that folder again later restores the whole setup. The "
         "blue folder button in the header holds the project actions: New, "
         "Open, Save as (a full fork copy, minus the rebuildable build "
         "output), Recent, the Projects list (sizes, notes, Archive to "
         "reclaim disk space from dormant projects), and Properties."),
        ("Auto-naming",
         "\"Auto-name call-outs\" transcribes speech locally (the first run "
         "downloads a ~75 MB model, after that it works offline). "
         "\"Auto-name music\" fingerprints full-length tracks against the "
         "online AcoustID database — the number after a matched title (e.g. "
         "0.97) is the match confidence. Results are also written to "
         "callouts.csv and music_titles.csv in the output folder. "
         "For better transcriptions at the cost of extra processing time, "
         "raise \"Voice recognition quality\" in the ⚙ settings menu (larger "
         "models are downloaded on first use)."),
        ("Length-prefixed names",
         "\"Length-prefix names\" (where available) leads each extracted "
         "sound's filename with its play length — e.g. "
         "\"01m22s235 - idx0001.wav\" — so sorting by name lines the same "
         "sounds up across firmware versions: slot numbers shift between "
         "releases, play lengths rarely do."),
        ("The baseline",
         "Extract writes a hidden .checksums.md5 file recording the pristine "
         "assets. The Replace tabs and Write use it to tell what you have "
         "changed — leave it in place."),
        ("\"The source image has changed\"",
         "A banner appears when the image you extracted from is no longer the "
         "file it was — swapped, reverted or rebuilt outside PAD — because the "
         "\"Original\" names on the Replace tabs then describe assets that "
         "image no longer holds. Re-extract to resync, or press Dismiss if you "
         "know it doesn't matter to you: that silences it for this image only, "
         "and it stays silenced after a restart. The next change to the image "
         "brings it back."),
        ("Re-extracting",
         "Extracting into a non-empty folder overwrites your edits (after a "
         "confirmation). Use a fresh project folder per firmware version — "
         "each project is one folder, one game version. (Extracting into an "
         "ARCHIVED project is different: that's the hydrate — your edited "
         "files are set aside first and restored over the fresh extraction "
         "automatically.) After a finished extract the Extract button greys "
         "out until you pick the card (on Select card) or folder again, change an option, or "
         "the card file changes, so a second click can't redo it by accident."),
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
                         "(default) or full scale, plus a ±12 dB offset. Moves every "
                         "replacement together."},
                {"icon": "wave", "tone": "ok", "title": "One clip",
                 "text": "**Loudness for this clip**, beside the Replacement preview. "
                         "Stacks on the build-wide offset; the Level column shows "
                         "which clips you levelled."}]},
            "- **Apply to all shown** puts the same offset on every row the list "
            "shows: set Type to Music first to move only the songs (Stern mixes its "
            "music quietly, under the callouts).\n"
            "- Boosts are soft-limited, never clipped. The build log says which "
            "setting built the card.",
        ]),
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
        ("Blip-free callouts (Advanced Audio Options)",
         "Removes a tiny scrap of the original sound from every replacement. "
         "Optional; works on real machines.\n\n"
         "- Without it, the machine needs a few bytes of each original sound at "
         "boot, so about 6 ms of the original plays twice inside every "
         "replacement. A tester listening for it could not hear it.\n"
         "- With it, those bytes are kept in the game program instead, and your "
         "audio plays all the way through.\n"
         "- It makes the game program slightly bigger, so it needs the card "
         "built as an image (the Linux filesystem driver, as full-size videos "
         "do). A Direct-SD write skips it."),
        ("Longer replacements (Advanced Audio Options)",
         "Lets a Spike 2 replacement be longer than the sound it replaces. "
         "Optional; confirmed on a real machine (no loop, correct cut-off).\n\n"
         "- Off, a longer clip is trimmed to the original's length.\n"
         "- On, your clip is added at the end of the sound bank and the game is "
         "pointed at it; every other sound is untouched. The preview shows the "
         "whole clip with a green line where the original ended.\n"
         "- It needs the card built as an image (the Linux filesystem driver). "
         "A Direct-SD write trims as before.\n\n"
         "### Two size limits\n"
         "1. **The 2 GB bank.** The game can open a sound bank only up to about "
         "2 GB, and each lengthened sound adds its whole length on top (on "
         "Godzilla 1.16, room for about 45 minutes of stereo). Anything over is "
         "trimmed and named in the log.\n"
         "2. **The games partition.** Lengthened sounds share it with full-size "
         "videos, and a stock 8 GB card may have only a few hundred MB free. When "
         "room runs short, longer sounds are trimmed to fit it; songs marked "
         "**Keep this song whole if the bank fills up** are kept whole first. The "
         "log names each one and the SD card size that would keep them whole.\n\n"
         "> SD card size on the Write tab (Windows and Linux) builds for a bigger "
         "card and gives the games partition more room, but it does not raise the "
         "2 GB limit."),
        ("Save and load settings",
         "**More > Save settings to a file…** keeps this tab's picks, ticks and "
         "options in one small file. **Load settings from a file…** puts them back, "
         "on this card or another.\n\n"
         "- Slots the file doesn't set keep what they have; slots this card lacks "
         "are skipped.\n"
         "- The file only names your sound files, it doesn't hold them."),
    ],
    "Replace Video": [
        ("Scan and assign",
         "Scan lists every video slot; assign a replacement clip per slot "
         "and compare it against the original in the side-by-side preview "
         "players before building. A clip that already matches the "
         "original's format, resolution and frame rate is used as-is; "
         "anything else is auto-re-encoded to match (transparency is kept "
         "where the original has it). The log says which one happened the "
         "moment you pick the file — \"already matches this slot — will be "
         "copied in, no re-encode\" or \"will be re-encoded to match this "
         "slot\" — so you never have to guess whether your clip was "
         "converted."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: the "
         "replacements you assign are applied automatically when you build the "
         "update on the Write tab."),
        ("Replacing a whole folder at once",
         "\"Replace from folder…\" beside the project folder takes a "
         "folder of your own files and picks each one for the clip with "
         "its name, so a whole set reworked outside the app goes in as "
         "one action instead of one pick per clip.\n\n"
         "Names pair whatever the file type and whatever the capital "
         "letters: a converter that wrote .mp4 for the card's .mov clips still pairs, and each file is converted to suit its slot "
         "when you build, like any other pick. Subfolders are searched "
         "too, and a file's own folders help it choose — when two slots "
         "are named the same, put the file under a folder named like its "
         "slot's. A clip that was set to go on as-is and comes back as a different file type is set to be converted instead, because going on as-is needs the slot's own file type.\n\n"
         "Keep your files in a folder of their own, OUTSIDE the project "
         "folder: the project folder holds the card's own files, so "
         "choosing it, or anything inside it, is refused. What comes back "
         "is ordinary replacements — they show in the Replacement column, "
         "the next build applies them, and \"Clear replacements…\" drops "
         "them again.\n\n"
         "Whatever it leaves out is named in the log: files named like no "
         "slot on this tab, files named like more than one of them, and "
         "files another file in the folder shares a name with."),
        ("Clearing replacements",
         "A replacement you pick is remembered against the PROJECT FOLDER, "
         "not against the card: it is stored in the folder itself, so it "
         "survives closing the app, and it is still there if you point the "
         "Extract tab at a different card image. That is what lets you come "
         "back to a project days later, and it is why picks never disappear "
         "on their own.\n\n"
         "To drop some, select the rows — click one, then Shift-click for a "
         "range or Ctrl-click to add single clips — and right-click the "
         "selection. Sort by the Replacement column first and everything you "
         "have picked sits together. \"Clear replacements…\" (in the More "
         "menu, the ⋯ button at the top) drops every pick on this tab at once.\n\n"
         "Clearing takes the replacement back out. A pick nothing has applied "
         "yet is simply dropped; a slot that a build, or Start on the Emulate "
         "tab, already wrote into the project folder gets the card's own file "
         "put back as well, so the list, the next build and the next emulator "
         "run all agree. None of your own files are touched. A slot changed "
         "some other way (a file copied over it by hand, or a build from "
         "before the app kept a saved original) keeps what it has — "
         "\"Revert all changes…\" on the Write tab is what restores those."),
        ("Scene editor (move, resize, turn, tint, layers, add)",
         "When the project has a scene's tree (Extract or \"Re-read from card…\" "
         "records it), the Scenes tab draws that scene the way the machine does - "
         "every picture and line of text in its own place, size, tilt and fade, at one "
         "MOMENT of its timeline - and you edit it right there. Click something in the "
         "preview (or its row under Layers) to select it; drag it to move it, drag a "
         "corner to resize it about its middle, or use the arrow keys to nudge it (Shift "
         "for 10 px). Ctrl-click (Cmd on a Mac) picks more than one, or takes one out "
         "again, and Shift-click in Layers picks every row between; dragging any of them "
         "or the arrow keys then move them all together (one Undo), Delete removes them, "
         "and the panel can hide or show them. The panel beside the preview sets its position and size exactly "
         "(W px / H px, keeping its shape or not), turns it (\"Turn °\" is degrees clockwise "
         "from as shipped; the 90° buttons turn it a quarter), tints it (a colour and an opacity), hides it, and moves it forward or back "
         "among the layers beside it - later layers draw on top. A picture also shows its "
         "own size and how big the scene draws it (\"Picture W x H px, drawn at N%\"); "
         "\"Draw 1:1\" takes the scene's scaling off so it draws pixel for pixel, "
         "keeping its top-left corner in place. A line of text also has "
         "\"Add a drop shadow\": a dark copy of the text just beneath it, a few pixels down "
         "and right, selected after so you can move, tint or remove it, and \"Fit box to text\", which shrinks or grows "
         "the line's box to sit round its words without moving them (copies drawn from the same text follow). \"Picture…\" and "
         "\"Text…\" add something new (text is written in the font and size of the "
         "selected line). \"Moment\" picks where in the scene's own timeline to look "
         "(Play runs the animation at its own speed; Stop goes back), "
         "and \"Switchable parts\" (click the box to open it; the number is how many "
         "parts it lists, numbered down the list) shows each part of the scene the "
         "game's code switches between looks (which monster Battle Select shows, a "
         "tile's Locked or city) - the file holds them all, the game chooses; pick one "
         "to preview it, which changes only the preview. Undo (Ctrl+Z) takes back the last edit, "
         "whichever button or key made it, and Redo (Ctrl+Y or Ctrl+Shift+Z) puts it back. A greyed layer is one the game is not "
         "drawing at this moment: click its name and it is shown on top, "
         "where it sits, at this same moment while it stays selected, ready to edit "
         "(an edit belongs to the layer, so it holds at every moment). A layer's eye works as in "
         "Photoshop or Fusion: it hides the layer in the preview only, to place things or reach "
         "what is under it, and never changes the card. H hides or shows the selected layers, "
         "and Alt+click on an eye shows that layer alone (Alt+click again brings the others "
         "back). Hiding a layer in the game is its own mark, like Fusion's Suppress: the card "
         "at the end of its row (or right-click, Hide in the game). The Write leaves it out of "
         "the card, the row is struck through and reads 'hidden in game', the status line names "
         "every such layer, and the preview is not changed. A scene opened for the first time "
         "starts with its eyes shut on the layers hidden in the game; after that the eyes stay "
         "as you set them until Reset puts them back ('Preview eyes as in the game', or As "
         "shipped). Delete hides a layer in both. Picking any layer shows it on top, even one "
         "hidden with its eye, and picking "
         "a sprite shows everything in it; no eye changes by picking. A dark layer "
         "with a crossed-out eye is off only because its switchable part shows another "
         "look: its eye turns it on in the preview (and back off). The "
         "layers inside that look keep their own eyes, like an editor's layers: one "
         "shows only while the look it sits in is on, and turning the look on leaves "
         "a layer you hid inside it hidden. Select "
         "something else and the scene goes back to what the game draws. A layer that draws a picture "
         "(itself or through what it holds) has a picture button at the end of its row: it opens "
         "that picture on the Images tab (a layer with several lists them to pick from). "
         "A text layer has a T button in the same place: it opens its words on the Text tab. "
         "Every edit is kept in the project and "
         "listed on the Write tab; the Write puts them on the card (moves, resizes, "
         "tints, hides and layer changes even straight to an SD card; an added picture "
         "or line of text makes the scene bigger, which needs an image build). The "
         "game's own parts are hidden rather than deleted, because its code finds them "
         "by name. Colour: these games draw most text in a styled font whose colours "
         "are baked in, so Tint is the way to recolour it. A project extracted before the "
         "editor existed has its scenes read off the Extract tab's card the first time the "
         "Scenes tab opens (about ten seconds, once). While you edit, the picture you see "
         "stays up and a small \"Updating\" tag shows while the change is drawn. Drag the "
         "dividers between the scene list, the preview and the panel on the right (and the one "
         "above Layers) to share the room the way you like; the app remembers them, and a "
         "double-click puts one back. To look closer, hold Ctrl (or Shift, or Cmd on a Mac) and turn the mouse wheel over the preview, or use the zoom buttons in the bar above it; the fit button goes back to 100%, and while zoomed you can drag the view with the middle mouse button. There is nothing to save: every edit is kept the "
         "moment you make it, and Write puts it on the card (\"Export picture…\" only makes a "
         "picture for you). Reset, under the preview, puts a scene back the way the last Write "
         "left it or the way the game shipped it, or every scene at once. With the Emulate "
         "tab running this project's edits (\"Apply my replaced assets on top\"), an edit is "
         "handed to the running game on the fly: a scene the game loads each time it shows "
         "it (most mode and message screens) changes the next time it comes up, and the tag "
         "under the preview says so; one the game loads when it starts (the score display, "
         "Battle Select) changes after a restart. Untick \"Include my Scenes tab edits\" (under \"Apply my replaced assets on top\") to run the card with your other replacements but the scenes as they were. Lines of W's (or AAA) are the game's own placeholders "
         "for text it fills in while it runs, such as high score initials: the game writes the "
         "player's letters there, so they are as wide as the widest name can be."),
        ("Save and load scene edits",
         "\"Save / load edits\" at the head of the Scenes page saves this scene's "
         "edits, or every edited scene's, to one .zip with the pictures they add, "
         "to share or keep. Loading such a file replaces a scene's own edits (it "
         "asks first when the scene has some). A scene is found by its path, so a "
         "file from the LE loads on the Pro; a scene this card lacks is left out "
         "and named, and an added picture whose name is taken by a different one "
         "is renamed. The file holds the scene editor's edits only, not Text-tab "
         "colours or text layout. \"Save ... with pictures and color profiles\" "
         "also puts in each picture those scenes draw that you replaced on the "
         "Images tab (the file, its Keep size tick, its color switch and the color "
         "profile baked into it), the color profiles of the pictures you added, and "
         "the whole screen overlay; the machine screen stays each PC's own. Loading "
         "it copies the pictures into the project's \"Shared pictures\" folder and "
         "never deletes or overwrites a file; when it would change a picture you "
         "replaced, a scene you edited or your overlay, it asks first."),
        ("Size limits",
         "On most games patching is size-neutral: a same-or-smaller "
         "replacement fits as-is, a larger one is re-encoded down to the "
         "slot's byte budget. A replacement that already matches the slot's "
         "format is copied through verbatim, with no quality loss. On Barrels "
         "of Fun the update's file offsets are rewritten around the new "
         "clip, so an oversized replacement skips the byte budget "
         "entirely.\n\n"
         "Stern Spike 2 has no byte budget per slot either: an image build "
         "puts every clip assigned here on the card at full size. The limit "
         "is the free room on the card's games partition, which all the "
         "full-size clips share with any lengthened sounds. A stock 8 GB "
         "card can have only a few hundred MB free, so a big retheme can run "
         "out; SD card size on the Write tab (Windows and Linux) builds for a "
         "bigger SD card and gives the games partition that room. A build "
         "whose clips won't fit is stopped before anything is written to the "
         "card image, and says how much room it needs. A clip is squeezed to "
         "fit its slot's "
         "byte size only on a direct SD write, when this computer can't "
         "write whole files to the card (on Windows that needs WSL2), or "
         "when the file picked for it has since been moved or deleted."),
        ("What the machine can actually play",
         "A clip only goes onto a Spike 2 card untouched when it's a real "
         "drop-in for the one it replaces — same container, H.264, 8-bit "
         "4:2:0, and the slot's own resolution and frame rate. The machine's "
         "decoder isn't a desktop player: give it an MKV, HEVC, a 10-bit "
         "clip or the wrong size and it plays the sound over a black "
         "picture. Anything that isn't a drop-in is converted first (still "
         "at full size, no byte budget) and the build log says which clip "
         "and why. The song videos also need a key frame every few frames, "
         "the way Stern encodes them: one with key frames far apart plays "
         "stuttering and slows the whole game down, so it is converted too."),
        ("Encoding your own clips",
         "Right-click a slot and pick \"What this slot needs…\" to see exactly "
         "what a replacement has to be to go on the card untouched: container, "
         "codec, H.264 profile and level, frame size, frame rate, key-frame "
         "spacing where the slot needs a short one, and whether the clip has "
         "an audio track. It also gives you an ffmpeg command that produces "
         "one, with only the flags that have to match, so you can add your "
         "own bitrate and preset around them. Every value is read off the clip already in that slot, which "
         "is the only real authority on what the machine will play — Spike 2 "
         "decodes H.264 in hardware and nothing else, so a ProRes or HEVC "
         "file plays its sound over a black picture no matter how good it "
         "looks on a PC."),
        ("Audio in a video file",
         "Most game clips have no audio track at all, and the game plays its "
         "own sound over them. A replacement that keeps its source's audio "
         "adds a soundtrack the machine really will play on top. Converting "
         "now matches the slot (a silent slot gets a silent replacement), and "
         "a file you copy in as-is is flagged in the Convert column as \"As-is "
         "⚠ audio\" so you can strip it first. Slots that do have their own "
         "audio keep it."),
        ("Use my files as-is",
         "This one checkbox covers EVERY replacement you have picked, not "
         "just the slot showing in the preview — tick or untick it any time "
         "and the Convert column re-answers for the whole list. You never "
         "have to pick files again to change your mind about converting "
         "them. On, each replacement is copied in byte-for-byte and has to "
         "already be game-ready; off, anything that isn't already a match is "
         "converted to suit the slot, still at full size."),
        ("The Convert column",
         "Once you assign a replacement, the Convert column says what the "
         "build will do with it: \"As-is\" means the clip already matches the "
         "slot's container, codec, size and frame rate and is copied straight "
         "in; \"Repackage\" means it already IS this slot's video and only the "
         "container around it is wrong, so ffmpeg rewrites the wrapper and "
         "every frame survives untouched; \"Re-encode\" means ffmpeg converts "
         "the picture itself, which is where a long build spends its time and "
         "the only one of the three that costs any quality. With \"Use my "
         "files as-is\" on you may "
         "also see \"✗ needs .mov\" (the build would refuse a different "
         "container) or \"✗ wrong format\" (it would be copied on untouched, "
         "but the machine can't decode it, so it would play its sound over a "
         "black picture) — untick the box for those and they get converted "
         "instead. The answer is worked out in the background, so a row can "
         "read \"…\" for a moment, and it re-checks itself whenever you "
         "change either checkbox. Export CSV carries the column too."),
        ("Slots already holding a wrong-format clip",
         "A ⚠ next to the Format cell means the clip sitting in that slot "
         "RIGHT NOW is one the machine can't decode (ProRes, HEVC, 10-bit) — "
         "usually one that went on as-is before the app checked for it. "
         "Select the row and a callout under the preview says so in words. "
         "The Format and Audio columns always describe the clip currently in "
         "the slot, so after you assign a good replacement they keep showing "
         "the old clip's format until the next build applies it — the "
         "callout turns amber and says the build will fix it. The "
         "\"Original\" preview pane shows the untouched factory clip "
         "whenever its backup exists, even for a slot you've already "
         "replaced — its title reads \"Original (stock)\" against "
         "\"Replacement (your file)\" so the two panes can't be mixed up "
         "when both sides carry the same slot name. That factory clip is "
         "also what the Convert column measures your replacement against: "
         "a slot whose current file is a wrong-format one you put there "
         "earlier can't teach the app the wrong frame rate, size or "
         "profile, so a clip cut to the machine's real spec still reads "
         "\"As-is\"."),
        ("Each clip's length",
         "Right-click a slot and pick \"This clip's length\" to choose how "
         "long that one clip plays: follow the Trim / pad box (the default), "
         "match the stock clip, keep your file's full length, or type a "
         "length in seconds. A clip with its own length shows it after the "
         "Length cell. Trim / pad always measures against the stock clip, "
         "so a slot you already replaced is still fitted to the original "
         "length on later builds."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
        ("Seeing where a clip plays",
         "Right-click a slot and pick \"Show scene contents…\" to open the "
         "Scenes tab on the scene that plays it, with the images, fonts "
         "and text it shares the screen with."),
        ("Very short clips",
         "Plenty of Spike 2 slots hold a clip well under a second — a sixth "
         "of one Batman card's 6331 do, down to one-frame stills — so the "
         "Length column shows those with their milliseconds (0:00.033) "
         "instead of rounding them to 0:00, which reads as an empty slot. "
         "The preview posters the first frame of a clip that short, "
         "because it is the whole clip."),
        ("Checking a card you already built",
         "\"Check card…\" (in the More menu, the ⋯ button at the top) asks the other question: not what "
         "you are about to put on, but how the clips ALREADY on a card came "
         "out. Point it at a built card image and it measures every clip on "
         "it and lists the ones low enough in bitrate to look blocky — the "
         "same test a build applies to a replacement, applied after the fact. "
         "It reads the image only, takes a few seconds, and needs no "
         "extract.\n\n"
         "The list separates two very different problems, because the fix is "
         "different. A clip marked \"squeezed to fit\" was too big for the "
         "slot it replaced and the build shrank it to fit: build an image "
         "file (not a direct-SD write) with WSL working and it goes on whole "
         "instead, no re-export needed. Whole clips need room on the card's "
         "games partition, though, and a stock 8 GB card can have only a "
         "few hundred MB free, so when many clips come back squeezed, build "
         "for a bigger SD card with SD card size on the Write tab (Windows "
         "and Linux). A clip that is just low in bitrate was not squeezed, "
         "and the card can't say which of two things it is. If it went on as "
         "your own file, it is exactly as you exported it, so only a better "
         "export will improve it. If it went on as the app's converted copy "
         "(a replacement that isn't an exact match for its slot is "
         "converted), an older version of the app may have converted it far "
         "below Stern's bitrate, and building again from your original "
         "replacement files converts it at the bitrate of the clip it "
         "replaces. The same room limit applies to that rebuild.\n\n"
         "A handful of the game's own clips sit under the bar by design "
         "(long attract loops are encoded lean), so a card with nothing of "
         "yours on it is not expected to come back empty."),
        ("Best quality from your own files",
         "Stern Spike 2. A replacement that isn't already an exact match for "
         "its slot is converted, and by default the conversion is held to "
         "the bitrate of the clip it replaces, so it fits where that clip "
         "was. Tick \"Best quality\" (or use \"Best quality…\" on the "
         "toolbar) and each clip is converted at full quality instead: it "
         "gets the bits its picture needs, which for a detailed clip is "
         "more than the stock clip had and for a simple one can be less. "
         "Build for a 16 GB or 32 GB SD card on the Write tab if they don't "
         "fit; a build that won't fit says so before it copies anything. "
         "Converted clips are kept in the project, so building again only "
         "converts the clips whose file or setting changed.\n\n"
         "If the project doesn't know which files your clips came from — "
         "you built the card on another PC, or picked the clips from files "
         "named nothing like the slots — \"Best quality…\" can find them. "
         "Pick a card built with your videos, the stock card it was built "
         "from, and the folder your videos are in, then Find. Every clip "
         "that card replaced is compared with every video in the folder by "
         "what it looks like, so names and file types don't matter, and a "
         "colour clip is told from its black-and-white twin. Where the "
         "folder has the same video more than once (a master and an "
         "export, two copies), the best copy is used. Amber rows are worth "
         "a look before you use them; \"already on the card untouched\" "
         "means your file went onto the card exactly as it is, so building "
         "from it again won't make that clip any better. Untick anything "
         "you don't want, then \"Use these files at best quality\". The "
         "first search of a big folder takes a few minutes; a second one "
         "reuses what it read."),
        ("Save and load settings",
         "More > Save settings to a file... keeps this tab's picks, ticks and "
         "options in one small file; Load settings from a file... puts them "
         "back, on this card or another one. Slots the file doesn't set keep "
         "what they have, and slots this card doesn't have are skipped. The "
         "file only names your files, it doesn't hold them."),
        ("Color column (Spike 2)",
         "A replaced clip shows a Color palette: green, a color profile is "
         "attached to it, so the Color profile tab's individual files profile is "
         "baked into it when you build (it is re-encoded for that); red, no "
         "color profile is attached and it goes on the card as it is. The Color profile tab's 'Every replaced video' sets "
         "every clip that has no switch of its own. The game's own clips show "
         "a blue lock and are never changed; tick Advanced on the toolbar to "
         "give each one its own palette, and detaching one (or unticking "
         "Advanced) puts the original back."),
        ("Preview colors (Spike 2)",
         "The row above the players shows the clips the way the machine will, "
         "with a switch for each step: the Whole screen overlay, the "
         "Individual files correction (a replacement with the color profile "
         "attached) and the Machine screen. Turn them on and off to see what each "
         "one does; all three off is your PC's own colors. Every clip goes "
         "through the Machine screen; tick the gear menu's 'Files with no "
         "color profile attached skip the Machine screen' to let a replacement "
         "with no color profile attached skip it (it still gets the overlay). Click a name to open it on the Color profile "
         "tab. Only the preview changes: the card is not, and no clip is "
         "re-encoded for it."),
    ],
    "Replace Images": [
        ("Scan and assign",
         "Scan lists the game's replaceable images. Assign a replacement "
         "per slot — almost any image format works; it is auto-scaled to "
         "the original's pixel dimensions and converted to the slot's "
         "format (transparency is kept where the original has it). Keep "
         "the original resolution for best results."),
        ("Color column (Spike 2)",
         "Every row has a Color mark. A replaced picture shows a palette: "
         "green, a color profile is attached to it, so the Color profile "
         "tab's individual files profile is baked into it when you build; red, "
         "no color profile is attached and it goes on the card as it is. The "
         "box under the preview does the same. The Color profile tab's 'Every replaced picture' "
         "sets every picture that has no box of its own. The game's own "
         "pictures show a blue lock and are never changed; tick 'Unlock "
         "extracted images' under Advanced to give each one its own "
         "palette, and detaching one (or locking again) puts the "
         "original back."),
        ("A bigger picture than the original",
         "Stern Spike 2: a picture inside a game scene (Source \"Radium\", "
         "not a font) can keep its OWN size instead, e.g. a longer name "
         "banner. Tick \"Keep this picture's own size\" under the preview, "
         "or its box in the Keep size column of the list: the build grows "
         "the scene to fit it and the game draws it at the new size, from "
         "the same top-left corner, so a wider picture "
         "reaches further right. Needs an image build, not a direct SD "
         "write. Verified in the PC emulator; no machine has run one yet. "
         "A few pictures cannot take a new size, because nothing in their "
         "scene draws them by size (full-screen backgrounds, for one). The "
         "build fits those to the original size instead, exactly as with "
         "the box unticked, and the log names each one."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: each "
         "replacement you assign is auto-fit to its slot (scaled, "
         "format-converted, size-matched) and applied automatically when you "
         "build the update on the Write tab."),
        ("Replacing a whole folder at once",
         "\"Replace from folder…\" beside the project folder takes a "
         "folder of your own files and picks each one for the image with "
         "its name, so a whole set reworked outside the app goes in as "
         "one action instead of one pick per image.\n\n"
         "Names pair whatever the file type and whatever the capital "
         "letters: a batch export that wrote .png over the card's .jpg still pairs, and each file is converted to suit its slot "
         "when you build, like any other pick. Subfolders are searched "
         "too, and a file's own folders help it choose — when two slots "
         "are named the same, put the file under a folder named like its "
         "slot's. Scene pictures and font glyphs are named with a fingerprint of the card they were extracted from, so copies from another card's extract cannot pair by name at all — \"Transfer Mods to New Version\" on the Mod Pack tab carries those over by content instead.\n\n"
         "Keep your files in a folder of their own, OUTSIDE the project "
         "folder: the project folder holds the card's own files, so "
         "choosing it, or anything inside it, is refused. What comes back "
         "is ordinary replacements — they show in the Replacement column, "
         "the next build applies them, and \"Clear replacements…\" drops "
         "them again.\n\n"
         "Whatever it leaves out is named in the log: files named like no "
         "slot on this tab, files named like more than one of them, and "
         "files another file in the folder shares a name with."),
        ("Clearing replacements",
         "A replacement you pick is remembered against the PROJECT FOLDER, "
         "not against the card: it is stored in the folder itself, so it "
         "survives closing the app, and it is still there if you point the "
         "Extract tab at a different card image. That is what lets you come "
         "back to a project days later, and it is why picks never disappear "
         "on their own.\n\n"
         "To drop some, select the rows — click one, then Shift-click for a "
         "range or Ctrl-click to add single images — and right-click the "
         "selection. Sort by the Replacement column first and everything you "
         "have picked sits together. \"Clear replacements…\" (in the More "
         "menu, the ⋯ button at the top) drops every pick on this tab at once, and a scene "
         "group's own right-click menu clears just that animation.\n\n"
         "Clearing takes the replacement back out. A pick nothing has applied "
         "yet is simply dropped; a slot that a build, or Start on the Emulate "
         "tab, already wrote into the project folder gets the card's own file "
         "put back as well, so the list, the next build and the next emulator "
         "run all agree. None of your own files are touched. A slot changed "
         "some other way (a file copied over it by hand, or a build from "
         "before the app kept a saved original) keeps what it has — "
         "\"Revert all changes…\" on the Write tab is what restores those."),
        ("Where images come from",
         "The Source column tells the stores apart. \"File\" = a "
         "plain image file on the card (menus, apron/test art). \"Scene "
         "texture\" = artwork decoded out of the game's compiled display "
         "scenes — many are frames of an animation or sprite sheets. "
         "\"Radium\" = images embedded inside the scene descriptions "
         "themselves (song-title banners and similar). \"Glyph\" = a single "
         "character sliced out of a font atlas (see Font atlases below). "
         "\"Boot screen\" = the picture the machine shows while it starts "
         "up (Stern's logo, SternLogo.png), which lives on the OS partition "
         "rather than with the game's files; an extract made before this "
         "version doesn't have it until you Extract again. "
         "All of them replace the same way; the Source dropdown in the toolbar "
         "narrows the list to one store, and clicking the Source header "
         "sorts by it."),
        ("Scene groups",
         "\"Group by scene\" nests each image under the scene / animation "
         "it belongs to, in play order. Right-click a group header to "
         "assign one replacement to every frame, blank the whole "
         "animation (transparent), clear its pending replacements, or "
         "rename the group — most factory scene names are generic "
         "(\"unnamed_instance_14\"); your name is remembered for that "
         "assets folder and is matched by Search. Search finds an image by "
         "its own file name or by any scene it appears in — the scene's "
         "name, your rename, or its id/hash — so a hit doesn't always have "
         "the words in its file name; \"Group by scene\" shows which scene "
         "matched."),
        ("Font atlases",
         "Some scene textures are font/glyph maps — a grid of characters "
         "the game draws text from. You can re-style the whole grid, but "
         "keep every glyph in its original position: the game blits fixed "
         "rectangles, so moving or resizing glyphs scrambles on-screen text."),
        ("Editing one letter (Glyph source)",
         "To restyle a single character without touching the grid, set the "
         "Source dropdown to \"Glyph\": the app slices each font atlas into "
         "one image per character (named by its letter, e.g. \"U+0041 A\") "
         "and drops your replacement back into that character's exact "
         "rectangle — so you can redraw just the \"S\" and leave the rest "
         "alone. These sit under scene_textures/glyphs/ in the extract."),
        ("Fonts window (preview + import)",
         "The \"Fonts…\" toolbar button (where available) opens a preview "
         "of every game font: pick one, type your own text, and see it "
         "rendered from the real glyphs with the game's own spacing — "
         "pending glyph edits show up live. \"Import font file…\" fits a "
         "normal desktop font (TTF/OTF) into the game font automatically: "
         "one size is chosen so every letter fits the space its character "
         "has, each letter is baseline-aligned into its slot, and the ink "
         "color starts matched to the original. Apply writes the glyph "
         "PNGs (build on Write as usual); \"Revert font\" restores every "
         "letter from the atlas, \"Revert all fonts\" puts the whole "
         "project back to stock, and \"Undo\" steps back one write at a "
         "time. One typeface is baked into its own atlas per size AND per "
         "scene, so it fills several rows here that can look identical — "
         "those rows are marked \"copy 2 of 3\" and so on, and the line "
         "above the list says how many of them are further copies. The "
         "tick by the buttons changes every copy at once, and it governs "
         "Apply, \"Blank font\" and \"Revert font\" alike, so a restyle, a "
         "blanked outline and the way back all reach the same rows. If "
         "the font has an OUTLINE companion (a "
         "second font the game draws in black behind the letters) it is "
         "named above the buttons, and \"Remove it\" blanks that border in "
         "the scenes this font is in — only there, so the same outline "
         "stays put elsewhere. \"Outline\" is your own border in pixels, 0 "
         "for none; \"Letter width\" draws letters narrower inside their "
         "slots, which is what puts a gap between letters that touch (the "
         "game's own spacing is fixed on the card). Fonts under 30px are "
         "marked \"tiny\" because a desktop font rarely survives being "
         "fitted that small. \"Blank font\" erases a font's letters so it "
         "draws nothing, which is how an outline or shadow font is removed "
         "on its own; it asks first and names how many further copies and "
         "scenes it will reach, and \"Revert font\" comes back exactly that "
         "far — outline companions included — in one \"Undo\". \"Behind\" "
         "puts the preview on something other than "
         "black, the only way to see a black outline or where a letter's "
         "box ends. The \"Color\" swatch works with no font file too: pick "
         "a colour and it previews on whatever font you select, then Apply "
         "repaints that font's existing letters in it. Remember the SCENE "
         "multiplies that colour — the line under the controls says which "
         "colours the scenes draw this font in, and a font a scene tints "
         "black stays black whatever you pick."),
        ("Scenes tab",
         "The Scenes tab (an image's right-click \"Show scene contents…\" opens it too) lists every "
         "scene on the card with the images, fonts and on-screen text it "
         "is built from — double-click an item to jump to its row here, in "
         "the Fonts window, or on Replace Text. Right-click any scene "
         "image for \"Show scene contents\" to land there directly. It "
         "also PREVIEWS the scene as the machine draws it, composited from "
         "THIS project folder — replace an image or import a font and the "
         "preview redraws with your version. Titles are drawn the way the "
         "machine layers them — the black outline font underneath, then "
         "the fill on top — so a border can be checked here (over a light "
         "\"Behind\" backdrop; black on black is as invisible here as on "
         "the machine), and a scene's font sizes are quoted with the same "
         "numbers the Fonts window uses, so the two windows always call "
         "one font one size. Click any column heading to "
         "sort the list — by image count to find the big scenes, by Video "
         "to find the ones that play a clip. One scene file holds every "
         "screen a mode can put up — its intro, each award, the phase and "
         "victory screens — and the machine shows one at a time as the "
         "game runs, so the \"Screen\" box draws them one at a time under "
         "the game's own names instead of piling them on top of each "
         "other; the ◀ ▶ buttons step through them. Scenes that animate "
         "play their frames at the frame rate written in the scene itself "
         "(it varies per scene), and the \"Speed\" box — which only "
         "appears for a scene that actually moves — overrides it if you "
         "want a closer look at a fast one. On a big scene, Play first "
         "shows \"Getting frames ready…\" until enough frames are drawn "
         "that the first loop can run without stalling. \"Export picture…\" writes a "
         "still scene out full size as a PNG; on a scene that moves the button reads "
         "\"Export video…\" and writes the whole scene as an MP4 at its own frame "
         "rate, every frame drawn the way the preview draws it (your edits, the "
         "preview eyes, the backdrop and the Machine screen included), or the frame "
         "on the preview as a PNG if you pick that instead. The MP4 needs ffmpeg "
         "installed. \"Export all pictures…\" does the whole list at once: one "
         "PNG per scene into a folder you pick, following whatever the "
         "Search box is filtering on, so you can flip through a card's "
         "screens in an image viewer. \"Export all videos…\" is the same in one click "
         "for videos: an MP4 of every listed scene that moves and a PNG of each still "
         "one. Both run in the background — the "
         "same button becomes Cancel while it works, closing the window "
         "stops it, a name already in the folder is suffixed rather than "
         "overwritten, and the message beside the buttons tells you how many were "
         "written and how many could not be drawn. \"Re-read from card…\" re-reads the scene "
         "layouts off the card image on the Extract tab in a few seconds; "
         "it rewrites only the layout file, so your images, glyph slices "
         "and font imports are left alone (a full re-extract would "
         "overwrite them). \"Behind\" lays the preview over a lighter "
         "backdrop or a checkerboard instead of the machine's black — the "
         "only way to see a black border or the edge of a piece of art. "
         "RIGHT-CLICK anything in the Contents list to act on it: a text "
         "line offers \"Text colour…\", which is where a text colour "
         "actually lives (the font is white on purpose so the scene can "
         "tint it), and a font offers \"Blank this font in this scene\" or "
         "everywhere it is used — one atlas is shared by every scene that "
         "draws it, so prefer the scoped one."),
        ("Text layout (move, alignment, font size)",
         "The same right-click on a text line also offers \"Move…\", an "
         "\"Alignment\" submenu (Left / Centre / Right) and \"Font size…\". "
         "All three are per-scene, in-place, size-neutral edits of that "
         "scene's file, exactly like a text colour: a move shifts the "
         "line's box by the pixels you type, alignment rewrites the flag "
         "the scene keeps beside it, and the preview follows every change "
         "as you make it. \"Font size\" here means the size THIS scene "
         "bakes the font at — each scene carries its own copy of the "
         "glyph metrics for every face it draws — so it is a percentage "
         "of the scene's own size, and the dialog shows the pixels it "
         "comes to next to the scene's original. Shrinking is lossless; "
         "enlarging past the size of the master art blurs, because the "
         "atlas is only scaled, never redrawn. Two things to know: the "
         "edit applies to every keyframe of that string in the scene "
         "(the outline drawn under a title moves with its fill), and a "
         "size change resizes every OTHER line in that scene drawn with "
         "the same font, because they share the one metric table — the "
         "log names them when you write. \"Back to the original layout\" "
         "drops the edit; nothing touches the card until the Write tab, "
         "where layout edits ride the same path as text colour and show "
         "up in its preview and the list of changes to write. The words "
         "themselves are changed on Replace Text, not here — but a "
         "replacement you have typed there is what this preview draws, "
         "so the box, alignment and size can be judged against the new "
         "text rather than the stock one; the row reads \"shows: …\" and "
         "\"(not built yet)\" while it is pending."),
        ("Size limits",
         "Patching is size-neutral: the encoded replacement must fit the "
         "original slot's byte budget — a small enough image drops "
         "straight in, a larger one is re-compressed (fewer colours) to "
         "fit, and one that still won't fit is skipped (left unchanged); "
         "use a simpler image. Exception: scene/radium glyph and sprite "
         "atlases are re-encoded losslessly to the slot's exact "
         "dimensions with no byte-size limit."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
        ("Save and load settings",
         "More > Save settings to a file... keeps this tab's picks, ticks and "
         "options in one small file; Load settings from a file... puts them "
         "back, on this card or another one. Slots the file doesn't set keep "
         "what they have, and slots this card doesn't have are skipped. The "
         "file only names your files, it doesn't hold them."),
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
            {"note": "A scene's line is often a placeholder the code writes over. If a "
                     "line still shows the old words on the machine after you changed "
                     "every scene copy, edit its game-program row.", "kind": "tip"},
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
        ("Apply to all",
         "**Apply to every scene with the same original text** makes the same edit "
         "everywhere that exact line appears (many lines repeat once per scene)."),
        ("Seeing the line in its scene",
         "**Show in Scenes…** (also on the right-click menu) opens the Scenes tab on "
         "the scene that draws the line, with the line picked out: its font, colour "
         "and the art behind it.\n\n"
         "- Your edits show there before anything is written (the Contents row says "
         "\"(not built yet)\"), so you can check a longer line fits its box.\n"
         "- A game-program line whose scene is a placeholder shows your edit, since "
         "that is what the machine draws.\n"
         "- Game-program lines no scene draws have nothing to preview."),
        ("Narrowing a big card down",
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
    "Color profile": [
        ("What it does",
         "A color profile corrects the colors of this project's build: the "
         "middle shades and color level of each channel, the color strength "
         "and the shadow lift. On Spike 2 the game itself draws every picture "
         "and video through it; on other machines the replaced pictures and "
         "videos are corrected when they are staged. 'No change' leaves the "
         "colors alone."),
        ("Starting points",
         "Recommended is the usual starting point; Black and white suits the "
         "black-and-white playfield editions. Hover a starting point's button "
         "to see how it was made, then adjust the sliders and watch the curve "
         "graph and the preview."),
        ("Preview and emulator",
         "Drag across the preview to compare before and after on a test card, "
         "one of your Images-tab replacements or another picture. 'See it in "
         "the emulator' runs this project's edits with the profile; Emulate's "
         "'Stock colors' tick leaves it out."),
        ("Part of the project",
         "The profile is a staged change of this project: Write lists it as "
         "pending, Revert all clears it, and Save a copy / Load move it "
         "between projects. Saved profiles lists the copies saved in that "
         "folder by file name: pick one to use it. The one in use is shown "
         "there, and the starting point in use is highlighted."),
        ("Individual files (Spike 2)",
         "The whole screen overlay reaches the game's own art too, which "
         "Stern already made for that screen. Adjust individual files for "
         "a second profile that is baked into only the replaced pictures "
         "and videos (and pictures added in Scenes) it is attached to: tick "
         "'Every replaced picture' or 'Every replaced video' there, or one "
         "file at a time in the Color column of the Images and Video tabs "
         "and the palette in the Scenes layers. It starts from Recommended. "
         "The game's own pictures have no switch (a blue lock) until Advanced unlocks them on the Images or Video tab. "
         "Both can be on at once: the overlay is drawn over the baked files "
         "like everything else."),
        ("Machine screen (Spike 2, preview only)",
         "Not a correction but the screen itself: what your machine does to "
         "what it is given. Scenes and the Video tab's players draw through "
         "it when its switch under Preview colors is on; nothing is written "
         "to the card and Revert all leaves it. Besides the sliders it has "
         "Color ranges (one band of hues at a time: hue, width, soft edge, "
         "hue shift, saturation and brightness, with greys protected) and "
         "Curves (RGB, then Red, Green and Blue, through points you drag or "
         "type). Every control has a number box and a reset; new ones "
         "change nothing until moved. Save a copy keeps them; loaded into "
         "the other two modes they are left out."),
        ("Preview colors (Scenes)",
         "The row under the Scenes preview draws the scene the way the "
         "machine will, with a switch for each step: the Whole screen "
         "overlay, the Individual files correction (the files it is attached to) "
         "and the Machine screen (set on the Color profile tab; until you "
         "set one, the Recommended screen). Turn them on and "
         "off to see what each one does; all three off is your PC's own "
         "colors. The Machine screen reaches the pictures and videos, a test "
         "card you added included, but not lines of text: they keep their "
         "own color and get only the overlay. Tick the gear menu's 'Files with no color "
         "profile attached skip the Machine screen' to let a file with no color "
         "profile attached (a red palette in Layers) skip it, to see it against the game's own art; it still "
         "gets the overlay. Click a name to open it on the "
         "Color profile tab. Only the preview changes: the card is not."),
        ("Color profiles bar (Scenes, Images, Video)",
         "The rainbow Colors tab on the right edge of the Scenes, Images and "
         "Video tabs slides out the Color profile tab's controls beside the "
         "page, so you tune a profile with the scene and its Layers, or the "
         "list and its Color column, in view: each file's color switch stays "
         "at hand. It is one set of profiles wherever it is opened: a saved "
         "profile picked from the list on the Images tab is the one Scenes "
         "and the Video tab use too, and the other way round. On Images and "
         "Video the bar opens on Files the first time, the profile their "
         "Color column attaches to a file. On Scenes the scene list steps "
         "aside while it is open: the Scenes tab down the left edge brings "
         "it back, the arrow at the end of its search row hides it again. "
         "Each tab remembers whether its bar was left open. Drag the bar's "
         "left edge to make it wider or narrower (double-click puts it back). "
         "Undo and Redo (Ctrl+Z, Ctrl+Y) step back through the changes to "
         "the profile on show; each profile keeps its own. Clicking a name "
         "under Preview colors opens it on that profile. Overlay, Files and "
         "Machine screen pick the profile, with a dot on those in use; Copy "
         "and Paste carry one profile's numbers (ranges and curves too) to "
         "another. The same starting points, sliders, number boxes, Color "
         "ranges, Curves, Save a copy and Load are there. The scene, or the "
         "Video tab's players, is drawn again a moment after each move, while "
         "'Show it in this preview' (the same switch as under Preview colors) "
         "is ticked; the Images tab's preview does not draw through the "
         "profiles, so its bar has no such switch."),
        ("One profile per file",
         "Each picture, clip or picture added in Scenes can have a color "
         "profile of its own. Click it (a row on Images or Video, a layer in "
         "Scenes) with the Colors bar open, or open the bar with it clicked, "
         "and Files shows that file's profile: the one baked into it now. "
         "Pick a starting point or a saved profile, or move a slider, and "
         "that file gets it as its own (its color profile is attached if it "
         "was not). Same as the other files drops it again. A file with no "
         "profile of its own gets the individual files profile, which the "
         "bar shows with no file clicked and the Color profile tab always "
         "shows. Hover over a file, or a layer in Scenes, to see its Color "
         "profile, or None."),
    ],
    # The Modes tab's own tips are in PREVIEW_HELP: a copy of the app without a
    # preview code shows none of them (sections_for).  The key stays so every
    # notebook tab has an entry.
    "Modes": [],
    "Write": [
        ("What a build does",
         "Build copies the pristine original and repacks every file in the "
         "assets folder that differs from the extract baseline — including "
         "changes from earlier sessions, not just today's. Changed sounds "
         "are re-encoded and replaced videos / images / text are patched "
         "in, on most games size-neutrally, so the built file is a drop-in "
         "replacement for the original. On Stern Spike 2, replaced videos "
         "and lengthened sounds go on at full size, in the free room on the "
         "card's games partition, and a build for a bigger SD card (SD card "
         "size, below) is that card's size, so it needs an SD card at least "
         "that big. The Modified Files list previews exactly what will "
         "go in before you click — it's only a preview: the build does its "
         "own full comparison, so there's no need to wait for the scan to "
         "finish before building."),
        ("Building again",
         "A second build onto the same file can be an update. When the file "
         "in the build folder is the build this app made from this original "
         "and project, and nothing has touched it since, the Build button "
         "offers to update it in place: the card image is not copied again, "
         "replacements already on it stay put, only the ones that changed "
         "since are written, and anything taken back since gets its stock "
         "content back. On a mod with hundreds of replaced videos that is "
         "minutes rather than hours. The build's record lives beside it (a "
         ".pad-build.json file); answer No, or delete the record, to build "
         "from the original again. Anything the record can't vouch for — a "
         "different original, a file changed since, a copy that failed, an "
         "app update — makes the build start over from the original, and the "
         "log says why."),
        ("Building from a multi-boot card",
         "The build is the whole card again, so a multi-boot original gives "
         "you a multi-boot build: the first game on it carries your changes "
         "and every other game, plus the menu, is copied through exactly as "
         "it was. A notice before the build says which game that is. To "
         "change one of the others, build that game's own image and then put "
         "it onto the card from the Multi-boot tab (load the card, point that "
         "game's row at your build, update in place) — only the parts that "
         "changed are written."),
        ("SD card size (Stern Spike 2)",
         "Every replaced video and grown sound goes onto the card's games "
         "partition, which only has the room Stern left on it for the "
         "original's card size: a stock 8 GB card can have a few hundred MB "
         "free, and a big retheme can run out of it. If the SD card in your "
         "machine is bigger, pick its size under SD card size, below the "
         "Build Image line: the games partition grows to fill that card size "
         "and everything else on the card stays exactly as it was. The built "
         "image is then that size, so it only fits an SD card at least that "
         "big, and flashing it takes longer. Room is all a bigger card "
         "gives: the game still can't open a sound bank over about 2 GB, so "
         "the limit on lengthened sound stays where it is, and nothing that "
         "is fitted to its original's slot gets any bigger. Before anything "
         "is written to the card image, a build adds up what it will put on "
         "the games partition. Longer sounds are trimmed to the room that is "
         "left. A build whose videos won't fit is refused then, with the "
         "numbers and the smallest SD card size that could take it (when one "
         "could), and the file already at the output is left as it was. "
         "When a bigger SD card size would fit it, the app asks whether to "
         "change to that size; Yes sets SD card size and builds again. A "
         "video that has to be converted is counted once it is, so that "
         "refusal can come after the conversions; the converted videos are "
         "kept in the project. An update that no longer fits "
         "beside the last build's files is built from the original instead. "
         "A few small files made during the build are only estimated ahead, "
         "so a build right at the limit can still stop at the copy at the "
         "end, and the log says so. Only sizes bigger than the "
         "original that it can be built at are offered (a multi-boot card is "
         "sized on the Multi-boot tab instead), and the option isn't "
         "available on macOS yet. The size applies to building an image: a "
         "direct write keeps the card's own partitions, and Port + build "
         "makes every other card at its own size. The card, and whether this "
         "computer can grow one, are checked before anything is converted; "
         "if either can't, the note under SD card size says why, and a build "
         "is refused with that reason before any other question. When the "
         "original's file name carries its card size, as Stern's own names "
         "do (\"…Release.8G.sdcard.raw\"), the build is named for the size it "
         "is built for instead, so it lands beside a build made at the "
         "original's size. Any other name stays the same at every size, so "
         "the bigger build replaces the other one: give it a name of its own "
         "with Change… to keep both."),
        ("Output name",
         "The Build Image line shows the exact file the build will "
         "produce. Builds land in the project's own build\\ folder — one "
         "build per project, overwritten on each rebuild — with a distinct "
         "default name (e.g. \"…-modified.raw\", where supported) so it "
         "can't be mistaken for the stock file. \"Change…\" is one Save-As "
         "picker for both the folder and the name — handy when a "
         "NAS-hosted project should build to a local drive; the required "
         "extension is applied automatically. A folder you typed that "
         "doesn't exist yet is created when the build starts — and if it "
         "can't be, you're told which folder and why before any work "
         "happens, not a minute into the build."),
        ("Reading the Modified Files list",
         "Click any column header — File, Type or Status — to sort the "
         "list; click the same one again to flip it, and a third time to "
         "put it back in the scan's own order, which groups Pending above "
         "Modified. Export CSV saves every row exactly as it reads on "
         "screen, so two projects that disagree on their change count can "
         "be diffed in a spreadsheet instead of by eye."),
        ("Undo",
         "\"Revert all changes…\" restores every changed asset back to its "
         "extract original (the build inputs, not any card)."),
        ("Direct write",
         "\"Write to SD card / SSD\" (where available) applies the same "
         "changes straight to the physical media. Remove the media from the "
         "machine first and always keep a backup image."),
        ("Build / flash",
         "On SD-card machines (Stern Spike 2, CGC) \"Build / flash SD "
         "card…\" is the single build button: it opens a two-part dialog "
         "where you build a fresh image, write an image onto a card, or "
         "tick both to build and then flash the fresh build in one step — "
         "the quickest way to test a change on the machine. With building "
         "unticked it flashes any pre-built or backup image, without a "
         "separate imaging tool. The whole card is erased and replaced; a "
         "size check refuses an image too big for the card. Requires "
         "Administrator. The dialog opens on whichever pair you ran last "
         "(remembered per manufacturer, across sessions), so a build-only or "
         "flash-only habit doesn't have to be re-ticked every time. (Other "
         "machines keep a plain Build button.)"),
        ("USB install stick (JJP)",
         "On Jersey Jack machines the same button reads \"Build / make USB "
         "install stick…\", and the stick section does something different: "
         "instead of raw-writing the ISO it formats the stick FAT32 and "
         "copies the ISO's files onto it — the only stick layout a JJP "
         "machine can read. A stick written with balenaEtcher, dd or Rufus' "
         "DD mode fails on the machine with 'Failed to mount USB stick'. "
         "Put the finished stick in a USB port on the computer in the "
         "backbox (the cabinet's front slot works too, but on some machines "
         "it is thirty times slower: a minute on the Restore menu, hours to "
         "install), leave the "
         "purple security key plugged in, and power on: the installer runs "
         "by itself — the Utilities USB-update menu is only for JJP's small "
         "delta updates and ignores install sticks. The installer checks for "
         "the security key first and stops on \"Security key not found\" if "
         "it is missing."),
        ("Onto the game's SSD instead (JJP)",
         "The stick dialog's \"Onto:\" row offers the game's SSD in a dock on "
         "this PC as a second place for a JJP install ISO. The app then does "
         "what the machine's installer would - the partition table from JJP's "
         "own template, every partition restored, the machine's filesystem "
         "IDs - and reads the disk back before it says done. It needs the app "
         "run as Administrator (the disk is handed to WSL whole), erases the "
         "disk, and needs no stick and no security key for the write; the key "
         "is still needed to play. On a disk that already holds this install, "
         "the \"Write:\" choice replaces only the boot menu (make the change "
         "to the ISO on the Multi-boot tab first) or only one image from that "
         "image's own install ISO, and keeps the settings and scores; both "
         "images must be the same game version, and the dialog checks the "
         "disk really is this install before a byte is written."),
    ],
    "Mod Pack": [
        ("What it's for",
         "Mod packs are zips holding only your modified files, so a mod is "
         "small enough to hand to someone else. The Project Folder shown at "
         "the top is the same one every Replace tab and the Write tab work "
         "out of — packs export from it and import into it."),
        ("Export",
         "Export bundles everything you've changed (versus the extract "
         "baseline) into a single shareable mod-pack file. That means ALL "
         "your changes to this folder since you last extracted it — not "
         "just the ones made this session — so a mod built over many "
         "sittings exports in one go. Re-running Extract into a folder "
         "makes its current contents the new baseline, so export before "
         "you re-extract, and keep each firmware version in its own "
         "folder."),
        ("Import",
         "Import applies a mod pack onto a matching extract — the pack "
         "records which game/version it was made from, and only files this "
         "extract actually has are written. A pack built from another card "
         "(an LE pack onto a Pro extract, say) keeps its sounds and art in "
         "different places, so most of it fits nothing here: those files are "
         "skipped and counted rather than dropped into the folder, where they "
         "would list as slots no build can use. Use \"Transfer mods\" for that "
         "instead.\n\nThe confirmation before an import counts the skips, and "
         "a \"Details\" button on it opens the full list — every file that "
         "won't be applied, each with the reason it isn't: either your "
         "extract has no such file (it stays in the zip, untouched), or it's "
         "a stray this import will take back out of the project folder. The "
         "log names them one per line as well, so the same list is still "
         "there to read after the dialog is gone.\n\nYour staged Defaults, high-score defaults and the names "
         "you gave image groups and scenes ride along in the pack as well — "
         "they are project settings rather than files, so they are keyed by "
         "the firmware's own names and land staged for the next Build. One "
         "thing no import can APPLY: files you replaced on the card image "
         "itself with the Partitions tab (SternLogo.png and friends). Those "
         "are written into the .raw rather than into the project folder, and "
         "putting one back means resizing inside the card's own filesystem. "
         "The pack carries your copies anyway, as long as the file you "
         "swapped in is still on this PC: Import drops them into the "
         "project's card_files folder under the same on-card path, so it is "
         "one right-click Replace on the Partitions tab. If that file has "
         "moved since, Import can only name it for you to redo."),
        ("Port + build (one click)",
         "\"Port + build onto card image(s)...\" runs the whole chain for "
         "you: pick one or more STOCK card images — the new firmware "
         "version, the other model of the same title (Pro to Premium/LE or "
         "back), or several at once — and for each one the app extracts the "
         "card, transfers this project's mods onto it, and builds its "
         "modded image, unattended, one after another. Each card's extract "
         "folder is created next to the built images and reused on the next "
         "port, so re-shipping after a small change skips straight to the "
         "transfer and build (which the Write's own caches make fast). "
         "Audio slots whose index now holds a different sound are skipped "
         "automatically (the safe choice); everything skipped or dropped is "
         "named in the log, per target, exactly like the step-by-step "
         "transfer below."),
        ("Transfer mods",
         "\"Transfer mods from another extract\" (where available) carries "
         "your Replace edits from an older firmware's extract onto a new "
         "version's extract. Audio is matched by content signature, so it "
         "survives renumbered slots and renamed files. Before the confirm "
         "dialog opens, the log lists the whole plan slot by slot: every sound "
         "that moved to a new index, both ends of the move, and everything "
         "that can't be carried with the reason why — nothing is silently "
         "dropped. Text works the same way: any string the two old-version "
         "extracts can't be lined up on is quoted in the log under the asset "
         "it came from, with which of the two extracts it was in, so a skipped "
         "count is something you can actually check your own edits against. "
         "The log stops that list at 40 so a big card can't push everything "
         "else out of the pane; the complete list, every string in full, is "
         "written to unmatched-text.txt in the new extract's logs folder and "
         "the log line right after it says where. "
         "Your staged "
         "Defaults (settings and high-score slots) come along too — those "
         "are keyed by the firmware's own names, and the build skips any "
         "the new image doesn't have.\n\nRunning the same transfer onto "
         "the same folder again REPLACES the earlier run rather than "
         "adding to it: anything that run staged and this one doesn't "
         "find goes back to the slot's original, and anything you "
         "re-pointed yourself since is kept. The confirm dialog says how "
         "many assignments are about to be replaced.\n\nThe same thing works between the "
         "two models of one game: point it at your Pro/Prem/LE extract and "
         "a fresh extract of the other model, and what they share moves "
         "over.\n\nFields 1 "
         "and 3 are never alternatives, and neither takes priority: field 1 "
         "(your old extract) is where your mods come FROM and is always "
         "required; field 3 is an optional clean, unmodified twin of that "
         "same old version, used only as the reference your old extract is "
         "compared against — with it, the factory's own between-version "
         "changes aren't mistaken for your mods, and audio + text mods can "
         "be carried too.\n\nIf your old extract came off a card THIS app "
         "built, the mods already baked into that card are the folder's "
         "starting point rather than replacements, so on its own the "
         "transfer carries only the replacements you assigned inside that "
         "folder - the confirm dialog and the log both say so. Fill field 3 "
         "with a stock extract of that card's own code and it offers to "
         "carry BOTH in one run: the baked-in mods first, compared against "
         "that stock extract, then this folder's own replacements on top, "
         "which win on any slot the two share by being the newer round. "
         "Each pass keeps its own confirm, and turning the first one down "
         "still runs the second."),
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
                     "settings: Stern stores them on the board, not the card.",
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
        ("What it does",
         "Runs a Stern Spike 1 game on this PC — the 2015-2016 dot-matrix "
         "generation (WrestleMania, KISS, Game of Thrones, Ghostbusters, and "
         "more), and the earlier 2012 home models (Transformers The Pin), which "
         "have no dot matrix at all but two 8-digit 16-segment alphanumeric "
         "displays. The game is a static ARM program, so it runs "
         "under a patched emulator with a software model of the machine's "
         "boards — no CPU it can run natively, unlike JJP. Pick a Spike 1 card "
         "image, press Start, and it boots the way the machine does, straight "
         "to its own attract on its own kind of display, with sound."),
        ("It needs WSL and runs as root there",
         "The board model needs a privileged host setup, so this tab is "
         "Windows-only and runs the emulator inside WSL with root (which on "
         "Windows needs no password). The first Start installs the emulator: "
         "the ARM emulator and the board model are binaries built and checked "
         "as part of this app, downloaded once and verified against the exact "
         "version this app expects, so nothing is compiled on your machine and "
         "no packages are needed. Later starts are quick, and switching to a "
         "different card you've already picked before reuses its extraction. "
         "It can also bring its own Linux: pressing Fix setup installs a "
         "private WSL distro called PAD-Runtime with the emulator already in "
         "it, so your own distro is not touched and a PC with WSL enabled but "
         "no distro installed at all can still run a game. That is a one-time "
         "download of about 414 MB, and Start never does it for you — Fix "
         "setup here, or “Update emulator Linux…” on the Stern Spike 2 "
         "Emulate tab, which appears there when the installed one is from an "
         "older version of this app. "
         "Everything the app sends to Linux now goes to that runtime once it "
         "is installed, not only the emulators: the extract and write "
         "pipelines, the disk tools and the card builder run there too, which "
         "is why the prerequisite list finally describes the same machine the "
         "work happens on. "
         "Set PAD_RUNTIME=0 if you would rather everything used the machine's "
         "default distro."),
        ("Fix setup, if anything is missing",
         "Fix setup installs whatever the emulator is missing and then says "
         "what, if anything, is left — no terminal, either way. If your "
         "network blocks the download (a firewall, or a proxy that allows "
         "github.com but not its download host), it offers a file picker "
         "instead: fetch the file on any other machine and it is checked "
         "against the same checksum before it is installed. Start does the "
         "same install by itself, so pressing this first is only needed when "
         "something has gone wrong. Right-click it to give space back "
         "instead: \"Delete the emulator's data\" (the extracted games, "
         "card caches and save states), \"Delete downloaded files\" (the "
         "emulator binaries and the runtime image, all re-downloadable), and "
         "\"Remove the app's Linux\" (the PAD-Runtime distro itself). Each "
         "says what it will destroy before it does it, refuses while a game "
         "is running, and reports how much it freed. The emulator's work "
         "lives on a disk of its own, so removing the runtime does not take "
         "your save states with it."),
        ("Play a game",
         "A display window shows what the machine is showing — the dot matrix, "
         "or, on a 2012 home model, its two 16-segment displays side by side "
         "with the text they spell out underneath. A switch/LED window opens "
         "beside it listing every switch by name and position, not a bare grid; "
         "a title with no built-in map is no longer stuck on the nameless grid, "
         "because the names are read out of the running game itself, which is "
         "also why those switches now actually do something. "
         "Play with the keyboard (works in the display window) — arrow keys are "
         "the flippers, 1 starts, 5 coins up, T tilts, and there's a full legend "
         "in the window — or click a switch to pulse it briefly, the way a ball "
         "rolling over it would (right-click to hold one closed). The coin door "
         "and service buttons are drawn as on the real door, and the trough "
         "shows each ball position; coining up and pressing Start actually "
         "serves a ball, so you can play a full game start to finish."),
        ("The 2012 home models have no coin door",
         "Transformers The Pin and its siblings have no coin door, no service "
         "buttons and no operator menu, so on those titles the service cluster "
         "and the coin-door bar are drawn dead and the bar says what to do "
         "instead: test mode is both flippers held for three seconds. Their "
         "sound also runs at the rate the game's own DAC asks for rather than "
         "CD rate, so the speaker no longer starves into silence."),
        ("Volume and Default Settings",
         "The Volume slider and Mute checkbox are this tab's own speaker "
         "control (not the game's in-game volume, which is on the coin door "
         "like the real machine) and take effect immediately on a running game. "
         "Default Settings — the operator adjustments baked into the card — is "
         "a separate tab from Emulate and works without the emulator running at "
         "all."),
        ("Save states",
         "Save now snapshots the running game — mid-ball, mid-mode — into a "
         "named slot (the game freezes for a second or two while it writes, "
         "then keeps playing). Load swaps the running game for the selected "
         "slot, even in a later session after a full stop and restart: the "
         "game resumes right where it was, display, switches and sound live. "
         "Slots are per title (a slot loads only into the title it was saved "
         "from), take roughly 15-50 MB each on the WSL disk, survive emulator "
         "rebuilds, and stay until deleted — Rename and Delete manage them "
         "from the same list."),
        ("If it gets stuck",
         "\"Restart WSL…\" force-restarts WSL to clear a wedged emulator — a "
         "frozen window or a game that will not stop. It closes all WSL sessions "
         "and takes about 15 seconds; your card and settings are untouched."),
    ],
    "Emulate JJP": [
        ("What it does",
         "Runs the real Jersey Jack game on this PC — in its own resizable "
         "window, with sound. The game is a native x86-64 Linux program, so "
         "unlike the Stern emulator there is no CPU emulation involved: it "
         "simply runs. Pick a JJP game ISO, press Start, and it boots the way "
         "the machine does — through its own startup into attract mode."),
        ("You need the purple USB key",
         "The JJP security key is not optional and cannot be worked around. "
         "The game's program code is ENCRYPTED, and the key holds the "
         "decryption key — so without it the game stops immediately with "
         "\"Sentinel key not found\", exactly as a real machine does with the "
         "key unplugged. The key is also per-game: the key from one JJP title "
         "will not start another. Plug it into this PC before pressing Start; "
         "the app hands it through to the emulator for you."),
        ("Your game image is never modified",
         "The ISO is mounted READ ONLY and the game runs against a temporary "
         "overlay held in memory. Everything it writes while running — its "
         "settings, its high scores, the manual pages it renders on first "
         "boot — is discarded when you stop. You can always start again from a "
         "known state, and a crashed run cannot corrupt the image."),
        ("Switch matrix",
         "Once the game is running, \"Switch matrix…\" opens the playfield "
         "with every switch and light on it, drawn on the game's own playfield "
         "photograph. Left-click a switch to trigger it the way a ball rolling "
         "over would (a brief pulse); right-click to hold it closed, which is "
         "what you want for balls sitting in the trough or the coin door. The "
         "game reacts exactly as it would on the machine."),
        ("First start is slow",
         "The first Start on a given ISO restores the game filesystem out of "
         "it, which is several GB and takes a few minutes. That result is "
         "cached, so every later Start on the same ISO is quick."),
        ("If there is no sound",
         "WSL has no sound card, so the emulator routes audio through "
         "Windows. If music sounds wrong, judge it by ear rather than by a "
         "test tone — the audio path is known to pass a plain tone cleanly "
         "while distorting music."),
    ],
    "Emulate DP": [
        ("What it does",
         "Runs the real Dutch Pinball game on this PC - The Big Lebowski or "
         "Alice's Adventures in Wonderland - in its own window (Alice opens "
         "two: the main screen and the round one). The emulator stands in "
         "for the machine's controller board and gives the game what the "
         "machine's disk gave it, a window, sound, and a way to press every "
         "switch, and it boots into attract mode."),
        ("Which files to pick",
         "The machine's disk image (.img; for Alice, the full_image "
         "installer) - it is the only place most of the "
         "game's pictures and sounds exist; the update zips carry only what "
         "changed. The first Start copies the game out of the image (several "
         "GB, a few minutes); the next is quick. Optionally add an update "
         "(.zip, The Big Lebowski only): the official one, or one the Write "
         "tab built from your "
         "edits. It is laid over the version on the image the way the "
         "machine installs it, so you can play a mod before it goes on a USB "
         "stick. Both files are only read."),
        ("Playing",
         "When the game is up its switch window opens beside it: the game's "
         "own drawing of the machine with every switch on it (for Alice, a "
         "list), and a list of them all by name. Hold a switch with the "
         "mouse (a flipper, a ball resting in the scoop); right-click to "
         "latch it until you right-click again. With that window focused "
         "the game's own keys work: for The Big Lebowski N and M are the "
         "flippers, 1 is Start, 3 a coin and 7, 8, 9, 0 the service buttons; "
         "for Alice the Shift keys are the flippers, 1 is Start and 7, 0, 8, "
         "9 are Escape, Enter and the volume. Closed it? "
         "\"Switches window\" on this tab brings it back."),
        ("Cancel",
         "While a game is starting the Start button is Cancel: it stops the "
         "copy off the image and throws away the half-copied game."),
    ],
    "Emulate BoF": [
        ("What it does",
         "Runs the real Barrels of Fun game on this PC - Dune, Winchester "
         "Mystery House or Labyrinth - in its own window. The game is a "
         "native Linux program, so nothing is emulated but the machine's "
         "boards: the emulator answers the game the way the FAST controller, "
         "its lighting boards and (on Dune and Winchester) BoF's own mechanism "
         "board would, so it boots through its hardware check into attract "
         "mode. Bon Jovi can't be emulated yet: its .fun is a signed disk "
         "image and the emulator has no board profile for it; Image Info "
         "says how an owner can help."),
        ("Which file to pick",
         "The .fun update file - the one the machine installs from a USB "
         "stick. That can be the official file, or one the Write tab built "
         "from your edits: emulating it first is the quick way to check a mod "
         "before it goes on a stick. The file is only read."),
        ("Playing",
         "When the game is ready its switch window opens beside it: the "
         "game's own playfield drawing with every switch on it, and a list "
         "of them all by name. Hold a switch with the mouse (a flipper, a "
         "ball resting in a scoop); right-click to latch it until you "
         "right-click again. Plunge puts the ball in the shooter lane into "
         "play, Drain sends one back to the trough, and Coin door opens or "
         "closes it. With that window or the game's own window focused, Z "
         "and / (or the Shift keys) are the flippers, 1 is Start, 5 a coin, Space Launch, P Plunge and "
         "D Drain. Closed it? \"Switches window\" on this tab brings it "
         "back. The game's own window can be moved and resized like any "
         "other; the picture scales to fit."),
        ("Cancel",
         "While a game is starting the Start button is Cancel. A build on a "
         "slow or busy drive can take a long time to unpack; Cancel stops "
         "it and throws the half-unpacked copy away."),
        ("First start is slower",
         "The first Start on a file unpacks it (2-4 GB) inside the app's "
         "Linux, which takes a minute or two. The last two builds are kept, "
         "so starting the same file again is quick; a rebuilt mod is "
         "unpacked fresh."),
        ("Settings and high scores",
         "Each game keeps its own settings, audits and high scores between "
         "runs, as a machine does. Sound follows Mute; the game's own volume "
         "is in its service menu."),
    ],
    "Emulate AP": [
        ("What it does",
         "Runs the real American Pinball game on this PC - Houdini, "
         "Oktoberfest, Hot Wheels, Legends of Valhalla or Galactic Tank Force "
         "- in its own window, with its sound. The game carries its own "
         "stand-in for the machine's controller board; the emulator gives it "
         "what the machine's computer did (the Python it runs on, a full "
         "trough, the coin door shut) and a way to press every switch, and "
         "it boots into attract mode."),
        ("Which file to pick",
         "The game-code file (.pkg) - the one the machine installs from a "
         "USB stick. That can be American Pinball's own, or one the Write "
         "tab built from your edits: emulating it first is the quick way to "
         "check a mod before it goes on a stick. The file is only read."),
        ("Playing",
         "When the game is up its virtual playfield opens beside it - the "
         "same window as the Stern Emulate tab's. Where the game has a "
         "playfield picture (Legends of Valhalla, Houdini, Galactic Tank "
         "Force) its switches and lights are drawn on it, the lights lit in "
         "the game's colours; otherwise its lights show as a grid and its "
         "switches as a list. A green dot is a switch the game sees made. "
         "Hold a switch with the mouse; hold the right button on one to rip "
         "it (a spinner spinning), as on Stern. There is no ball physics: Start "
         "serves a ball to the shooter lane, Plunge puts it into play, you "
         "press the switches it would hit, and Drain sends it back to the "
         "trough, ending the ball - unless the game's ball save is still "
         "running (the first seconds after the ball reaches the playfield, "
         "12 on Legends of Valhalla), when it serves the ball again, as the "
         "machine would. With that window or one of the game's own windows "
         "focused, the arrow keys are the "
         "flippers, 1 is Start, 5 a coin (two or four make a credit), Space "
         "the Action button, T tilt, the letters beside the playfield "
         "switches press them, F plunges, D drains, C opens and shuts the coin "
         "door, Backspace, -, = and Enter are the service buttons, and Pause "
         "or F9 (in the playfield window) freezes the game. Closed it, or "
         "lost it behind the game? The \"Playfield window\" button beside "
         "Stop brings it back to the front."),
        ("First start is slower",
         "The very first Start sets the emulator up inside the app's Linux: "
         "it downloads the Python the games run on (about 1 GB, a few "
         "minutes, once). Until that is done the tab says so, with a \"Set "
         "up emulator…\" button that does it now; the same button installs "
         "the app's own Linux when this PC does not have it yet (the game "
         "would otherwise run in this PC's own WSL distro, which this "
         "emulator is not built for). Each new .pkg is then unpacked once (under a "
         "minute) and kept, so starting it again is quick; a rebuilt mod is "
         "unpacked fresh. While a game is starting the Start button is "
         "Cancel."),
        ("One at a time",
         "Hot Wheels and Galactic Tank Force play their pictures and sound "
         "through American Pinball's own player, which only one game at a "
         "time can use. Barry-O's BBQ Challenge does not run here yet. "
         "Volume and Mute change the game's sound while it plays; the game's "
         "own volume is in its service menu."),
        ("Stopping",
         "Stop ends the game and closes its switch window. So does closing "
         "any of the game's own windows with its X."),
    ],
    "Emulate Spooky": [
        ("What it does",
         "Runs the real Spooky Pinball game on this PC, in its own window, "
         "with its sound. Supported: Beetlejuice, Scooby-Doo, Texas "
         "Chainsaw Massacre, Evil Dead, Looney Tunes, Halloween, Ultraman, "
         "Rick and Morty and Alice Cooper's Nightmare Castle. "
         "The DMD games Jetsons, Domino's and Rob Zombie run from their "
         "update zip (Jetsons_Code.zip, DOM_v6.zip, rzupdate_V26.zip) in a "
         "window of their own - the display, every switch, the balls and "
         "the sound - without the app's Linux. "
         "Not yet: Total Nuclear Annihilation, whose update cannot be opened "
         "yet, and America's Most Haunted, whose update carries no game "
         "program. "
         "These games run on this PC as they are, so nothing is emulated but "
         "the machine's controller board: the emulator answers the game the "
         "way that board would, with a full trough, and gives you a way to "
         "press every switch. The first Start of Rick and Morty or Alice "
         "Cooper also downloads the Python those two are written in (once, "
         "a few minutes)."),
        ("Which file to pick",
         "The game's update file - the one the machine installs from a USB "
         "stick, named as the machine wants it: v….beetlejuice, v….scooby, "
         "….ed, ….looney, tcm-….pkg (Texas Chainsaw), code_H78.pkg "
         "(Halloween), code_UM.pkg (Ultraman), rm-gamecode-….pkg (Rick and "
         "Morty) or ac-gamecode.pkg (Alice Cooper). The emulator tells the "
         "games apart by that name. It can be the official file, or one the "
         "Write tab "
         "built from your edits: emulating it first is the quick way to check "
         "a mod before it goes on a stick. The file is only read."),
        ("Playing",
         "When the game reaches attract mode its virtual playfield opens "
         "beside it - the same window as the American Pinball and Stern "
         "Emulate tabs'. The Spooky games ship no playfield picture, so "
         "their switches are a list; a green dot is a switch the game sees made. "
         "Hold a switch with the mouse; hold the right button on one to rip "
         "it (a spinner spinning). There is no ball physics: Start serves a "
         "ball to the shooter lane, Plunge presses the Launch button and the "
         "game fires the ball into play, "
         "you press the switches it would hit, and Drain sends it back to "
         "the trough, ending the ball - unless the game's ball save is still "
         "running, when it serves the ball again, as the machine would. With "
         "that window focused, the arrow keys are the flippers, 1 is Start, "
         "5 a coin, Space the Launch button, Down the Action button, T tilt, "
         "the letters beside the playfield switches press them, F plunges, D "
         "drains, Backspace, -, = and Enter are the service buttons, and "
         "Pause or F9 freezes the game. The same keys work in the game's own "
         "window, except the ones the game uses there itself (Beetlejuice: "
         "Enter starts, Space launches, the arrows flip). Closed the "
         "playfield? \"Playfield window\" beside Stop brings it back."),
        ("Volume",
         "Volume and Mute on this tab (and the VOL bar in the playfield "
         "window) set Predator's sound live, as on every Emulate tab. The "
         "game's own volume is in its service menu. Alien and ABBA have no "
         "sound in the emulator yet."),
        ("Cancel and Stop",
         "While a game is starting the Start button is Cancel; it stops the "
         "start and throws a half-unpacked copy away. Stop ends the game and "
         "closes its playfield window; so does closing the game's window."),
        ("Starting takes a while",
         "The first Start on a file unpacks it (Predator about 5 GB, Alien's "
         "restore image about 3.5 GB, a full Alien or ABBA update about "
         "2.5 GB) inside the app's Linux, which takes a few minutes; the "
         "result is kept, so starting "
         "the same file again skips that. Cache... beside Browse... shows "
         "what is kept and deletes it. Loading the game itself then takes a "
         "minute or two, as it does on the machine. It draws on this PC's "
         "graphics card (through WSL); on a PC where WSL has no graphics "
         "card it draws on the processor, and the picture is much slower."),
        ("Settings and high scores",
         "The game keeps its settings, audits and high scores between runs, "
         "as a machine does."),
    ],
    "Emulate PB": [
        ("What it does",
         "Runs the real Pinball Brothers game on this PC, in its own window. "
         "Supported: Predator, Alien, ABBA and Queen. Each game is two "
         "native Linux programs (the rules and the screen), so nothing is "
         "emulated but the machine's controller boards - Predator's FAST "
         "boards, or the I/O boards Alien, ABBA and Queen share: the "
         "emulator answers the game the way those boards would, with six "
         "balls in the trough, and gives you a way to press every switch. "
         "ABBA's screens stay dark: its update files carry the program and "
         "the sound, not the pictures and videos the factory installed."),
        ("Which file to pick",
         "The .upd update file for the version you want to play - the one "
         "the machine installs from a USB stick. Pinball Brothers ships one "
         "full update (pbpp_predator_game_1_0.upd) and then smaller "
         "follow-ups that carry only what changed "
         "(pbpp_predator_game_1_0_1.upd). Pick the follow-up to play that "
         "version; the full update must be in the same folder, and the "
         "emulator uses both. Alien and ABBA work the same way (pbap411.upd "
         "then pbap412.upd for Alien, pbap141.upd then pbap145.upd for "
         "ABBA), and also need Alien's restore image "
         "(clonezilla-live-alien40.iso) in that folder the first time: it "
         "is the machine's own Linux, which both games run on. Queen's "
         "updates (pbq0210G.upd) carry only what changed, so Queen needs "
         "its own restore image (clonezilla-live-queen20d.iso, about "
         "10 GB) beside them: it holds Queen's pictures, videos and sound. "
         "Pick a restore image itself to play the game as it left the "
         "factory. The files are only read."),
        ("Setting up",
         "The first time, the emulator downloads the libraries Predator "
         "needs for its sound and video (about 700 MB) into the app's "
         "Linux; Alien and ABBA need none. \"Set up emulator...\" does that ahead of time; otherwise "
         "the first Start does it."),
        ("Playing",
         "When the game reaches attract mode its virtual playfield opens "
         "beside it - the same window as the American Pinball and Stern "
         "Emulate tabs'. These games ship no playfield picture, so their "
         "switches are a list; a green dot is a switch the game sees made, "
         "and the lights are the LEDs the game has lit. Hold a switch with "
         "the mouse; hold the right button on one to rip it (a spinner "
         "spinning). There is no ball physics: Start serves a ball to the "
         "shooter lane, the Launch button (Space) fires it into play, you "
         "press the switches it would hit, and Drain sends it back to the "
         "trough. Queen has no Launch button: both flippers launch, and "
         "also start the song picked on the song select each ball begins "
         "with (F does both). With that window or the game's own window "
         "focused, the "
         "arrow keys are the flippers, 1 is Start, 5 a coin, Space the Launch button, T tilt, "
         "the letters beside the playfield switches press them, F plunges, "
         "D drains, Backspace, -, = and Enter are the coin door's buttons, "
         "and Pause or F9 freezes the game. Closed the playfield? "
         "\"Playfield window\" on this tab brings it back."),
        ("Volume",
         "Volume and Mute on this tab (and the VOL bar in the playfield "
         "window) set the game's sound live, as on every Emulate tab. The "
         "game's own volume is in its service menu."),
        ("Cancel and Stop",
         "While a game is starting the Start button is Cancel; it stops the "
         "start and throws a half-unpacked copy away. Stop ends the game and "
         "closes its playfield window."),
        ("Starting takes a while",
         "The first Start on a file unpacks it (Predator about 5 GB, Alien's "
         "restore image about 3.5 GB, a full Alien or ABBA update about "
         "2.5 GB) inside the app's Linux, which takes a few minutes; the "
         "result is kept, so starting "
         "the same file again skips that. Cache... beside Browse... shows "
         "what is kept and deletes it."),
        ("Settings and high scores",
         "The game keeps its settings, audits and high scores between runs, "
         "as a machine does."),
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
         "- **Two-hour cap:** it stops by itself, so a forgotten window cannot run all "
         "night."),
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
            "- **Down the right:** the keyboard reference (a row lights when the game "
            "sees that switch), the coin-door buttons (click and hold **BACK**, **-**, "
            "**+**, **SELECT** for the operator menu), a coin door open/close button "
            "(open cuts 48V, like the real interlock) and the ball trough, each "
            "position clickable.\n"
            "- The keyboard works with this window focused too.\n"
            "- It builds itself from the title, so every Spike 2 game gets one. The "
            "switches appear a minute or so into a run, once the game lists them.\n"
            "- **Pause** (or F9), in either window or on the bottom bar, freezes the "
            "whole game, video and sound too. **Resume** carries on from that frame. "
            "The bar also has Volume and Mute.",
        ]),
        ("Save states", [
            "**Save state** on the playfield window (Windows) checkpoints the whole "
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
            "emulator…** gets both.",
            {"note": "Each slot takes about 50–150 MB of the WSL disk, and a save briefly "
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
        ("Black game window",
         "On Windows the usual cause is a WSL that logs in as **root**: the renderer "
         "cannot reach WSLg's shared memory and draws nothing, while sound, switches "
         "and the playfield all work.\n\n"
         "- **Check setup…** names it. The cure is on the WSL side: give the distro an "
         "ordinary user, make it the default, restart WSL. The rig will not guess a "
         "user for you.\n"
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
                     "it asks first and is greyed out while a run is up: stop the game "
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
            "after its card file. Cancelling, or saying no to an overwrite, stops the "
            "pair there; card B is not left queued.",
        ]),
        ("Adjustments and high scores",
         "Both game programs are read the same way the Defaults tab reads them: "
         "settings added or removed, defaults that changed, and high-score places "
         "whose initials, name or score changed. These are the cards' built-in "
         "defaults; a machine's live settings and scores are in its own memory."),
    ],
    "Multi-boot": [
        ("What it does",
         "Builds ONE SD card that carries several complete Spike 2 game "
         "images and shows a menu at power-up: the flippers move the "
         "highlight, START boots the highlighted image, and a countdown "
         "boots the remembered choice by itself. Stock code and a custom "
         "build (or two builds) live on the same machine without swapping "
         "cards. The first image in the list is the primary — its boot "
         "files are the card's, and the machine falls back to it if the "
         "menu ever fails. Up to 16 images fit one card, and from five "
         "the menu scrolls three at a time, with a counter under them and "
         "a chevron in each margin, so "
         "a card is not limited to what fits on the screen at once. One "
         "card in the menu can also stand for SEVERAL games and boot one "
         "of them at random - see \u201cA card that picks for you\u201d below."),
        ("A card that picks for you",
         "Add image or random\u2026 at the foot of the list offers three "
         "more things beside a plain image: a random card over the images "
         "already on the card, a random card with games of its own, and "
         "the same from a whole folder of them. Either way it is ONE card "
         "in the menu, and choosing it - by hand or by the countdown - "
         "boots one of its games. Forty song-set variants of one title "
         "become one card that looks completely standard and plays a "
         "different set every power-up. A random card over images that "
         "keep their own cards is \u201csurprise me\u201d beside the very builds "
         "it rolls between."),
        ("A base card plus an edits folder",
         "A song set does not need a whole 8 GB card of its own. Add "
         "image or random… also offers Add base card + edits "
         "folder…: the stock card plus a folder of the files a song "
         "set changes, and only those files go on the card, with everything "
         "else read "
         "from the base. Add random group from edits folders… takes one "
         "stock card and a folder of those sets - the jukebox card. Both "
         "check the pair before the row goes in and say why when they "
         "refuse it (a set edited from a different card, from another "
         "version of the app, half-built, or changed since), and both "
         "lock Compact build on."),
        ("How a random card picks, and what it looks like",
         "Edit image\u2026 on a random row asks two questions an ordinary "
         "image does not. HOW IT PICKS: truly random (100% random, so it "
         "can give you the same one twice) or shuffle (cycle through every "
         "game before any of them repeats, remembered across power-ups the "
         "way a music player does it), and under the two a tick for "
         "\u201cnever the one it booted last\u201d \u2013 greyed on under a "
         "shuffle, which never gives you the one it just booted "
         "anyway. AND WHAT IT SHOWS: the games\u2019 own "
         "logos fanned out like a hand of cards, in a pile, as a grid, "
         "under a big \u2018?\u2019, the shuffle symbol, each logo in turn, a slot "
         "reel that spins and settles, a picture file of your own, or "
         "nothing. It has its own music and confirm sound too. Press "
         "Select under the preview to see what the machine draws when the "
         "card is chosen: the build the roll landed on, named. Its Games "
         "box changes WHICH games it holds without removing the row: a "
         "card with games of its own takes Add files… (several at "
         "once) or Add folder…, and moves or removes them; one over "
         "images already on the card ticks the ones it uses. It always "
         "keeps at least two, and the change asks for a rebuild."),
        ("The tab, top to bottom",
         "One column, and it never rearranges itself under the window: the "
         "card path first, with From SD card…, Browse… and New card beside "
         "it, because reading a card you already built is usually the "
         "first thing you do here. Then the PREVIEW, the full width of the "
         "tab — the boot menu drawn by the selector itself. Then the "
         "IMAGES TABLE under it, one row per image, with four checks above "
         "it — Card image, Images, Built, Ready to flash — each with the "
         "sentence behind its mark. Then the SIZE STRIP: which SD card the images "
         "need, the Compact build tick, and a bar of what fills the card. "
         "WHEN THE CARD YOU NEED IS BIGGER THAN THE GAMES ON IT the line "
         "adds the two numbers up rather than leaving you to - 10.83 GB "
         "of games + 6.21 GB free for updates = 17.65 GB, so 32 GB and "
         "not 16 GB - and the words and the bar carry the rest on their "
         "tooltip: what the smaller card really holds, that the free room "
         "is what lets an image be updated in place rather than rebuilt, "
         "that the first image's card is copied whole, and that Compact "
         "build is the tick that shrinks it. "
         "Then one bar: Menu settings… and Recover images… on the left, "
         "and on the right ONE green button, Build / flash card…, beside "
         "Run in emulator. "
         "Everything the tools print goes to the Log at the foot of the "
         "window, beside the other tabs', and the footer's stages and "
         "progress bar are this tab's own while you are on it."),
        ("The card path, and the three buttons beside it",
         "The path box IS the card this tab is pointing at, and it means "
         "both things a card path can mean. A path with a card already at "
         "it is one you can read: pick it with Browse…, or type it and "
         "press Enter, and every field fills from it — the tab is then "
         "editing THAT card. A path with nothing at it yet is where Build "
         "/ flash card… will write a new one. Browse… covers both — it "
         "takes a card that exists and a name that does not — and picking "
         "an existing card there reads it straight away (it asks first if "
         "you have unsaved changes, and answering no leaves the box "
         "alone). Typing alone never reads a card, because on the way to "
         "typing one name you pass through another that exists. From SD "
         "card… reads the card in the reader, and asks which read you "
         "want: the boot menu only — titles, pictures, sounds, settings "
         "and where the images came from, without an image file; only the "
         "menu's part of the card is read, so the games' versions are not "
         "shown, and Build / flash card… then writes the menu back onto "
         "that card — or the whole card, into a .raw you name, which then "
         "loads like any card on disk (its images can be recovered, "
         "replaced or added to, and the Build / flash dialog's flash "
         "section puts it back). The checks above "
         "the table always say which of these you are in, and what the "
         "green button would do about it. Point the box somewhere else "
         "while a card is loaded and the tab simply stops claiming to be "
         "editing it — nothing is thrown away, and typing that path back "
         "picks it up again. New card is the one way to empty the tab; "
         "clearing the path does not, because people clear a path to "
         "retype it. The whole form — the path, the images and the menu — "
         "comes back the way you left it on the next launch, per project, "
         "the way the Emulate tab's card does; it comes back OUT of editing "
         "mode, and nothing is read or run to restore it."),
        ("A card someone else built",
         "A multi-boot card you were given loads like any other and draws "
         "its own menu — but it names its images, and the videos and WAVs "
         "its pictures were made from, on the machine that built it, so "
         "the rows say \"not on this machine\" and nothing that needs the "
         "sources can run: no update in place, no rebuild, no third image. "
         "Recover images… is the way on. It writes each image back out of "
         "the card as a normal card image of its own (the game as its "
         "games partition, the boot menu taken out), named as the card "
         "records it, copies the card's pictures and sounds out beside "
         "them, and points the rows at those files — a recovery is not a "
         "change, so nothing reads as unsaved. From then on the card is "
         "one this machine built: Build / flash card… can update it in "
         "place, rebuild it, or write a fresh card with another image "
         "added. The button is greyed while every image is already on "
         "this machine, and for a card read from the reader as its menu "
         "only — read the whole card for that. Reads the card, writes only "
         "into the folder you pick."),
        ("The images table",
         "One row per image, in the order the menu will list them, and "
         "each row carries that image's own settings: its title and "
         "subtitle, its picture, its animation, its music, the sound that "
         "plays when it is chosen, and its game code version where that is "
         "known. The last row is dim and has a +: click it to add an "
         "image. Every row ends in four icons that act on THAT row — ✎ "
         "opens it, − takes it off the card, ▲ and ▼ move it (an outlined "
         "arrow means that row cannot go further that way). A "
         "double-click or Enter opens a row too, and a right-click offers "
         "the same five commands. The line under the table names the .raw "
         "the selected image was copied from."),
        ("One image's text and media",
         "✎ (or a double-click on the row) opens that image: its title and "
         "subtitle, ONE list saying what its card shows — the game's own "
         "logo, a picture file, the game's own attract video, a video "
         "file, or nothing at all — and its own music and confirm sound. "
         "A video is the still as well: the frame it starts on is what "
         "shows while the card is not highlighted. Whatever the list is "
         "on is drawn on the right of the dialog as the card the menu "
         "will put on screen, in the menu's own colours and with the "
         "title and subtitle under it, so a picture is a picture there "
         "and not a path to one. A random card's list offers the ways it "
         "can draw the games behind it instead."),
        ("Menu settings",
         "The button on the action bar opens everything that belongs to "
         "the MENU rather than to one image, and the line beside it "
         "already says what those are: the heading across the top of the "
         "menu, whether every card draws its text at the same size, "
         "whether the cards are counted under them, what the countdown "
         "line says, the move and confirm sounds (auto "
         "pulls a click and a stinger from the primary image, synth "
         "generates tones), the volume, the countdown (0 = wait for "
         "START), which image is highlighted at power-up, and the WSL "
         "path of the built selector — which you do not have to fill in. "
         "Leave it alone and the app builds and installs the menu program "
         "there itself; point it somewhere of your own and that directory "
         "is checked and never written into."),
        ("The SETTINGS card at the end of the menu",
         "End the menu with a SETTINGS card in Menu settings (Stern, on by "
         "default) puts one more card after the last image, with a gear on "
         "it, whenever an image's game carries an adjustable color profile; "
         "the preview draws it in exactly those cases, and a card built "
         "with v1.60.x shows none until it is rebuilt. On the machine, "
         "Settings > Color correction changes each game's color "
         "correction without a computer: Start from (As built, "
         "Recommended, No change, Black and white), middle shades and "
         "color level per channel, color strength and darkest shades, with "
         "the Color profile tab's test card on the glass corrected live as "
         "the values move, then Save for this game or Save for every game. "
         "The values reach the game at its next start - the game program "
         "is copied into RAM with the new numbers in its drawing shaders, "
         "the games partition is never written, and any failure runs the "
         "program as built. No countdown runs inside Settings; on the card "
         "the countdown boots the game the menu opened on, and two idle "
         "minutes leave Settings without saving."),
        ("The heading across the top of the menu",
         "Heading in Menu settings is the line the machine draws above "
         "the cards. It reads SELECT GAME CODE because that is what the "
         "menu says when nobody has changed it - the box shows what the "
         "card will actually say, never a blank standing in for it - and "
         "typing over it retitles the menu. EMPTYING IT IS A REAL ANSWER: "
         "a heading cleared here leaves the top of the menu bare. It is "
         "free text, one line, shrunk and then cut to the glass like every "
         "other line the menu draws, and the preview shows it the moment "
         "you stop typing. A card that never asked for a heading is "
         "written exactly as it always was."),
        ("The three lines under the cards",
         "A menu of five cards or more scrolls, and it counts the cards "
         "under them - the \u201c<  3 / 7  >\u201d line. Count the cards "
         "under them in Menu settings turns that line off for a menu whose "
         "cards are artwork of their own. Under it, Countdown says is the "
         "first word of the bottom line, the one the countdown runs on: "
         "\u201cstarting The Beatles in 9 s\u201d by default, and typing "
         "Launching or Booting over it says that instead. The example "
         "beside the box is the line itself, with the highlighted image's "
         "own name in it, so you can read what the machine will say before "
         "you write the card. EMPTYING IT IS A REAL ANSWER too: the "
         "countdown then names the game and the seconds and nothing else. "
         "A word of your own also replaces LOADING on the screen the "
         "machine shows while the chosen image starts. "
         "Neither is written onto a card that never asked for it."),
        ("The instructions line, and turning it off",
         "Between those two sits the line naming the buttons - \u201cLEFT / "
         "RIGHT FLIPPER: choose      START: boot\u201d. Show the "
         "instructions under the cards in Menu settings takes it off the "
         "glass, and the Instructions box under that puts your own words "
         "there instead. LEAVE THE BOX EMPTY AND THE MENU KEEPS ITS OWN "
         "LINE, which is not the same thing as typing that line out: only "
         "the menu's own wording follows the buttons the machine actually "
         "has, so a cabinet with an ACTION button on the lockdown bar is "
         "told about it and one without it is not. The line beside the box "
         "says which of the three you will get. A card that never asked for "
         "words of its own is written exactly as it always was."),
        ("Hearing a sound before the card is written",
         "Every sound row - the menu's move and confirm sounds in Menu "
         "settings, and an image's music and confirm in Edit image - has "
         "a \u25b6 Play beside its Browse\u2026. Press it and the sound "
         "plays here, through the preview's own volume and Mute. A WAV "
         "you pointed the row at plays straight off disk; a word (auto, "
         "synth, menu) plays the file the last preview rendered for THAT "
         "row, so auto on image 3 is image 3's own sound and not the "
         "highlighted image's. The Log says which file played and how "
         "long it was, and says why when nothing did - a row whose media "
         "has not been rendered yet is the usual reason, and ticking "
         "Sound under the preview is what renders it. An image's confirm "
         "sound is the one that plays WHEN YOU PRESS START on it, not as "
         "you scroll onto it: scrolling plays the menu-wide move click, "
         "which is why a confirm sound you set can sound as though it "
         "never took. THE TWO CONFIRM BOXES NAME EACH OTHER: they are "
         "one setting, an image's falling back to the menu's, so Edit "
         "image carries a line under the box naming the sound that image "
         "will actually play - the same name the list's Confirm column "
         "shows for that row, bracketed there when it is the menu's - "
         "and Menu settings names the images that carry a confirm sound "
         "of their own and so will never play the one in front of you."),
        ("Using one sound on every image",
         "Every sound row also LISTS the sound files this menu already "
         "uses, under its own words. Browse a WAV in once - for the "
         "menu's confirm sound, or for one image's music - and it is on "
         "the list in all four boxes, so putting the same clip on every "
         "image is a pick rather than a trip through the file dialog each "
         "time. They are listed by file name, because the list is only as "
         "wide as the box above it; picking one sets that file, exactly "
         "as Browse… would. Only files that are on THIS PC are offered: "
         "a card built on somebody else's machine loads with their paths "
         "in it, and those are not sounds this one can read."),
        ("The preview",
         "It redraws itself. Change anything — a title, the countdown, the "
         "art, the highlighted image — and about a third of a second after "
         "you stop, the selector draws that frame again under qemu. A text "
         "change costs one snapshot; only a media change makes the media "
         "be rendered again, and that is cached. It scales with the "
         "window, and it never greys the tab while it is drawing. "
         "Selecting a row in the table points it at that image. It is the "
         "same media the build will use, so the card carries exactly what "
         "you previewed. It draws itself when you open the tab and after "
         "every change, so there is nothing to press. THE VERY FIRST ONE "
         "ON A NEW PC TAKES A FEW MINUTES: the menu program is built "
         "against the machine's own filesystem, so that is unpacked from "
         "a card first. It happens once, the log says so while it runs, "
         "and every render after it is the third of a second above."),
        ("The flippers, the animation and the sound",
         "The two flipper buttons under the picture are the machine's: "
         "they move the highlight one card and wrap round at the ends, "
         "exactly as the flippers on the lockdown bar do, and the left and "
         "right arrow keys do the same once you have clicked the picture. "
         "Frame steps through the highlighted image's animation and Play "
         "runs it — the whole animation is drawn in one go and then played "
         "from memory at the clip's own frame rate. Sound plays what the "
         "menu plays: the highlighted image's music loop, and the move "
         "sound on a flipper press (never over itself, so a long one plays "
         "once however fast you flip), at the volume in Menu settings. It "
         "starts off — nothing opens a sound device until you tick it — "
         "and the sounds are the prepared media's own. While it is off the "
         "preview renders pictures and music only, so ticking it is also "
         "what asks for the move and confirm sounds: the media is prepared "
         "again in full and the sounds arrive when that run finishes. The "
         "picture's right-click menu also plays the highlighted image's own "
         "confirm sound, which is the one sound you cannot otherwise hear "
         "before the card is written."),
        ("Bypass game validation",
         "Always on, for every image on the card - there is no box to "
         "tick. The machine's validator would fail a modified image (GAME "
         "VALIDATION ERROR), and the images on one card share one saved "
         "grade, so a failure one image left behind would latch on the "
         "next. Every image gets its validator switched off and its saved "
         "grades ignored at boot, with that image's package index record "
         "refreshed - proven on a TMNT. A card that is already built is "
         "repaired by Apply / Update: any image still unpatched is patched, "
         "and the card is read back afterwards to say so - no rebuild, and "
         "no separate command."),
        ("Building one on a Mac",
         "A Mac can build these cards from v0.229.0, and it needs "
         "Docker Desktop to do it. The tools this tab runs are Linux tools "
         "\u2014 they loop-mount the card's partitions and write ext4 \u2014 and "
         "macOS has neither, so the app runs them inside a Linux container "
         "instead: it builds that container's image the first time you "
         "write a card and reuses it after that. That Linux is an x86-64 "
         "one on every Mac, Apple silicon as much as Intel, because the "
         "boot menu the card carries is an x86-64 program built against "
         "the machine's own libraries \u2014 so on Apple silicon the "
         "container runs emulated, and building its image the first time "
         "takes a few minutes rather than one. You are never asked for a "
         "password, because the container's own user is root. If Docker "
         "Desktop is not installed, or is installed but not running, the "
         "log says which and nothing is written; reading a card, the "
         "preview and the size strip need none of it. If a step fails, "
         "the log carries the container's own output, which is what to "
         "send on."),
        ("Build / flash card…, and what it decides",
         "One green button, and a dialog that says what it is about to "
         "do. With a new path in the box it builds a fresh card: every "
         "image copied in, the menu injected, and every copied range, "
         "file system and the injected selector verified afterwards. With "
         "a card you read back still in the box it is editing THAT card, "
         "and the dialog offers to update it in place: a changed title, "
         "picture or setting is rewritten into the menu in seconds, and a "
         "changed IMAGE — one video swapped inside a card you rebuilt with "
         "this app — is written as the difference, only the files that "
         "changed, in about a minute rather than a rebuild; the dialog "
         "says how many files and how much. Adding, removing or reordering "
         "images on a card built the older way needs a fresh card, and the "
         "dialog says so. Reading the card again re-syncs after something "
         "else changed it and throws unapplied edits away. Below the "
         "choice, the tick under Flash to an SD card writes the finished "
         "image onto an SD card in the same run. WHICH CARD is picked in "
         "the next dialog: Start opens the SD-card picker the Write tab "
         "uses, and nothing is written to any card until you have chosen "
         "one there and confirmed — Windows asks for administrator access "
         "for that write. That dialog only writes this tab's card: it has "
         "no Build section (that builds the Write tab's own image) and "
         "never warns that nothing was modified. Only the boot menu starts "
         "ticked only for an image a flash from this app has already put "
         "onto an SD card; any other image starts with it off and is "
         "written whole, games and all — what an SD card needs the first "
         "time. Tick it yourself if your card already holds that image: it "
         "checks the card first. After a fresh build or an update in place "
         "no SD card holds the card yet, so it stays off; after an Apply "
         "that changed only the menu, the menu-only write is offered. "
         "Every one of these runs starts "
         "with a selector step: the menu program the card will carry is "
         "built and installed when this machine has not got one, unpacked "
         "from the image being built, and rebuilt when the app ships newer "
         "sources. It goes before the media, so a run that cannot get a "
         "menu program does not first spend a minute rendering pictures "
         "for one — and if any step refuses, the Log line it refused with "
         "is what the tab says, naming the step."),
        ("The size strip and Compact build",
         "The strip under the table says which Stern card size the images "
         "need, before a byte is written: the tab asks the tool by itself "
         "whenever the image list changes, so it is never a stale answer "
         "from the last time somebody thought to check, and the bar shows "
         "what fills the card. Clicking the strip measures the list again, "
         "which is the way back from a check that failed or an image that "
         "has arrived since the list last moved. The sizes are walked through the BUILDER, "
         "one at a time, rather than estimated, so the size named here is "
         "the one the build will use and a compact card can no longer be "
         "offered a size the build would then refuse. When no Stern size "
         "fits, the strip carries the tool's own refusal - which "
         "partition ran out, by how much, and that the content wants a "
         "bigger card - cut to the line, with the whole sentence on the "
         "tooltip. Compact build (off by default) stores every "
         "file the images have in common only once — three images of one "
         "title that filled a 32 GB card fit a 16 GB one — and the bar "
         "hatches what that saves; the first time it is ticked the images "
         "are read through once, and the strip shows it thinking with the "
         "image's name and a percentage. A card built compact must be "
         "changed with this app, never with a Stern USB update, which would "
         "write through the shared files into every image at once."),
        ("Run in emulator",
         "Run in emulator starts the Emulate tab on the finished card with "
         "Boot selector ticked, so the same menu appears in the game window "
         "here first, and each image runs as it would on the machine. "
         "Everything runs under WSL and reports into the Log at the foot of "
         "the window, tagged [multi-boot]."),
        ("A Jersey Jack machine (multi-boot install stick, or the SSD)",
         "Pick Jersey Jack on the picker and the tab takes two JJP install "
         "ISOs of the same game code instead of card images - the stock "
         "code and a retheme built here, say - and Build / make stick... "
         "writes one multi-boot install ISO and turns it into an install "
         "stick (use a USB port on the computer in the backbox). The machine "
         "installs it as it installs any JJP stick, with the purple security "
         "key in, and from then on shows the menu at power-up: flippers "
         "choose, START or the Action button boots, the volume buttons set "
         "the menu's level, and a maintenance reboot boots the same image "
         "again without the menu. The stick dialog's Onto: row can install "
         "straight onto the game's SSD in a dock instead, and its Write: "
         "choice can then replace only the boot menu, or only one image from "
         "that image's own ISO, keeping the machine's settings and scores. "
         "Both images must be the same game version (they share one settings "
         "partition); the build refuses a mismatch and says why."),
        ("A Barrels of Fun machine (one update file)",
         "Pick Barrels of Fun on the picker and the tab takes the stock .fun "
         "of a game and up to three more builds of it - a mod, say - and "
         "Build update... writes ONE .fun under the game's own name (lab.fun "
         "for Labyrinth). Copy it onto a FAT32 USB stick and install it the "
         "way every Barrels of Fun update is installed: nothing is opened "
         "up. The install puts the first build in place, rebuilds the others "
         "from it and checks each one, and from the next power-up the machine "
         "shows the menu on its own screen before the game starts: flippers "
         "choose, START or LAUNCH boots, and the countdown boots the build "
         "chosen last. Every build after the first is carried as its "
         "difference from the first, which is what keeps two builds under "
         "the 4 GB one FAT32 file can be; the size strip says when it does "
         "not. The menu fills the backbox, and it can show a picture or a "
         "video clip on each card, play music and the move and confirm "
         "sounds, and offer a random card that boots one of the builds above "
         "it (Add random over the images above). A card's 'auto' picture "
         "and clip are that build's own title or attract video, taken out "
         "of its .fun (a mod that changed the attract shows its own); "
         "'auto' music is the build's own too (stock plays the game's theme, "
         "a mod that changed its intro plays that intro's soundtrack), and "
         "the 'auto' sounds are the game's own menu click and clock bell. All "
         "builds share the game's one set of settings and scores, and "
         "installing any normal update afterwards takes the menu away again. "
         "Labyrinth is supported; Dune and Winchester update differently and "
         "are not yet."),
    ],
}

# The Image Info WINDOW (the "Info" button beside the Extract / Write image
# pickers) — not a notebook tab, so it lives outside the per-tab dict and is
# appended to the tabs its launch buttons sit on (see _CONTENT_EXTRAS).
_IMAGE_INFO_SECTIONS = [
    ("The ⓘ button",
     "The small ⓘ button next to the image picker opens a read-only window "
     "with everything the app knows about that image: the file itself, what "
     "was detected (manufacturer, game, format), firmware details, on-card "
     "asset counts and the partition layout. Useful for telling firmware "
     "versions apart, comparing two releases, and reporting problems. Its "
     "Copy Report button puts a plain-text version on the clipboard, ready "
     "to paste into a bug report. When the image is the card picked on the "
     "Select card tab, the button takes you there instead, because the same "
     "details already sit under the card on that tab."),
    ("Where its details come from",
     "Only from the image itself and its filename — or, for a card opened "
     "from the Extract tab's card row, from the card in the reader (there is "
     "no filename then, so the game is named by the card's own game folder). A Stern card's version "
     "is read from the card's own update index — the version is a fact "
     "about the image, so renaming the file cannot change it — and the "
     "filename is used only when that index cannot be read. If the name "
     "claims a different version than the card, both are shown and the "
     "card wins. The short Version ID (like VEN106LE) is "
     "assembled from the title code inside the game firmware. Videos, "
     "images, scenes, sounds and sound fragments are all counted straight "
     "off the card, no Extract needed: those sound counts are the asset "
     "container's own header words. \"Sounds\" is what an Extract decodes "
     "to WAVs; \"Sound fragments\" is the (larger) pool of audio pieces "
     "the game's sound requests draw on — a request can chain several "
     "fragments, and several requests can share one. \"Sound requests\" is "
     "that third number, the calls the game code itself can make: it is no "
     "header word, so it is read from the request table inside the game "
     "firmware, and the row is left out rather than guessed at on a card "
     "whose table cannot be read."),
    ("Adjustments and high scores",
     "\"Adjustments\" is how many operator settings this firmware defines — "
     "the settings list in the machine's own service menu — and \"High "
     "scores\" is how many places its high-score board keeps: the four high "
     "scores, the Grand Champion, and every mode or challenge champion the "
     "game tracks. Both are read from the game firmware on the card. What "
     "the card cannot tell you is the machine's current state: the settings "
     "an operator has chosen and the scores actually played are kept in the "
     "machine's own memory, not on the SD card. The Defaults tab edits the "
     "values a freshly flashed machine starts from."),
]

# Non-tab help appended to the tabs whose UI hosts the feature.
_CONTENT_EXTRAS = {
    "Extract": _IMAGE_INFO_SECTIONS,
    "Write": _IMAGE_INFO_SECTIONS,
}
for _tab, _extra in _CONTENT_EXTRAS.items():
    HELP_CONTENT[_tab] = list(HELP_CONTENT[_tab]) + list(_extra)

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
        if p.stack_note and p.can("stack"):
            also.append("waits for multiballs only")
        if not p.can("stack"):
            also.append("never waits")
        if not p.can("events"):
            also.append("no events")
        if not p.proven:
            also.append("never run")
        rows.append((p.label, media, yes if p.can("countdown") else "no",
                     yes if p.can("ball_save") else "not yet", lights, ", ".join(also)))
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
                     "- **Ball save not yet:** found in the game, not yet seen working.\n"
                     "- **Lights:** *shots* lights just the scoring shots' inserts; *all* "
                     "holds every insert in the mode's colour.\n"
                     "- **HUD:** counters, a timer and a gauge at the screen's edges.\n"
                     "- **Buttons:** the flipper and Action buttons count as shots.\n"
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
                     "text": "**Off limits.** Progression, settings, coils, high scores, Insider Connected."}]},
                _limits("Quick answers"),
            ]),
            ("Which games", _modes_which_games),
            ("Making a mode", [
                "**New**, over the list, makes a blank mode or one from an example "
                "(KAIJU RUSH is the one that has run on a real machine). A project "
                "with no mode yet offers the same on the page. Then:\n\n"
                "1. **Name it.**\n"
                "2. **Starts on:** the shot that starts it and how many times. It can "
                "also ask for up to three more shots in the same ball, in any order or "
                "in order (any other shot starts the sequence over). *Only after* "
                "holds it until another mode has run this ball or game.\n"
                "3. **Runs for:** how long it runs.\n"
                "4. **Points per shot:** which shots score and what the first one "
                "pays. A minus number takes that much away on each hit.\n"
                "5. **Ends on** (if you like): a pick of shots, or any shot that "
                "does not score, ends it sooner.\n\n"
                "### Everything else is optional\n"
                "- **Screen:** a panel in your colours or a picture of your own, "
                "showing what each shot paid and the total.\n"
                "- **Clip:** a title card or a video of your own, full screen when "
                "the mode starts or ends.\n"
                "- **Sound:** the countdown, the sound when time is up, and sounds of "
                "its own when it starts, on a scoring shot and underneath.\n"
                "- **Lights:** a colour sweep, or the scoring shots lit on the playfield.\n"
                "- **Rules:** how often it can start, whether it runs during the "
                "game's own modes, and an event that starts or ends it.",
                {"note": "Every change saves itself in the project's modes folder about "
                         "half a second after you stop typing. The line at the bottom of "
                         "the form says whether the mode can be built, and a section this "
                         "game can't do is greyed, with the reason."},
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
                "- An edit made while the game runs reaches it within a second; a new "
                "sound or clip reaches it at the next Try it.\n"
                "- A refusal is shown beside Try it and on the Emulate tab, with the reason.",
            ]),
            ("Several modes",
             "- A card holds as many modes as you make. The count is under New, with "
             "modes made of blocks and modes written in C counted apart.\n"
             "- **One runs at a time.** A mode whose shots come up while another is "
             "running does not start then, but its next starting shot after that one "
             "ends starts it.\n"
             "- A card carries one end sound of a mode's own: the first mode that has "
             "one. The Sound section says whose."),
            ("Modes made of blocks", [
                "**New > Mode from blocks…** makes a small working mode on this card's "
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
                "- Every change saves itself; the line at the top says what is left to fix.",
                {"note": "The app turns the blocks into a mode in C, which Try it and "
                         "Write build like any other. **C it makes** shows it, and "
                         "**Edit as C…** keeps that C and puts the blocks away, for "
                         "carrying on in C."},
            ]),
            ("Modes written in C", [
                "For what the form can't do.\n\n"
                "- **New > Mode in C > Blank mode in C…** copies the Mode SDK's "
                "template into this project's modes folder and opens it. **Open "
                "MODE_SDK.md** opens the SDK's guide.\n"
                "- The folder's name is the mode's trigger name (its test triggers are "
                "*folder*.start and .stop), so keep it to letters, digits and _.\n"
                "- An **assets.json** beside the code names a clip, a picture, music "
                "and calls of the mode's own, and Try it and Write compile the mode in "
                "with them. The Code modes line lists each one.\n"
                "- **Start mode now** starts the open code mode through its .start "
                "trigger, once a Try it has built it into the running game.",
                {"note": "On a Godzilla title, New > Mode in C adds six examples written "
                         "in C, among them the MELTDOWN multiball, lit by ten Magna "
                         "captive-ball hits. Each plays its clips full screen behind a HUD "
                         "of its own. Their clips, music and calls are cut from your own "
                         "copy of the films: until they are, the example's page says which "
                         "films it needs, with **Choose your films folder…**."},
            ]),
            ("The game's own modes",
             "They are listed under yours. Pick one to see its page.\n\n"
             "- **Timers and awards:** type a new value and press Set. Stock puts that "
             "number back to the game's own.\n"
             "- **Shots:** on a game whose port allows it, a shot that counts as one of "
             "its own, and a rewrite of its shots in C.\n"
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
                "mode's own greys that button, with the reason.",
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
             "- **Save / load** saves the open mode, or every mode, to one .zip holding "
             "each mode's whole folder (picture, clip, sounds and code), to share or "
             "keep. Loading one adds its modes as Copy to… would; a name already here "
             "gets _2."),
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
                "failed message and plays on.\n\n"
                "The page says so under the title. A title whose port cannot do this "
                "(one worked out before the gate existed) cannot carry modes until its "
                "port is worked out again.",
            ]),
            ("A preview feature", [
                "The mode maker is a preview: it is in every copy of the app, switched "
                "off, and a personal code from the app's author switches it on.",
                {"flow": [
                    {"icon": "gear", "title": "Settings", "text": "the gear, top right"},
                    {"icon": "star", "title": "Preview features…", "text": "paste your code"},
                    {"icon": "check", "title": "Unlock", "text": "the Modes tab appears"}]},
                "- The window says whose code it is and the last day it works. After "
                "that day the Modes tab is gone again at the next start.\n"
                "- Your modes stay in the project's modes folder either way.\n\n"
                "### Asking for more",
                _limits("Asking for more"),
            ]),
        ],
        "Write": [
            ("Preview features",
             "A project can hold modes made with the mode maker, a preview feature "
             "(Settings > Preview features). A copy of the app where it is not "
             "switched on builds everything else in the project exactly as usual, "
             "leaves the modes and any changes to the game's own modes off the "
             "card, and says so in the log."),
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
     "- disk-space management and voice recognition quality\n"
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
