# Getting started: your first mod

[← Back to the README](../../README.md)

New to the app? This walks through one small mod from start to finish:
**swap one song** in a Stern Spike 2 game (the Disco multiball tune on
Deadpool, say). Every other kind of change follows the same path. When
something doesn't go to plan, see [Common problems](common-problems.md).

**What you need:**

- The app, installed with its prerequisites ([Installing](install.md)).
- The game's SD card, or an image of it (a `.raw` / `.img` file).
- The song you want, as almost any audio file (mp3, wav, ogg, flac, m4a…).
- A spare SD card for the new build. Keep the machine's own card as it is:
  it is your way back.

## 1. Pick the card

Open the app and click **Stern Pinball** on the picker. On **Select card**:

- **From SD-card image**: **Browse…** to the image file, or
- **From SD card**: put the card in a reader and pick it (on Windows this
  needs the app running as Administrator, which its shortcuts do).

The page shows the game's loading screen and **Card details** (game,
version, edition), so you can see it is the right card.

> **Back up first.** Reading straight from the machine's card? On the
> Extract tab, **Save card as image…** copies the whole card to a `.raw`
> file. Do it once, before anything else.

## 2. Extract

On **Extract**, choose an empty **Project Folder** (one per game version)
and press **Extract**. Ticking only **Audio** is enough for a song swap and
is quicker.

The first extract of a card takes a while: the sounds are decoded by
running the game's own code. The log at the bottom says what it is doing.
That folder is now your **project**; the Replace and Write tabs all work
out of it, and it remembers your picks between sessions.

## 3. Find the song

Open **Audio** (under Replace). Every sound on the card is a row, named by
the game's own Sound Test menu where the game has one.

- Set **Type** to **Music** to see only the songs (where the game names
  its sounds).
- Type part of a name in **Search** (try `MX`, `TUNE` or a mode's name).
- Click ▶ on a row to hear it. Tick **Play sequentially** and it carries
  on down the list, so you can listen through the songs until you hear
  the one you want.

## 4. Pick your song for it

Click the row's **Replacement** cell (or select the row and press
**Choose…**) and pick your file. That's it: the app fits it to the slot's
format and loudness when it builds.

- **Original** and **Replacement** play side by side, so you can compare.
- **Length:** by default your song is cut or padded to the original's
  length. Tick **Allow replacements longer or shorter than the original**
  under **Advanced…** to have it play at its own length.
- **Too loud or quiet?** Use **Loudness for this clip** beside the
  Replacement player, not your audio editor.
- Changed your mind? **Remove replacement** drops the pick.

## 5. Try it on the PC (optional)

The **Emulate** tab plays the real game on your PC. Tick **Apply my
replaced assets on top, without rebuilding the card** and press **Start
emulator**: start a game and play to the multiball to hear your song, with
nothing built yet. The first run sets up for a few minutes. See
[Emulate](emulate.md).

## 6. Build the card

On **Write**, press **Build / flash SD card…**. Tick building the image,
flashing it onto an SD card, or both. The new image goes in the project's
`build` folder; flashing erases the card you pick, so check it is the
spare.

The build passes the machine's own checks, so the game boots it without a
GAME VALIDATION ERROR.

## 7. On the machine

Power the machine off, swap in the new card, power on. To go back, put the
original card back in (or flash your backup image onto a card).

## Next steps

- **More of the same:** videos, pictures and text work the same way on the
  **Video**, **Images** and **Text** tabs. Pick, then build.
- **Several songs for one multiball:** right-click a song > **Play in
  turn** or **At random**.
- **A choice of soundtracks:** **Music modes** lets the service menu switch
  between sets of songs.
- **A new game version came out:** **Transfer Mods to New Version** on the
  Mod Pack tab carries your picks over.
- **Other manufacturers** follow the same four steps (pick, extract,
  replace, write); what each one can change is in [Supported
  manufacturers](manufacturers.md).
- Every tab has a **?** button in the top bar with tips for that tab.

The full tour of every tab is [Using the app](using-the-app.md).
