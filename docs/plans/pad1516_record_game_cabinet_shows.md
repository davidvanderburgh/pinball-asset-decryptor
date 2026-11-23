# PAD-1516: the game's own speaker animations, recorded, in the Expression lights tab

Jim-Beam (Bond Pro 1.06 project): "opened the speaker light tab and saw no stock light animations, I hoped to see the
stock ones. Would it be possible to store/copy those animations to take it to other titles like Iron Maiden?"

## Done (round 2, commit 026d79da6)
New show > From another project: copies shows between projects (cab_shows.copy_shows, lights.other_shows / copy_in).
On another game a copy has no song; a show of a game's own frames (fx `game`) stays on its game.

## What Bond does (emulator, 2026-11-23, Bond Pro 1.06, PAD card staged, padled node 7 sampled every 0.25 s)
- Attract: 85 distinct speaker frames in 49 s. ~0-17.5 s a smooth gradient travelling round the rings, hue stepping
  red > magenta > blue > cyan > green > yellow > orange > red; then ~17.8-30 s whole-ring flashes (orange bf3f00,
  magenta ff003f, red ff0000, green 00ff3f) with part-ring blocks; then it repeats (attract cycle).
- In a game: one steady colour, every channel 0x55 (BACKGROUND SPEAKER COLOR at its default), flashes from shows.
- The PAD runtime with a mode staged left all of this alone (the attract above was recorded with it loaded).
- Bond keeps no frame table (cab_stock finds none): the light-show engine draws it in code. So: RECORD it.
- Raw samples: //wsl.localhost/PAD-Runtime/home/pad/padslots/1/rigjob.james_bond_pro-1.06/spk.txt (copy in
  C:/tmp/PAD-1516/spk_pad.txt). Rig job: C:/tmp/PAD-1516/run.sh + spkjob.sh + spksample.py (rigbatch, slot 1).
  NB both list lines share a key, so the second run's JOB_OUT overwrote the first's: give each its own JOB_OUT.

## To build
1. **Recorder** (rig side): run the project's card hidden to attract (rigjob.sh job_boot / job_wait_attract), sample
   padled at the game's rate (~30 Hz: ledframes notes 33 ms pairs; sample 40 Hz and keep changes), for every cabinet
   light of the port (`cablamp` lines: R,G,B light ids -> node = group+1, channel = device index; check the mapping on
   one speaker with the LED Tests or by lighting one through pm_cab_*). Write `<project>/cab_rec/<name>.bin`:
   header {magic, version, period ms, frames, lights} + frames x lights x RGB, lights in the port's cablamp order, with
   each light's u (0..999 round its ring / up its blade) and side so another cabinet can map it.
2. **Tab**: where it says "This game keeps no expression light shows of its own the app can read", a
   "Record the game's own" button (needs the emulator; progress like Run in emulator). Recordings are listed with the
   game's own shows (stock list), played in the preview from their frames, and "Make a show of it" makes a project
   show with a `frames` step per lane (step: {fx: "frames", ms, rec: <name>, from}).
3. **Runtime**: cabshow.cfg `frames <name> <period> <frames> <lights>` + a `.bin` beside it (Write stages it with
   cabshow.cfg); a `frames` step paints each cabinet light from the recording, light k <- recorded light nearest in u
   on the same side (one ring alone: nearest u). cabfx.js mirrors it; the parity test (test_pad1040_cab_shows.py,
   WSL gcc + node.exe) covers it.
4. **Copy**: copy_shows carries a `frames` show's recording file to the other project (unlike `game` steps they play on
   any cabinet). Iron Maiden's added speaker lights (PAD-1448) take it by u.
5. Proof: record Bond Pro 1.06 attract; play the made show on Iron Maiden LE 1.18 with added speakers in the emulator
   (padled node 2, PAD-1448 verify recipe) and compare against the recording at the game's dimming.

Decision for David (listed on the ticket): the recording is made from the user's own card on their PC and kept in
their project; nothing of the game's ships with PAD.
