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
         "bringing a hot music clip down to the level of its neighbours."),
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
         "every change the next build will pack, not just this session's."),
        ("Preview",
         "Two players side by side — the original on the left, your "
         "replacement on the right — each with its own controls, so you can "
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
         "of audio: Music (song/bank tracks plus anything at least 20 "
         "seconds long — some pins store songs as Sound-Test-named "
         "sequences), Sound FX (named by the game's own Sound Test menu), "
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
         "replaced."),
        ("Undo",
         "Right-click a slot to remove an un-built assignment or revert an "
         "already-changed file."),
        ("Seeing where a clip plays",
         "Right-click a slot and pick \"Show scene contents…\" to open the "
         "Scenes window on the scene that plays it, with the images, fonts "
         "and text it shares the screen with."),
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
         "time. One typeface is baked at many sizes and each is its own "
         "font here, so Apply offers to fit the same font file into every "
         "size of it at once. If the font has an OUTLINE companion (a "
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
         "on its own. \"Behind\" puts the preview on something other than "
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
         "preview redraws with your version. Click any column heading to "
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
         "want a closer look at a fast one. \"Save preview…\" writes a PNG "
         "(or an animated GIF). \"Rebuild previews…\" re-reads the scene "
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
         "Administrator. (Other machines keep a plain Build button.)"),
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
         "records which game/version it was made from."),
        ("Transfer mods",
         "\"Transfer mods from another extract\" (where available) carries "
         "your Replace edits from an older firmware's extract onto a new "
         "version's extract. Audio is matched by content signature, so it "
         "survives renumbered slots and renamed files; anything that can't "
         "be matched is reported instead of silently dropped.\n\nFields 1 "
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
         "in its Adjustments menu. The master volume is the one to know "
         "about: it lives on a service screen, and on titles with a "
         "first-boot Guided Setup the wizard picks a volume of its own — so "
         "the number the operator menu shows may not be the default you set "
         "here. See the Menu column in the all-settings list below the form "
         "for the same information on every setting."),
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
         "nothing rather than guessing."),
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
         "then verifies nothing survived."),
        ("It runs the card you pick here, not the Input box",
         "This is the one tab that ignores the Input box: point it at a card "
         "image of its own. That image is mounted READ ONLY and run in place — "
         "nothing is extracted and nothing can write to it — so a stock card "
         "and your own build both work, and replacing an asset on the Replace "
         "tabs does not change what the emulator plays until you build a card "
         "and pick it here. The path is remembered per project, so it comes "
         "back on the next launch without another Browse."),
        ("Waiting at Tech Alerts is not a fault",
         "The game boots to its Tech Alerts screen and waits there for an "
         "operator, exactly like the real machine. Press a switch in the game "
         "window — Enter is Service Select — and it carries on. The status "
         "line says \"Waiting at Tech Alerts\" rather than pretending "
         "something is wrong. \"Stuck at Tech Alerts\" is the different one: "
         "it means the skip-to-attract helper pressed several times and the "
         "screen never changed, and its hint says what to try."),
        ("Skip to attract mode",
         "Ticked by default. It waits until the node bus has finished bringing "
         "up — that is the point at which the game will actually accept an "
         "operator — and then presses Service Back once, which takes it "
         "straight to attract mode. It cannot be saved instead: the screen is "
         "a live readout of the boot checks, not an acknowledgement the "
         "machine remembers, and the emulator's NVRAM already persists between "
         "runs. Untick it to drive the boot yourself."),
        ("Sound",
         "The game's audio is played out to your speakers — through WSL on "
         "Windows, and on macOS over a local stream played by ffplay, which "
         "ships with the ffmpeg the prerequisites already install. It "
         "only makes sound while it is actually running, so silence after the "
         "boot chime usually means it is still waiting at Tech Alerts. The "
         "status line shows frames played and frames dropped — dropped should "
         "stay at zero."),
        ("Video",
         "Clips play. The game's own decoder is an i.MX6 hardware block this "
         "PC does not have and the card carries no software fallback, so the "
         "host decodes each clip with ffmpeg and publishes the frames into a "
         "shared ring the game draws from. Scenes, text, lamps, switches and "
         "sound all work too."),
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
         "ball had rolled over it. It builds itself from the title you are "
         "running, so any Spike 2 game gets one. The switches are the one "
         "part that needs the game to be up: it publishes its switch list a "
         "minute or so into a run, and they appear on the playfield as soon "
         "as it does, without restarting anything."),
        ("Install Docker… (macOS only)",
         "The emulator is a Linux program, and a container is how a Mac runs "
         "one — so Docker is to macOS what WSL is to Windows here. This "
         "button appears only when Docker is missing or not running, and does "
         "whichever is needed: it starts Docker Desktop, or installs it (via "
         "Homebrew in Terminal if you have Homebrew, otherwise it opens the "
         "download page). It disappears once Docker is ready. Windows and "
         "Linux never see it and never need Docker to emulate."),
        ("Set up emulator… (Windows only)",
         "The tab asks this PC what the emulator still needs before you press "
         "anything, so a run does not stop on a missing tool a minute after "
         "Start. A machine that is ready shows nothing at all. One that is not "
         "gets an amber notice naming the fault and each missing package with "
         "what it is for, and this button to fix it: it installs those "
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
         "so one apt cannot get never blocks the rest. If nothing can help — "
         "sources trimmed, or a distro out of support — the log says that "
         "plainly rather than inviting another press. "
         "Linux sees the notice but no button, because there the same work "
         "needs a sudo password this app has nowhere to ask for — the notice "
         "prints the command for that machine instead. macOS sees neither: "
         "its container already carries all four, so Docker is the "
         "prerequisite there."),
        ("Restart WSL…",
         "For the two faults that are not the emulator's to fix: a game "
         "window left on screen that will not close (its X does nothing "
         "because nothing is behind it any more), and crackly or stuttery "
         "sound after a long session. Both live in WSL rather than in the "
         "game, and restarting WSL is the cure for each. It closes "
         "everything running in WSL, not just the emulator, so it asks "
         "first and stays greyed out while a run is up — stop the game, "
         "then use it. Nothing on disk is lost."),
    ],
    "Compare": [
        ("What it does",
         "Pick two card images of the same game — two releases, or a modded "
         "card against its stock base — and Compare reports what changed "
         "from A to B: added, modified and deleted files per asset type "
         "(videos, images, scenes, music banks), the sound counts, "
         "adjustment defaults and the high-score board. Copy Report puts "
         "the whole diff on the clipboard as plain text."),
        ("How files are diffed",
         "Straight off the cards, no Extract needed: every moddable file on "
         "a Spike 2 card is indexed in the card's own validation manifest "
         "with its size and a digest, so \"modified\" means Stern's own "
         "stored digest changed — comparing two multi-GB cards takes "
         "seconds, not a full read. A scene counts as modified when any "
         "file in its folder changed. Sounds are packed inside image.bin "
         "and can't be listed one by one here: the report shows the sound "
         "and fragment counts and whether the audio container changed at "
         "all — for a sound-by-sound diff, extract both cards and compare "
         "the WAVs (the length-prefix naming option helps line them up)."),
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
     "is read from the vendor filename, or — on a renamed card — from the "
     "card's own update index, and the short Version ID (like VEN106LE) is "
     "assembled from the title code inside the game firmware. Videos, "
     "images, scenes, sounds and sound fragments are all counted straight "
     "off the card, no Extract needed: the sound counts are the asset "
     "container's own header words. \"Sounds\" is what an Extract decodes "
     "to WAVs; \"Sound fragments\" is the (larger) pool of audio pieces "
     "the game's sound requests draw on — a request can chain several "
     "fragments, and several requests can share one."),
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
     "theme, update check, disk-space management, voice recognition "
     "quality, the prerequisite tools (status, re-check, install), and a "
     "re-readable copy of the first-launch disclaimer (View disclaimer…)."),
    ("Prerequisites",
     "Each manufacturer needs a few tools installed. While anything is "
     "still being checked or missing, a strip under the title lists them: "
     "[?] = still checking, [✗] = missing (\"Install Missing\" sets them "
     "up), [✓] = ready. Once everything is ready the strip tucks itself "
     "away — the ⚙ menu keeps the status."),
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
