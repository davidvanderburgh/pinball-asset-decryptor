# PAD-1040: expression light shows (the cabinet's blades and speaker lights)

BEN (Discord): "Is there a way to read the expression lighting? Ultimately if songs are swapped out, the expression
lighting is no longer in sync with the replaced audio track. An example game would be Led Zeppelin."
David (2026-11-07): "We should have an expression light show creator just like the playfield light show creator."

## What the games do

- The cabinet's **expression lights** are lights of the game's own light table, like inserts: Led Zeppelin LE 1.22
  names 96 blade pixels `EXPRESSIVE LIGHTING L 1..48` / `R 49..96` (lights 128-415, I/O group 1 = node 2 "Cabinet
  Lights", G-R-B channels, bottom up) and 23 speaker pixels `SPEAKER 1..23` (lights 431.., group 6 = node 7). Each pixel
  is one RGB lamp (kind 2) of the lamp table. Every title with blades names them the same way (PAD-500).
- The port's `lamp` lines leave them out (`lampmap.inserts` keeps only the playfield picture's), so no mode could
  touch them.
- Led Zeppelin's `ExpressionLights` singleton picks a cabinet show by the SOUND being played ("Expression Lights
  sound effect out of range" is one of its errors). A song replaced in the Audio tab keeps its request, so the game
  plays the old song's cabinet show over the new music: BEN's report.
- The operator's own way out: EXPRESSION LIGHTS MODE (`AD_EXPRESSION_LIGHTS`, 0-6, default 3; MATCH MODE COLOR,
  GENERAL ILLUMINATION, USER SET COLOR, ALL / REMIX / ORIGINAL SHOWS) and CUSTOM EXPRESSION LIGHTS RED/GREEN/BLUE.

## The design

1. **Ports** carry the cabinet's lights as `cablamp <R,G,B> 0 <name>  # ..., at X,Y` lines (`lampmap.cabinet_lines`),
   placed on the CABINET drawing (0-300 x 0-600, the playfield's range): the left blade down x 12, the right down
   x 288 (pixel 1 at the bottom), the speaker ring at the top.
2. **The runtime** keeps them after the inserts (CAB0 = 256, up to 160) on the same lamp layers, so holding one covers
   the game's own show exactly as an insert hold does (`pm_cab_count/at/xy/paint/release_all`).
3. **Song shows** (`cabshow.cfg`, beside the runtime like idle.cfg / coop.cfg): shows of steps, each tied to a sound
   request. When the sound worker takes that request the runtime starts the show from its first step; it runs while
   the sound plays (and to its length), every cabinet light held, then hands them back to the game.
4. **The engine** is the runtime's own, made for strips: each light's place on its strip (0 bottom .. 1000 top; the
   speaker ring by its angle). The app's preview runs a JS mirror of it, integer for integer, kept equal by a test.
5. **The creator**: the playfield creator's shape (shows list / the preview / steps on a timeline), on a drawing of
   the cabinet, with the song's waveform under the timeline so a show can be cut to the music.
6. **Reading the game's own**: the emulator records the cabinet's lights while a song plays (padled node strips), so
   the game's own show can be seen and used as the start of a new one.

## Status (2026-11-07)

- [x] ports: `cablamp` lines on every shipped port with a cabinet (52 changed, recipes rebuilt, portgen REVISION 10:
      drafted and derived ports read them off the target's own tables)
- [x] runtime: the cabinet range, `pm_cab_*`, song shows (`cabshow.cfg`), the strip engine ("CAB FX"), `cab_show` in
      mode files; armed before the score gate ("only"): a card of shows alone stays on Insider Connected
- [x] the app: the Expression lights tab (lights.py / lights.js / cabfx.js), not behind the mode maker's preview;
      Write puts cabshow.cfg on the card with each show's song as the sound ids that start it (engine
      `_cab_sids_for_build`)
- [x] Make it from the song (cab_auto.py): beat, bars, sections and drops, steps on the bar lines in three styles
- [x] emulator proofs (Led Zeppelin LE 1.22): a mode's show over the game's own on all 96 blades and 23 speaker
      lights (proof 2); the game's own sound 307 starting the card's show on a card with no modes and its end handing
      the lights back (proof 3); the build mapping that song's slot 156 to sound 307 (C:/tmp/PAD-1040/sids_check.py)
- [ ] (not done) recording the game's own cabinet show into a show: the emulator's playfield window already shows it
      live (PAD-500)
