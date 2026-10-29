# Common problems

[← Back to the README](../../README.md)

What new users most often run into, and what to do. New to the app? Start
with [Getting started: your first mod](getting-started.md).

Not listed here? **Report a problem** in the top bar sends the developer
what happened, with the app's log, after showing you exactly what goes.

## Installing and starting

| What you see | What to do |
|---|---|
| A red ✗ in the prerequisites row | Hover it for what is missing. On Windows, run **Install Prerequisites** from the Start Menu (or ⚙ > **Prerequisites** > **Install / repair prerequisites…**), then **Re-check prerequisites**. On Linux, **Install Missing**. |
| Install Prerequisites reports a problem with Ubuntu, WSL or virtualization | See [If Install Prerequisites reports a problem](install.md#if-install-prerequisites-reports-a-problem): each message has its fix. |
| macOS won't open the app | The first launch needs **Open Anyway** in System Settings > Privacy & Security ([macOS](install.md#macos)). |
| **"Audio preview needs ffplay"** | Answer **Yes** and the app installs the full ffmpeg. Only previewing needs it. |
| Can't read the SD card in a reader | On Windows that needs Administrator. The app's own shortcuts start it that way; started some other way, close it and use the shortcut. |
| The disk is filling up | ⚙ > **Manage disk space** shows what the app keeps and frees it ([Disk space](install.md#disk-space-windows)). |

## Picking and extracting

| What you see | What to do |
|---|---|
| **Not recognized** | Usually the wrong kind of file, a copy that hasn't finished, or another manufacturer's file (the badge under the box offers a one-click switch). Check the game is listed in [Supported manufacturers](manufacturers.md). |
| Replace tabs show a lock | They need an extract first: pick the card, then **Extract** into a project folder. |
| **"The source image has changed"** | The card image is no longer the file you extracted from. Re-extract, or **Dismiss** it for that image. |
| My edits are gone after extracting again | Extracting again into the same folder overwrites it (it asks first). Use one project folder per game version. |
| **⚠ not on this card** on a row | A file from another version's project or mod pack. **Transfer Mods to New Version** (Mod Pack tab) carries mods over to a new version. |

## Replacing

| What you see | What to do |
|---|---|
| Can't find the sound I want | Set **Type** to **Music**, **Sound FX** or **Callouts**, search part of its name, or tick **Play sequentially** and listen down the list. |
| My song is cut short, or has silence at its end (Stern Spike 2) | A replacement is cut or padded to the original's length. Tick **Allow replacements longer or shorter than the original** under **Advanced…** for its own length. |
| A replacement is too loud or too quiet | Use **Loudness for this clip** beside the Replacement player. Changing the file's own level does nothing: replacements are matched to the original's loudness. |
| Picks made, but nothing changed | Picks only reach the card on a build: press the build button on **Write**. Picks are kept in the project folder between sessions. |

## Building and the machine

| What you see | What to do |
|---|---|
| **A build that won't fit** (Stern Spike 2) | It stops before writing anything and names the card size that would take it: pick that under **SD card size** on Write and use a bigger card ([SD card size](using-the-app.md#sd-card-size-stern-spike-2)). |
| A feature says it **needs an image build, not a direct SD write** | Longer sounds, music modes, play in turn and the like need a full image build. Use **Build / flash SD card…** and build the image. |
| **GAME VALIDATION ERROR** on the machine | A card the app built passes the machine's checks; a file changed by hand on the card afterwards won't. Rebuild from the app, and send a **Report a problem** if it still shows. |
| I want the stock game back | Put the original card back in, or flash your backup image (**Save card as image…** on Extract makes one). |

## Emulate

| What you see | What to do |
|---|---|
| An amber notice on the Emulate tab | Something this PC needs is missing. **Set up emulator…** installs it; **Check setup…** writes the full answer to the log. |
| The first **Start** takes minutes | It builds the game's Linux from your card once. Later starts take seconds. |
| Black game window, no window, black videos, or a stuck window | See [When something goes wrong](emulate.md#when-something-goes-wrong). |
