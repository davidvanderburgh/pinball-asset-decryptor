"""Per-tab tips window — the header "?" button (tester feedback).

Every working-view tab carries a pile of behaviour that used to live only in
inline grey prose or hover tooltips.  This window collects those tips per tab
so a user can pull up "everything worth knowing about this page" on demand
instead of hunting for hidden hovers.

One window per app (a tester round 2): clicking "?" re-uses the open window
instead of stacking a new Toplevel per click, and switching notebook tabs
re-renders the open window for the new tab so the text never goes stale.

Content is deliberately static + manufacturer-agnostic (plugin-specific
behaviours say "where available"); if per-manufacturer help is ever needed,
grow ``HELP_CONTENT`` into a hook on ``Manufacturer`` like ``write_intro``.
"""

import tkinter as tk
from tkinter import ttk

from .placement import centered_over
from .theme import THEMES, dark_titlebar, platform_font


# (title, body) sections per notebook-tab name.  Keys match the tab captions
# exactly (MainWindow._open_tab_help passes the stripped tab text through).
HELP_CONTENT = {
    "Extract": [
        ("Pick a source",
         "Point the input box at a dumped card image / update file. Plugins "
         "with direct-media support also offer a \"From SD card / SSD\" mode "
         "that reads the physical media in a reader (needs Administrator on "
         "Windows)."),
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
         "automatically.)"),
    ],
    "Replace Audio": [
        ("Scan and assign",
         "Scan lists every sound slot in the assets folder. Assign a "
         "replacement per slot — almost any audio format is accepted (mp3, "
         "wav, ogg, flac, m4a, …); it doesn't need to match the original, "
         "it's converted and fitted (length / sample rate / volume) "
         "automatically when you build. Export from your editor at whatever "
         "sample rate and bit depth it likes — 16, 24 or 32-bit, float or "
         "integer, any rate — there's nothing to match by hand."),
        ("Matching the original's volume",
         "Replacements are levelled against the sound they replace, not to a "
         "fixed peak: the original slot is decoded, its speech level "
         "measured, and yours gained to match. That matters most when one "
         "stray transient (a lip smack, a desk knock) is the loudest thing in "
         "your recording — normalizing to that peak would leave the voice far "
         "quieter than the callouts around it. It works the other way too, "
         "bringing a hot music clip down to the level of its neighbours.\n\n"
         "The match ignores the level you mixed your own file at — the same "
         "track exported quietly or hot builds the same card — so if you "
         "want a replacement louder or quieter than stock, do it in "
         "Advanced Audio Options rather than in your editor. The "
         "\"Replacement loudness\" row there keeps the match as the default, "
         "offers normalizing to full scale instead, and takes a ±12 dB "
         "offset on top of either; boosts are soft-limited, never "
         "hard-clipped. Music is the usual reason to reach for it: Stern "
         "mixes its music as a bed under the callouts, so a matched song "
         "sits there too. The build log states which setting built the "
         "card.\n\n"
         "That row is one setting for the whole build, so it moves every "
         "replacement together. To lift one clip on its own, use the "
         "\"Loudness for this clip\" box beside the Replacement preview on "
         "the Audio tab — its dB stacks on top of the build-wide one, the "
         "Level column shows which clips you have levelled, and \"Apply to "
         "all shown\" puts the same offset on everything the list is "
         "currently showing (set Type to Music first and only the songs "
         "move)."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: the "
         "replacements you assign are applied automatically when you build the "
         "update on the Write tab."),
        ("Change markers",
         "Green = assigned this session (staged when you build). "
         "\"✓ changed on disk\" = the file sitting in your PROJECT FOLDER no "
         "longer matches the one Extract put there — because an earlier build "
         "replaced it, or because you copied a file over it yourself. It says "
         "nothing about your source card image (never touched) or about a "
         "card you have already written. Either way the next build packs it, "
         "which is why replacing files in the project folder by hand works: "
         "batch-process them however you like, drop them over the originals, "
         "press Scan, and they show up here as changed. The counter shows "
         "every change the next build will pack, not just this session's.\n\n"
         "\"⚠ not on this card\" is the opposite answer: that file is in your "
         "project folder but not in the extract, so nothing on the card "
         "matches its name, no original was overwritten, and the next build "
         "cannot place it. It's usually a mod pack built from an older "
         "extract whose names for some files have since changed — importing "
         "that pack again takes the strays back out, and \"Transfer Mods to "
         "New Version\" on the Mod Pack tab carries the change over by "
         "content instead of by name."),
        ("Preview",
         "Two players side by side — \"Original (stock)\" on the left, "
         "\"Replacement (your file)\" on the right — each with its own "
         "controls, so you can "
         "compare them before you commit to a build. Starting one pauses "
         "the other, and ■ on either silences both — only the pane you "
         "pressed rewinds."),
        ("Play sequentially",
         "Tick it and a finished clip selects and plays the next row on its "
         "own, following whatever sort, search and Type filter you have set — "
         "so you can listen through a whole card without clicking each row. "
         "It stops at the end of the list, and pressing ■ or clicking another "
         "row stops it. Anything you notice on the way is already selected, "
         "so hit F2 or right-click it there and then. Opening a replacement "
         "picker also stops the audition rather than play on behind the "
         "dialog — press ▶ when you're back to carry on from there.\n\nTick \"Play "
         "replacements\" as well and every row that has a replacement "
         "(picked now, or already changed on disk) plays the replacement "
         "instead of the original — the list sounds the way the built card "
         "will, so anything that still sounds stock is a clip you haven't "
         "replaced yet. It only acts while sequential play is stepping "
         "through the list, so ticking it turns \"Play sequentially\" on "
         "too."),
        ("Undo",
         "Right-click a slot: \"Remove replacement\" cancels an un-built "
         "assignment; \"Revert to original\" restores an already-changed "
         "file. \"Revert all changes…\" on the Write tab resets everything."),
        ("Finding things",
         "Click any column header to sort (click again to flip). The search "
         "box filters by name — with auto-naming on, that includes the "
         "transcribed call-out text and matched song titles. The Type "
         "dropdown (shown when the folder classifies) filters to one kind "
         "of audio: Music (the song and bank tracks — and on a game whose "
         "own naming identifies no music at all, anything at least 20 "
         "seconds long instead, because some pins store their songs as "
         "Sound-Test-named sequences; a slot promoted that way reads Music "
         "in the Type column too, so the column and the filter always "
         "agree), Sound FX (named by the game's own Sound Test menu), "
         "Callouts (speech — needs Auto-name call-outs to have run), or "
         "Other. The Show dropdown narrows the list by change state: "
         "Changed = the slots you've replaced or that already differ from "
         "the extract, for reviewing a big mod; Unchanged = only what you "
         "haven't touched yet, so a part-finished pass is the list in front "
         "of you instead of something to scroll past. Export CSV saves the "
         "whole table (every slot, not just the filtered view) for tracking "
         "a large project in a spreadsheet."),
        ("Where is this on the card?",
         "Right-click a slot → \"Find in Partition Explorer\" opens the "
         "card image at the file the asset came from, expanding the tree "
         "down to it. Sounds aren't separate files on a Spike 2 card — "
         "they're decoded out of a bank — so an audio row reveals that "
         "bank (image.bin, or the image-scNN.bin for music) and says so."),
        ("Name and type (Properties)",
         "Right-click a slot → \"Properties…\" to correct its name (e.g. a "
         "call-out the auto-transcriber mis-heard). The name is remembered "
         "by the sound's content, so a future extract — same card or a "
         "newer firmware carrying the same sound — reapplies it before "
         "transcription runs, and the slot keeps its Type bucket. Blank "
         "restores the stock name and forgets it. On Stern titles with a "
         "Sound Test menu the extract already names the sounds it lists "
         "(\"SE FX MATCH\" and the like), and writes the full menu "
         "listing to sound_test_names.csv; the dialog offers those names as "
         "suggestions, so you can play a number on the machine's Sound Test "
         "menu and either confirm what the extract called that slot or pick "
         "the entry (type its number to find it) yourself."),
        ("Blip-free callouts (Advanced Audio Options)",
         "Off by default, and experimental. The machine reads two ~512-byte "
         "windows out of "
         "every sound at boot to set up its decoder, and each result feeds "
         "the next, so re-encoding one sound would desync the whole bank. "
         "The plain fix puts the original bytes back in those two windows, "
         "which are inside the audible part — so you hear a ~6 ms scrap of "
         "the original twice in every replacement. Blip-free instead stashes "
         "a copy of those bytes in the game binary and points the boot-time "
         "read at the copy, so your audio plays for the whole sound. It "
         "needs the Linux filesystem driver (the same one full-size video "
         "replacement uses) because it makes the game binary slightly "
         "longer, and it is skipped for a direct-SD write. It is off because "
         "the one machine it has ever reached reboots partway through its "
         "startup screen and loops there. Two faults in the added code were "
         "found and fixed in v0.102.5 and that machine still does it, so the "
         "cause is not yet known and no card built this way has been "
         "confirmed to boot. Leaving it off costs you only the brief scrap "
         "described above, which a tester listening for it could not hear."),
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
        ("Size limits",
         "Patching is size-neutral: a same-or-smaller replacement fits "
         "as-is, a larger one is re-encoded down to the slot's byte budget. "
         "A replacement that already matches the slot's format is copied "
         "through verbatim — no quality loss. Two exceptions where a "
         "longer clip keeps full quality: on Stern Spike 2 the slot is "
         "grown on the card, and on Barrels of Fun the update's file "
         "offsets are rewritten around the new clip — so on both, an "
         "oversized replacement skips the byte budget entirely."),
        ("What the machine can actually play",
         "A clip only goes onto a Spike 2 card untouched when it's a real "
         "drop-in for the one it replaces — same container, H.264, 8-bit "
         "4:2:0, and the slot's own resolution and frame rate. The machine's "
         "decoder isn't a desktop player: give it an MKV, HEVC, a 10-bit "
         "clip or the wrong size and it plays the sound over a black "
         "picture. Anything that isn't a drop-in is converted first (still "
         "at full size, no byte budget) and the build log says which clip "
         "and why."),
        ("Encoding your own clips",
         "Right-click a slot and pick \"What this slot needs…\" to see exactly "
         "what a replacement has to be to go on the card untouched: container, "
         "codec, H.264 profile and level, frame size, frame rate and whether "
         "the clip has an audio track. It also gives you an ffmpeg command "
         "that produces one, with only the flags that have to match, so you "
         "can add your own bitrate, key-frame interval and preset around "
         "them. Every value is read off the clip already in that slot, which "
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
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
        ("Seeing where a clip plays",
         "Right-click a slot and pick \"Show scene contents…\" to open the "
         "Scenes window on the scene that plays it, with the images, fonts "
         "and text it shares the screen with."),
        ("Very short clips",
         "Plenty of Spike 2 slots hold a clip well under a second — a sixth "
         "of one Batman card's 6331 do, down to one-frame stills — so the "
         "Length column shows those with their milliseconds (0:00.033) "
         "instead of rounding them to 0:00, which reads as an empty slot. "
         "The preview posters the first frame of a clip that short, "
         "because it is the whole clip."),
    ],
    "Replace Images": [
        ("Scan and assign",
         "Scan lists the game's replaceable images. Assign a replacement "
         "per slot — almost any image format works; it is auto-scaled to "
         "the original's pixel dimensions and converted to the slot's "
         "format (transparency is kept where the original has it). Keep "
         "the original resolution for best results."),
        ("Assets folder + applying",
         "The assets folder is the one Extract produced — the same folder the "
         "Write tab reads. There's no separate \"stage\" step: each "
         "replacement you assign is auto-fit to its slot (scaled, "
         "format-converted, size-matched) and applied automatically when you "
         "build the update on the Write tab."),
        ("Where images come from",
         "The Source column tells the four stores apart. \"File\" = a "
         "plain image file on the card (menus, apron/test art). \"Scene "
         "texture\" = artwork decoded out of the game's compiled display "
         "scenes — many are frames of an animation or sprite sheets. "
         "\"Radium\" = images embedded inside the scene descriptions "
         "themselves (song-title banners and similar). \"Glyph\" = a single "
         "character sliced out of a font atlas (see Font atlases below). "
         "All four replace the same way; the Source dropdown in the toolbar "
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
        ("Scenes window",
         "The \"Scenes…\" toolbar button (where available) lists every "
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
         "want a closer look at a fast one. \"Save preview…\" writes the "
         "scene out full size: a PNG of a still one, and an MP4 (or an "
         "animated GIF) of one that moves. The MP4 needs ffmpeg installed "
         "and is the whole scene at its own frame rate — it is re-rendered "
         "for the export, so it isn't limited to the frames the preview "
         "plays. \"Save all previews…\" does the whole list at once: one "
         "PNG per scene into a folder you pick, following whatever the "
         "Search box is filtering on, so you can flip through a card's "
         "screens in an image viewer. It runs in the background — the "
         "same button becomes Cancel while it works, closing the window "
         "stops it, a name already in the folder is suffixed rather than "
         "overwritten, and the caption tells you how many were written "
         "and how many could not be drawn. \"Rebuild previews…\" re-reads the scene "
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
    ],
    "Replace Text": [
        ("Scan and edit",
         "Scan loads the game's editable display strings from the assets "
         "folder Extract produced — the same folder the Write tab reads. Pick "
         "a row and type the new text in the edit panel — the original is "
         "always kept alongside for reference. Edits are saved straight into "
         "the manifest and patched in on the next Write."),
        ("Length limits",
         "Replacements live in the original string's slot: the Max column is "
         "the byte budget, same-length or shorter is padded automatically, "
         "and over-long text is rejected."),
        ("Scene text vs game-program text",
         "Two kinds of string are listed. Scene text lives in a scene file "
         "(the Scene column names it). Game-program text is drawn by the game "
         "code itself — mode titles, battle names, award lines — and shows "
         "\"game program\" in that column. A scene's text is often only a "
         "placeholder the code overwrites, so if a line still reads the old "
         "way on the machine after you changed every scene copy of it, the "
         "one that matters is the game-program row."),
        ("Names that live inside a longer line",
         "Some names have no string of their own: the machine draws the tail "
         "end of a longer line, so \"EBIRAH\" is really the last part of "
         "\"GODZILLA VS EBIRAH\". Those get their own row, budgeted by the "
         "length of the line they sit inside. Edit BOTH rows and make the "
         "line END with the new name — say \"GZ VS BIOLLANTE\" plus "
         "\"BIOLLANTE\" — and the pointer is moved for you. If the two don't "
         "agree, the build log says so and leaves that line alone."),
        ("Apply to all",
         "\"Apply to every scene with the same original text\" repeats the "
         "edit everywhere that exact original string occurs (many strings "
         "repeat once per scene/keyframe)."),
        ("Seeing the line in its scene",
         "\"Show in Scenes…\" (also on the right-click menu) opens the "
         "Scenes window on the scene that draws the selected line, with the "
         "line itself picked out — so you can see the font, the colour and "
         "the art it sits on before changing the words. Game-program lines "
         "have no scene to show: the game code draws them at runtime."),
        ("Narrowing a big card down",
         "Show gives you All / Changed / Unchanged: Unchanged is exactly the "
         "lines you haven't dealt with yet, so a part-finished pass is what's "
         "left in front of you. Scene narrows to the game program or to one "
         "scene file, each listed with how many strings it holds. Both stay "
         "with the project folder, so you come back to the view you left."),
        ("Naming a scene",
         "Spike 2 names every scene folder with a hash, so the Scene column "
         "is characters that mean nothing until you've opened them. "
         "Right-click a row and choose \"Name this scene…\" to give it a name "
         "of your own; it shows in the Name column and in the Scene "
         "dropdown. The folder name never changes, so the name sticks — and "
         "it's the same name the Replace Images tab shows for that scene, "
         "from either direction."),
    ],
    "Write": [
        ("What a build does",
         "Build copies the pristine original and repacks every file in the "
         "assets folder that differs from the extract baseline — including "
         "changes from earlier sessions, not just today's. Changed sounds "
         "are re-encoded and replaced videos / images / text are patched in "
         "size-neutrally, so the built file is a drop-in replacement for "
         "the original. The Modified Files list previews exactly what will "
         "go in before you click — it's only a preview: the build does its "
         "own full comparison, so there's no need to wait for the scan to "
         "finish before building."),
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
         "Put the finished stick in a front-cabinet USB slot, leave the "
         "purple security key plugged in, and power on: the installer runs "
         "by itself — the Utilities USB-update menu is only for JJP's small "
         "delta updates and ignores install sticks. The installer checks for "
         "the security key first and stops on \"Security key not found\" if "
         "it is missing."),
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
         "dropped. Your staged "
         "Defaults (settings and high-score slots) come along too — those "
         "are keyed by the firmware's own names, and the build skips any "
         "the new image doesn't have.\n\nThe same thing works between the "
         "two models of one game: point it at your Pro/Prem/LE extract and "
         "a fresh extract of the other model, and what they share moves "
         "over.\n\nFields 1 "
         "and 3 are never alternatives, and neither takes priority: field 1 "
         "(your old extract) is where your mods come FROM and is always "
         "required; field 3 is an optional clean, unmodified twin of that "
         "same old version, used only as the reference your old extract is "
         "compared against — with it, the factory's own between-version "
         "changes aren't mistaken for your mods, and audio + text mods can "
         "be carried too."),
    ],
    "Partition Explorer": [
        ("What it's for",
         "Browse a raw card image (.raw / .img) the way a file manager would. "
         "Handy for pulling a file (a radium scene, a boot script) out of an "
         "old modded card to reuse, or dumping a folder to compare a modded "
         "card against a stock one. Browsing never changes the card — only "
         "\"Replace with…\" writes to it, and only when you confirm."),
        ("Open a card",
         "Point \"Card Image\" at a card image and press Open. The app reads "
         "the disk's partitions and picks the first browsable Linux (ext4) one; "
         "switch partitions with the dropdown. FAT and extended partitions are "
         "listed but not browsable."),
        ("Browse + preview",
         "Expand folders in the tree to walk the filesystem — children load as "
         "you open each folder, so even a full card opens instantly. Selecting "
         "a file shows it in the Preview pane: text as text, and images and "
         "fonts drawn as a picture with their format and real pixel size. "
         "Anything too big to draw, or of a kind that doesn't render, says to "
         "extract it instead."),
        ("The Changed column",
         "\"Changed\" marks the files you have replaced on THIS card image, "
         "with the date of the last swap, and the mark survives closing the "
         "app. It is PAD's own record of what PAD did — an edit made outside "
         "PAD leaves nothing to find, and if the image is swapped or rebuilt "
         "underneath the marks they're dropped rather than shown against a "
         "card they no longer describe. \"Show:\" filters the tree to All, "
         "Changed (just those files, already expanded) or Unchanged "
         "(everything else). Find searches the whole partition either way — "
         "it clears the filter first so a hit can't stay hidden behind it."),
        ("Properties",
         "Right-click any file → \"Properties…\" for its full on-card path "
         "(the path it has when the partition is mounted, for lining PAD's "
         "edits up with a hand-mount workflow), its partition, size and type "
         "— and, for a file you've replaced, every swap PAD made to it on "
         "this image with the file each one came from."),
        ("Extract",
         "\"Extract Selected\" saves the highlighted file, or the highlighted "
         "folder's whole subtree, to a location you pick. \"Extract Whole "
         "Partition\" dumps the entire filesystem — useful for diffing two "
         "cards."),
        ("Replace a file on the card",
         "Right-click any file → \"Replace with…\" swaps it for one of your "
         "own: a boot or game script, a font, the Stern splash screen on the "
         "OS partition (sda2, /usr/local/spike/SternLogo.png). Your file does "
         "NOT have to match the original's size. A same-size file is written "
         "straight into the blocks the original occupied, which changes no "
         "filesystem structure at all and needs nothing installed. A bigger "
         "or smaller one has to have blocks allocated or freed, so the card "
         "image is mounted through the Linux filesystem driver (WSL2 on "
         "Windows — the same dependency full-size video replacement uses) and "
         "the kernel does that part. Either way the file keeps its name, "
         "location and permissions, and its Stern validation record is "
         "refreshed — including the stored file size when the length "
         "changed. The confirmation dialog tells you which of the two routes "
         "your pick will take before anything is written."),
        ("Before you replace",
         "Work on a copy of the image if it's precious: a replace writes into "
         "the image straight away and there is no undo. Files the validation "
         "manifest doesn't index (everything on the OS partition, for "
         "instance) simply have no record to refresh, and the log says so. A "
         "resize needs free space on that partition, and you'll be told the "
         "numbers rather than left with a half-written file if there isn't "
         "any."),
    ],
    "Default Settings": [
        ("What it's for",
         "Preset the operator-adjustment DEFAULTS baked into a card image — "
         "free play, volume, pricing, brightness and more — so a machine "
         "comes up the way you want without adjusting it by hand every time "
         "you flash a fresh card. The Card Image shown is the master image "
         "set on the Extract tab; the settings are read from its game "
         "firmware."),
        ("Fresh cards only (important)",
         "A machine uses these defaults on a fresh flash or after a factory "
         "reset. A machine that has already been set up keeps its own "
         "settings — Stern stores those on the board, not on the card, so the "
         "app cannot change a machine that's already configured. Think of this "
         "as \"how a brand-new card boots\"."),
        ("How the list is ordered",
         "Settings are grouped under headings — Game, Sound, Lighting, "
         "Insider Connected, High scores — and every score on the machine's "
         "high-score board is collected into the High Scores block at the "
         "bottom, whether or not the firmware carries a player name to go "
         "with it. \"Allow High Scores\" and \"Reset High Scores After\" sit "
         "just above that block because they govern the board without being "
         "places on it."),
        ("Edit + build",
         "\"On card\" is the default currently baked into the image (Stern's "
         "factory value unless it was changed here before); set \"New "
         "default\" to what you want — a ● marks every row that deviates "
         "from the card, and every change stages itself automatically, like "
         "edits on the Replace tabs. The log names each field you change and "
         "both values, once you leave the field. The next card you Build gets "
         "the staged defaults baked in (validation record refreshed "
         "automatically) while your master image stays untouched. \"Reset "
         "Fields\" puts everything back to the image's own defaults and "
         "clears the staged changes."),
        ("When the Range looks wrong",
         "A few settings ship with a default outside the range the firmware "
         "itself declares for them — Led Zeppelin 1.22's two ELECTRIC MAGIC "
         "champions default to 2,000,000 against a stated minimum of "
         "5,000,000. That is the firmware, not a misread: the Range column "
         "says so, the row counts as unchanged until you touch it, and if "
         "you do edit it the value written is pulled into the declared range "
         "(the game rejects anything else)."),
        ("Settings the machine edits elsewhere",
         "Hovering a setting's name tells you when the machine won't show it "
         "in its Adjustments menu — the master volume, for one, lives on a "
         "service screen rather than in Adjustments. See the Menu column in "
         "the all-settings list below the form for the same information on "
         "every setting."),
        ("Master Volume",
         "This row is the volume the machine comes up at, and \"On card\" is "
         "the number this game was built with — 30 on Led Zeppelin, 10 on "
         "Godzilla, 24 on John Wick. It is not the setting's own compiled "
         "default: every Stern card ships that as 64, one past the 63 the "
         "firmware accepts, so the machine ignores it and uses its built-in "
         "number instead. Setting this row moves both, including the one a "
         "factory reset reads, so a fresh card comes up on your number. Same "
         "\"fresh cards only\" rule as the rest: a machine that has already "
         "been set up keeps the volume it has until it is factory reset, "
         "because Stern stores that on the board."),
        ("High scores",
         "The \"High Scores\" block is the board a fresh card boots with — "
         "Stern ships it filled with the design team's initials. Each slot "
         "takes new initials, a new player name and (where the firmware "
         "exposes it) a new default score. Initials and names are written "
         "into the slot's own space in the game firmware, so each field is "
         "capped at the number of characters that slot has room for — "
         "initials are always 3. Same \"fresh cards only\" rule as every "
         "other default: a machine that already has scores stored keeps "
         "them."),
        ("All settings on this image (and what \"Debug\" means)",
         "Below the editable form is every adjustment the firmware carries, "
         "with the caption the machine itself prints and its id. "
         "The \"Menu\" column says where you can reach it on the machine. "
         "\"Adjustments\" is the ordinary operator Adjustments menu. "
         "\"Service menu\" is a real setting the machine edits on a different "
         "screen — volume, speakers, software update, tournament, redemption. "
         "\"Debug\" is one no menu shows at all: factory tuning values, "
         "mech timings and developer leftovers that Stern left in the "
         "firmware but never listed. This isn't guesswork — the app reads the "
         "menu's own pages out of the game binary and works out what they "
         "can't reach. A build whose menu can't be read says so and flags "
         "nothing rather than guessing. Click a column header to sort the "
         "list, again to reverse it, and a third time to put it back in the "
         "firmware's own order; the value columns sort as numbers rather "
         "than as the text in the cell."),
        ("Changing a setting the form doesn't draw",
         "Double-click any row in that list to set its default, including the "
         "Debug ones. It stages and logs exactly like the form above, and the "
         "\"New default\" column shows what the next Build will bake in. Two "
         "differences from the form: the value is in the firmware's own units "
         "(the form converts a few, like the master volume, into what the "
         "machine displays), and there is no help text or safety curation "
         "behind it — a factory tuning value set to something the game never "
         "expected is on you. \"Back to card value\" in the dialog unstages "
         "it again. Same fresh-cards-only rule as everything else here."),
        ("Showing hidden settings on the machine itself",
         "A Debug setting is hidden because the machine's Feature Adjustments "
         "page stops before it — nothing marks the setting itself. \"Show "
         "hidden settings in the machine's menu…\" moves where that page "
         "stops, so the machine lists and edits those settings like any "
         "other. Pick how far it opens: the page is one straight run of "
         "settings, so everything between the current end and your pick comes "
         "with it — you cannot expose one and skip its neighbour. It is "
         "staged for the next Build like any other change, and by name rather "
         "than by number, so rebuilding on a different game version can't "
         "expose whatever that number happens to mean there. Worth knowing "
         "before you use it: this rewrites one instruction in the game's code "
         "rather than changing a value (the card stays the same size and its "
         "validation record is refreshed as usual), it has been checked "
         "against the firmware but not yet on a real machine, and the tail it "
         "reaches usually mixes genuinely useful settings with factory test "
         "entries and the game's own internal bookkeeping flags. Titles whose "
         "menu the app couldn't fully read don't offer the button at all."),
        ("Presets (set once, reuse everywhere)",
         "Save a set of values as a named preset with \"Save As…\", then pick "
         "it from the dropdown any time to fill the form (the values stage "
         "automatically). The auto-apply checkbox belongs to the selected "
         "preset: tick it and that preset is baked into every card you build "
         "on the Write tab, so you never have to revisit this tab — only the "
         "settings a given game actually has are applied, so one preset "
         "works across titles. Use presets without auto-apply when different "
         "machines need different defaults; tick it when one preset fits "
         "everything you build."),
    ],
    "Emulate Spike1": [
        ("What it does",
         "Runs a Stern Spike 1 (DMD-era) game on this PC. Spike 1 is the "
         "2015-2016 dot-matrix generation (WrestleMania, KISS, Game of Thrones, "
         "Ghostbusters). The game is a static ARM program, so it runs under a "
         "patched emulator with a software model of the machine's boards. Pick a "
         "Spike 1 card image, press Start, and it boots and shows its attract on "
         "the dot-matrix display — title, service-menu prompt, credits, replay "
         "score."),
        ("It needs WSL and runs as root there",
         "The board model needs a privileged host setup, so this tab is "
         "Windows-only and runs the emulator inside WSL with root (which on "
         "Windows needs no password). The first Start builds the emulator once, "
         "which takes a few minutes; later starts are quick."),
        ("The DMD and switch/LED windows",
         "Two small windows open beside the game: the dot-matrix display (the "
         "picture the machine shows) and a switch/LED matrix. The DMD shows the "
         "running attract. The switch matrix is still being wired up — it opens, "
         "but clicking switches does not drive the game yet (the game only reads "
         "a board's switches once its board type is advertised, a remaining "
         "step). Nothing you do here is written back to the card."),
        ("If it gets stuck",
         "\"Fix stuck state\" force-restarts WSL to clear a wedged emulator — a "
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
    "Emulate": [
        ("What it does",
         "Runs the real Stern Spike 2 game binary on this PC — in its own "
         "window, at 60 fps on the graphics card, with sound and keyboard "
         "input. Start it, and the game boots exactly as the machine does: "
         "splash, then its own boot sequence, then attract mode or the "
         "operator menu. On macOS the window is Screen Sharing — the picture "
         "renders inside the container, and the app opens the viewer by "
         "itself once the game is up (the VNC password is pinball). All of "
         "the emulator's windows live inside that one Screen Sharing desktop: "
         "click a window once to give it the keyboard, and drag windows by "
         "their title bars to arrange them. Stop kills every part of it and "
         "then verifies nothing survived — and if leftovers are stuck where "
         "nothing inside WSL can clear them, Stop says so and offers the "
         "WSL restart that does."),
        ("Reset windows",
         "Puts the emulator's windows back where they started. The rig "
         "remembers where you last dragged each one and restores it on the "
         "next run with no check that the spot is still on screen — so a "
         "window moved to a second monitor that is later unplugged comes back "
         "somewhere you cannot reach it, and there is nothing to drag. This is "
         "the way back. It works on every platform and whether or not a game "
         "is running."),
        ("The game window should come up in front",
         "It comes out over this app by itself, along with the virtual "
         "playfield window — you should not have to go looking for "
         "it. It can take a few seconds after the window first appears, "
         "because Windows will not let a program put a window in front of the "
         "one you just clicked, and the rig has to keep asking until it is "
         "allowed. If it ever stays behind, Reset windows above is the "
         "shortcut back to it."),
        ("It runs the card you pick here, not the Input box",
         "This is the one tab that ignores the Input box: point it at a card "
         "image of its own. That image is mounted READ ONLY and run in place — "
         "nothing is extracted and nothing can write to it — so a stock card "
         "and your own build both work, and replacing an asset on the Replace "
         "tabs does not change what the emulator plays until you build a card "
         "and pick it here. The path is remembered per project, so it comes "
         "back on the next launch without another Browse."),
        ("First boots copy the card — and Cache… shows where that space went",
         "The first boot of a card copies it to a local cache so every "
         "later boot starts in seconds instead of minutes. That copy is "
         "narrated in the status line (\"Copying card: …\") and starts in "
         "the background the moment you pick a card, so it is often already "
         "done by the time you press Start. Cached copies add up — the "
         "Cache… button beside Browse lists every cached card with its real "
         "size on disk and when it last booted, and lets you delete any of "
         "them. Deleting is always safe: the card just re-copies on its "
         "next boot. When disk space runs low, the cache also cleans "
         "itself, dropping the cards you have not booted for the longest."),
        ("Tech Alerts handles itself",
         "The game boots through its Tech Alerts screen — the machine's "
         "operator readout — and the emulator steps past it automatically, "
         "so a normal boot goes straight on to attract. While that is "
         "happening the status line says \"Passing Tech Alerts…\". "
         "\"Stuck at Tech Alerts\" is the one that needs you: the helper "
         "pressed several times and the screen never changed, and its hint "
         "says what to try. Once up, the status reads \"Game running\" — "
         "the rig deliberately does not guess between the attract loop, the "
         "operator menu, and a game you are playing."),
        ("Volume and Mute",
         "The game's audio always plays out to your PC speakers — through WSL "
         "on Windows, and on macOS over a local stream played by ffplay — and "
         "this slider is the one control over it. It sets the level of the "
         "emulator's OWN sound, not the in-game volume the coin door's -/+ "
         "buttons adjust, which is a per-title setting on the machine itself "
         "and is left alone. Both work live on a run that is already going, "
         "with no restart needed, and the level you leave them at is "
         "remembered for next time. Silence after the boot chime usually "
         "means the game is still waiting at Tech Alerts — it only makes "
         "sound while it is actually running."),
        ("Video",
         "Clips play. The game's own decoder is an i.MX6 hardware block this "
         "PC does not have and the card carries no software fallback, so the "
         "host decodes each clip with ffmpeg and publishes the frames into a "
         "shared ring the game draws from. Scenes, text, lamps, switches and "
         "sound all work too. That ffmpeg lives on the Linux side, and is a "
         "different copy from the one this app puts on your PATH — if it is "
         "missing there, everything else still works and the picture and the "
         "sound are simply not there. The run checks before it starts and "
         "names the package rather than letting a black window explain "
         "itself."),
        ("What it costs",
         "About 15% of one CPU core while waiting and roughly a third of a "
         "core once it is running, plus 1–2 GB of memory. The status line "
         "shows both live. There is a two-hour cap: it stops by itself so a "
         "forgotten window cannot run all night."),
        ("The first run on a machine takes a few minutes",
         "Nothing is set up in advance. The first time you press Start on a "
         "machine, the emulator builds the guest filesystem the game runs "
         "inside out of the card image you picked, and compiles the two "
         "pieces that talk to the hardware and the screen. That is several "
         "minutes with no game window, and the log says what it is doing "
         "throughout. It happens once: later runs start in seconds, and only "
         "rebuild a piece when an app update has changed it."),
        ("The virtual playfield",
         "A second window opens beside the game showing the machine's own "
         "playfield drawing, with every insert lit live from the wire and "
         "every switch clickable — click one and the game reacts as if the "
         "ball had rolled over it. Down its right side is the control "
         "panel: the full keyboard reference (a row lights the moment the "
         "game sees that switch close), the coin-door service buttons drawn "
         "as on the real door — click and hold BACK, -, + or SELECT to work "
         "the operator menu — an open/close coin door button (open cuts 48V "
         "exactly like the real interlock), and the ball trough with each "
         "position clickable. The keyboard works with this window focused "
         "too, not just the game window. It builds itself from the title "
         "you are running, so any Spike 2 game gets one. The switches are "
         "the one part that needs the game to be up: it publishes its "
         "switch list a minute or so into a run, and they appear on the "
         "playfield as soon as it does, without restarting anything."),
        ("Save states",
         "The playfield window carries a slot picker with Save state and "
         "Load state buttons (Windows); the ⓘ beside the section title on "
         "this tab spells out what a save costs. A save checkpoints the "
         "ENTIRE running game into the "
         "slot you picked — you can name it — and a load brings that exact "
         "moment straight back, mid-game included, even in a later session "
         "or after you have replaced assets on the card (streamed video and "
         "audio play the new versions; artwork already on screen at the "
         "save keeps its saved look until the game redraws that scene). "
         "It is not free: each slot holds roughly 50–150 MB on the WSL "
         "disk (snapshots compress about twentyfold; a save briefly needs "
         "~1.5 GB free while it packs), and each save freezes the game and "
         "its sound for a few seconds while the snapshot is written. "
         "A slot can only be loaded on the build it was saved on — the "
         "emulator's own libraries are part of the snapshot, so a slot "
         "from before an update is refused with a note rather than a "
         "failure. "
         "Every game has its own ten slots — a save from one game can "
         "never load into, overwrite or even appear among another's. The "
         "list on the tab shows the slots for the card you have picked; "
         "other games' slots are counted under the list rather than shown "
         "(pick that game's card and they appear; no card picked shows "
         "everything). Each slot carries its name, game, size and date, and "
         "the list keeps itself current as saves happen; Rename and Delete "
         "manage them, and the line under the list totals what every slot "
         "on the disk holds against its free space. Launch starts the "
         "emulator and drops straight into the selected slot — or, with a "
         "run already up, loads it into that run. Slots only ever load "
         "into the same game and firmware version they were saved from. "
         "They also need two things inside WSL that nothing else here "
         "does. busybox-static: the only boot shape that can be frozen has "
         "to let go of your own filesystem once it has swapped in the "
         "game's, and that takes a native static program. And criu, which "
         "is the program that does the freezing and thawing — no Ubuntu "
         "publishes it at all, so PAD builds it from source, once, which "
         "takes a few minutes. Without either one every "
         "title still starts and runs exactly as before — only the slots do "
         "nothing — so the tab says that in its own line before you press "
         "Start, and “Set up emulator…” gets both."),
        ("Start Docker / Get Docker… (macOS only)",
         "The emulator is a Linux program, and a container is how a Mac runs "
         "one — so Docker is to macOS what WSL is to Windows here. This "
         "button appears only when Docker is not ready and there is nothing "
         "to install: it starts the engine you already have (Docker Desktop, "
         "OrbStack, Rancher Desktop or Colima), or, on a Mac with no package "
         "manager for “Set up emulator…” to use, opens the Docker Desktop "
         "download page. Installing is the other button's job. The app looks "
         "for docker in Homebrew's, MacPorts' and Docker Desktop's own "
         "locations as well as on PATH, because a Mac app launched from "
         "Finder inherits almost no PATH at all; PAD_DOCKER overrides if "
         "yours lives somewhere else. It disappears once Docker is ready. "
         "Windows and Linux never see it and never need Docker to emulate."),
        ("Set up emulator… (Windows and macOS)",
         "The tab asks this PC what the emulator still needs before you press "
         "anything, so a run does not stop on a missing tool a minute after "
         "Start. A machine that is ready shows nothing at all. One that is not "
         "gets an amber notice naming the fault and each missing package with "
         "what it is for. Two of those are compilers and they are not "
         "interchangeable: the ARM one builds the hardware shim, and plain "
         "gcc (with libc6-dev, which gcc does not always bring along) builds "
         "the renderer that draws the picture on this PC. "
         "Two things are listed apart from those, under “Save states need:”, "
         "because their absence costs a feature and not the emulator: "
         "without busybox-static and criu every title still starts and runs "
         "and only the save "
         "slots do nothing, so that machine is told “The emulator runs on "
         "this PC. Save states do not yet.” instead of being accused of not "
         "running an emulator it runs perfectly well. The button gets both, "
         "and a Linux desktop is never asked for them at "
         "all, since the freezable boot shape is a Windows one. criu is the "
         "one thing here that is not an install: no Ubuntu publishes it, so "
         "the button builds it from source — it says so, and how long it "
         "takes, before it starts. "
         "The button fixes it: it installs those "
         "packages inside WSL, registers the kernel's handler for 32-bit ARM "
         "programs — which is what the game is — and turns on systemd in "
         "/etc/wsl.conf so that registration is still there after WSL "
         "restarts. It lists every package and file it will change before it "
         "touches one, and a No leaves the machine exactly as it was. No "
         "password is needed and nothing on the Windows side is altered. "
         "A package being missing is not the same as apt being able to get "
         "it, and the notice tells you which: Ubuntu keeps qemu-user-static "
         "in its “universe” component, and a WSL distro with universe "
         "switched off answers “has no installation candidate”. Turning it "
         "back on is then the first line of the confirmation dialog and the "
         "first thing the button does, and the packages go on one at a time "
         "so one apt cannot get never blocks the rest. Both of those readings "
         "come from apt's downloaded package lists, so neither is claimed "
         "until there is an index to read — a distro that has never run "
         "apt-get update is not one whose sources are missing anything. If "
         "your Ubuntu really does not publish qemu-user-static, the button "
         "fetches that one from Ubuntu 24.04's archive instead and installs "
         "the file: it depends on nothing, the download is checked for that "
         "before it goes on, and your package sources are not changed. The "
         "dialog lists it as its own step, since it is not an apt install. "
         "For anything left that no fetch can supply the button disappears "
         "rather than inviting another press, and the notice names the "
         "release you are on and gives you the two wsl commands to switch to "
         "one that carries the package — unless the only package it cannot "
         "get is the save-state one, where swapping your Linux out is a "
         "wildly out-of-proportion answer to a feature being off: there the "
         "notice says save states stay off, that titles start and run exactly "
         "as they do now, and leaves the working machine alone. "
         "Linux sees the notice but no button, because there the same work "
         "needs a sudo password this app has nowhere to ask for — the notice "
         "prints the command for that machine instead. "
         "macOS is asked a different question by the same button. Its "
         "container already carries all six packages, so what a Mac can be "
         "missing is Docker itself — and, more often, the Linux machine "
         "behind it: on macOS `docker` is only a client, so a docker "
         "installed from Homebrew or MacPorts has nothing to run a container "
         "with. Press the button there and this app installs Colima (and the "
         "docker client, if that is missing too) with whichever of Homebrew "
         "or MacPorts you already have, then starts it — in this window, "
         "with every line in the log pane. You never type a command: the "
         "password, where one is needed, is asked for by macOS in its own "
         "dialog, exactly as an installer would. As on Windows it lists what "
         "it will do first, a No changes nothing, and the button disappears "
         "when there is nothing left to install."),
        ("Check setup…",
         "Always here, on every platform, and it changes nothing — the probe "
         "only looks, so there is no confirmation to give and no password to "
         "type. Press it and the log pane gets the whole answer, including "
         "when the answer is that nothing is wrong: which packages are "
         "present, whether the 32-bit ARM handler is registered and whether "
         "it survives a WSL restart, who this distro logs in as, whether it "
         "can start Windows programs, whether the good sound path is "
         "available and which Windows Python it found for it, which "
         "display it has, and a last line saying whether "
         "this PC can run the emulator. That is the paste to send when a run "
         "goes wrong. On a Mac it answers the question a Mac has instead — "
         "there are no packages to install there and the container carries "
         "them all, so what it reports is Docker. The amber notice above "
         "only speaks when something is "
         "broken, so its silence used to mean both \"asked, all fine\" and "
         "\"nobody ever asked\" — this button is the difference. It is "
         "deliberately not the same button as \"Set up emulator…\": that one "
         "installs packages and edits /etc/wsl.conf, and this one is safe to "
         "press at any time, including while a game is running."),
        ("The game window opens and stays black",
         "The commonest cause on Windows is a WSL that logs in as root: the "
         "renderer then cannot attach to the WSLg X server's shared memory "
         "and draws into nothing, while the sound, the switches and the "
         "virtual playfield all work perfectly — which is why it looks like "
         "the app is fine and the picture is missing. Check setup… names it, "
         "and the cure is on the WSL side: give the distro an ordinary user "
         "account, make it the default, and restart WSL. The rig will not do "
         "that for you, because guessing a user is easy to get wrong in a way "
         "that trades a black window for a renderer that cannot start. "
         "Whatever the cause, the renderer now says whether there is a "
         "picture at all — a few \"picture:\" lines in the log, only when the "
         "answer changes. \"STILL BLACK\" while video frames are going in "
         "means the black is being drawn and the window is innocent, so "
         "Restart WSL… is not the cure; a picture that appears and then goes "
         "is the opposite case. Set PAD_GL_PICCHECK to change the seconds "
         "between readings, or to 0 to switch it off."),
        ("Restart WSL…",
         "For the two faults that are not the emulator's to fix: a game "
         "window left on screen that will not close (its X does nothing "
         "because nothing is behind it any more), and crackly or stuttery "
         "sound after a long session. Both live in WSL rather than in the "
         "game, and restarting WSL is the cure for each. It closes "
         "everything running in WSL, not just the emulator, so it asks "
         "first and stays greyed out while a run is up — stop the game, "
         "then use it. Nothing on disk is lost. (A stop that cannot finish "
         "cleanly offers this same restart by itself, so you rarely need "
         "to come here for that.) When the restart is done the tab checks "
         "this PC again, because the kernel's 32-bit ARM registration only "
         "survives a restart on a distro that boots systemd — so a machine "
         "that came back unable to run the emulator says so here, with "
         "“Set up emulator…” beside it, instead of leaving it to the next "
         "Start to fail. The log says it is checking before it checks, "
         "since that check is what boots WSL back up. A machine that came "
         "back intact is told nothing."),
    ],
    "Compare": [
        ("What it does",
         "Pick two card images of the same game — two releases, or a modded "
         "card against its stock base — and Compare reports what changed "
         "from A to B: added, modified and deleted files per asset type "
         "(videos, images, scenes, music banks), the sound counts, "
         "adjustment defaults and the high-score board. Copy Report puts "
         "the whole diff on the clipboard as plain text."),
        ("How much of each list you see",
         "Every change list in the report is complete — a version that "
         "renumbers four thousand sounds produces four thousand rows. "
         "\"Rows per list\" (12 / 25 / 50 / 100 / All, next to Copy Report) "
         "sets how many of each you see at once; the rest fold into a "
         "single \"… and N more\" line. DOUBLE-CLICK that line to list the "
         "rest of THAT group and nothing else, with your place on the "
         "screen kept. Changing the setting only re-draws the report "
         "already in memory — the cards are never read again — and it "
         "is remembered the next time you open the app. Copy Report "
         "ignores it entirely and writes every row."),
        ("Open a file the report lists",
         "DOUBLE-CLICK any file row in the report to look at the file "
         "itself — it is pulled off the card it belongs to (image A for a "
         "deleted file, image B for an added or modified one) into a "
         "temp folder and opened with whatever your desktop uses for "
         "that file type. No Extract needed, and it stays quick on a "
         "multi-GB card because only that one file is read. Spike 2 "
         "videos are stored without a file extension, so the app looks "
         "at the first bytes and names the temp copy .mp4 / .png / .jpg / "
         ".wav / .ogg to match; a file it does not recognise keeps the "
         "name it has on the card and may not open on its own."),
        ("Extract Both",
         "Runs a full Extract on image A and then image B into one "
         "parent folder you pick once, each card into its own sub-folder "
         "named after the card file. Use it when the report tells you "
         "WHAT changed and you now want both versions' assets side by "
         "side. Pick the folder that should CONTAIN the two "
         "sub-folders, not a project folder. The second card starts "
         "only once the first has really begun, so cancelling or "
         "declining an overwrite stops the pair there instead of "
         "queueing card B onto some later run."),
        ("How files are diffed",
         "Straight off the cards, no Extract needed: every moddable file on "
         "a Spike 2 card is indexed in the card's own validation manifest "
         "with its size and a digest, so \"modified\" means Stern's own "
         "stored digest changed — comparing two multi-GB cards takes "
         "seconds, not a full read. A scene counts as modified when any "
         "file in its folder changed. Sounds are the exception — see "
         "\"Sounds\" below."),
        ("Sounds",
         "The sounds are packed inside one container file (image.bin) whose "
         "per-sound layout only exists once a card has been extracted, so "
         "from the cards alone the report can show the container's sound "
         "and fragment counts and its size, and nothing more. It "
         "deliberately does NOT judge the sounds by that container's "
         "digest: Stern repacks and re-keys image.bin on every build, so "
         "two releases carrying identical sounds still have completely "
         "different container bytes.\n\n"
         "For the real answer, press Extract Both and then Compare again. "
         "Once both cards have been extracted the Sounds section lists the "
         "sounds that changed, moved to a new slot, were added or were "
         "removed — matched by content first, so one inserted sound doesn't "
         "read as a thousand changed ones. Double-click a listed sound to "
         "play it."
         "\n\n"
         "The match is on the AUDIO, not on the raw file. The first frame "
         "a Spike 2 sound decodes to is read out of whatever image.bin "
         "packs in front of it, so a version that repacks its audio "
         "changes that one frame on every sound at once and nothing "
         "after it. The report steps over that frame and prints a "
         "\"Codec lead-in\" row saying how many pairs needed it, rather "
         "than calling an untouched catalog rewritten."
         "\n\n"
         "The extracts are found by the source card each one "
         "records, so it does not matter which naming options they were "
         "made with or in what order."),
        ("Adjustments and high scores",
         "Both game firmwares are decoded with the same parsers the "
         "Defaults tab uses, then diffed: settings added or removed, "
         "defaults that changed, and high-score places whose default "
         "initials, player name or score moved. As always these are the "
         "cards' compiled defaults — a machine's live settings and scores "
         "are in its own memory, not on the card."),
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
     "to paste into a bug report."),
    ("Where its details come from",
     "Only from the image itself and its filename. A Stern card's version "
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

# Appended to every tab's sections — app-wide behaviours users ask about.
GENERAL_CONTENT = [
    ("The ⚙ settings menu",
     "The gear in the top-right collects the app-wide controls: light/dark "
     "theme, update check (both a manual \"Check for updates\" and \"Check "
     "automatically\", which sets how often the app re-checks while it's "
     "running — startup only, hourly, every 6 hours, or daily), disk-space "
     "management, voice recognition quality, the prerequisite tools "
     "(status, re-check, install), and a re-readable copy of the "
     "first-launch disclaimer (View disclaimer…)."),
    ("Prerequisites",
     "Each manufacturer needs a few tools installed. While anything is "
     "still being checked or missing, a strip under the title lists them: "
     "[?] = still checking, [✗] = missing (\"Install Missing\" sets them "
     "up), [✓] = ready. Once everything is ready the strip tucks itself "
     "away — the ⚙ menu keeps the status, and its "
     "\"Install / repair prerequisites…\" entry stays clickable even "
     "then. All-green means every PROBE passed, not that there is "
     "nothing left to install: ffplay, which the audio Preview needs, "
     "is nobody's probe, and re-running the installer is what brings "
     "the full ffmpeg build that carries it."),
    ("Recent paths",
     "Every file/folder box keeps a per-manufacturer history — open its "
     "dropdown to reuse a recent path."),
    ("Change history",
     "Every replacement pick (with the file it replaced), text edit, staged "
     "default, build and revert is appended with a date and time to a "
     ".history.log file at the root of the project folder — so months later "
     "a slot that says \"changed on disk\" still tells you what it was "
     "changed with, and from where. Open it from Project ▾ → "
     "\"Change history…\"; it's plain text, so it greps and diffs fine too."),
    ("The log",
     "The progress dots and log at the bottom mirror every operation; "
     "right-click the log to copy text for a bug report."),
]

_WIDTH, _HEIGHT = 560, 520


class TabHelpWindow:
    """The single per-app tips window.

    ``show(tab)`` opens it (or re-focuses + re-renders the open one);
    ``refresh(tab)`` re-renders in place without stealing focus/placement —
    used when the user switches notebook tabs or flips the theme with the
    window open.
    """

    def __init__(self, parent, theme_fn):
        self._parent = parent
        self._theme_fn = theme_fn        # () -> current theme name
        self._dlg = None
        self._text = None
        self._tab_name = None

    def is_open(self):
        try:
            return self._dlg is not None and bool(self._dlg.winfo_exists())
        except tk.TclError:
            return False

    def show(self, tab_name):
        """Open (or surface) the window rendered for *tab_name*."""
        if self.is_open():
            self._render(tab_name)
            self._dlg.deiconify()
            self._dlg.lift()
            self._dlg.focus_set()
            return self._dlg
        self._build()
        self._render(tab_name)
        return self._dlg

    def refresh(self, tab_name=None):
        """Re-render the open window (new tab and/or new theme).  Keeps the
        user's placement and stacking order; no-op when closed."""
        if self.is_open():
            self._render(tab_name or self._tab_name)

    def close(self):
        if self.is_open():
            self._dlg.destroy()
        self._dlg = None
        self._text = None

    # -- internals -----------------------------------------------------

    def _build(self):
        sans, _ = platform_font()
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        dlg.transient(self._parent.winfo_toplevel())
        dlg.minsize(420, 300)

        body = ttk.Frame(dlg, padding=(14, 10, 8, 10))
        body.pack(fill=tk.BOTH, expand=True)

        text = tk.Text(
            body, wrap="word", relief=tk.FLAT, borderwidth=0,
            font=(sans, 10),
            padx=4, pady=2, cursor="arrow",
            highlightthickness=0)
        self._text = text
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 10))
        close = ttk.Button(btn_row, text="Close", command=self.close)
        close.pack(side=tk.RIGHT)

        dlg.bind("<Escape>", lambda _e: self.close())
        dlg.protocol("WM_DELETE_WINDOW", self.close)
        dlg.geometry(f"{_WIDTH}x{_HEIGHT}")
        # Centre over the parent window — first open only; a refresh/re-show
        # keeps wherever the user dragged it.  placement.centered_over owns the
        # multi-monitor rule: this used to clamp against winfo_screenwidth(),
        # which is the PRIMARY display, so on a two-screen Mac with the app on
        # the second one the window was dragged onto the other monitor. It read
        # as "the Tips window flashes up and closes".
        dlg.update_idletasks()
        try:
            x, y = centered_over(self._parent.winfo_toplevel(),
                                 _WIDTH, _HEIGHT)
            dlg.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass
        close.focus_set()

    def _render(self, tab_name):
        self._tab_name = tab_name
        sections = HELP_CONTENT.get(tab_name)
        if sections is None:
            # Unknown/renamed tab — show just the general tips rather than
            # nothing so the button never feels broken.
            sections = []
        th = THEMES.get(self._theme_fn()) or THEMES["light"]
        sans, _ = platform_font()

        dlg, text = self._dlg, self._text
        dlg.title(f"Tips — {tab_name}" if tab_name else "Tips")
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        # (Re)apply theme colors every render so an open window follows a
        # light/dark switch instead of keeping the stale palette.
        text.configure(state=tk.NORMAL, bg=th["bg"], fg=th["fg"],
                       selectbackground=th["select_bg"])
        text.tag_configure("h", font=(sans, 10, "bold"),
                           spacing1=10, spacing3=2, foreground=th["fg"])
        text.tag_configure("body", spacing3=4,
                           lmargin1=14, lmargin2=14, foreground=th["fg"])
        text.tag_configure("rule", font=(sans, 10, "bold"),
                           spacing1=16, spacing3=2, foreground=th["gray"])

        text.delete("1.0", tk.END)
        for title, para in sections:
            text.insert(tk.END, title + "\n", "h")
            text.insert(tk.END, para + "\n", "body")
        text.insert(tk.END, "General\n", "rule")
        for title, para in GENERAL_CONTENT:
            text.insert(tk.END, title + "\n", "h")
            text.insert(tk.END, para + "\n", "body")
        text.configure(state=tk.DISABLED)


def show_tab_help(parent, tab_name, theme_name):
    """One-shot helper (tests/back-compat): open a fresh tips window for
    *tab_name* and return its Toplevel.  The app itself goes through a
    long-lived :class:`TabHelpWindow` so "?" re-uses one window."""
    win = TabHelpWindow(parent, lambda: theme_name)
    win.show(tab_name)
    return win._dlg
