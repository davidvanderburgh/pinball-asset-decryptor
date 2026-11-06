# Inactivity pauses the timers on Guardians of the Galaxy (PAD-1022)

Joe_Blasi (Pinside): "can this do an quick fix the allow inactivity to pause timers that does not work on guardlians".

## What the games do

Every Spike 2 framework offers the operator **ALLOW INACTIVITY TO PAUSE TIMERS** (`AD_INACTIVE_TIMER`, 0..1, default
1). The titles honour it in their OWN timer code (it is not a framework feature):

- TMNT 1.59 (symbol build): the timer's should-pause check 0xadf70 asks `get_adjustment(200) == 1` and then whether
  framework timer 15 has run out; 0x1432e4 re-arms that timer to 372 ticks (6 s) at every score.
- Godzilla LE 1.16: the same at 0x622e8 (adjustment 166, timer 11, re-armed at 0x18de90 in the title's score code).

Census of the 53 latest builds (C:/tmp/PAD-1010/elfs, `calls.py` / `ldsites.py` in C:/tmp/PAD-1022): every title that
shows the setting reads it once (Munsters through a wrapper at 0x642b8), except **Guardians 1.15 Pro and LE**: none
of the eight loads of 175 is a setting read. Batman 66, Elvira 3, Bond 60th, JP Pin, Metallica, Star Wars ELG and
X-Men do not have the setting at all.

## Guardians' clocks (Pro addresses; LE in the port)

- **Missions** (Pod Chase, Escape Kyln, Knowhere, Quill's Quest, Yaka Arrow, Sanctuary, Sibling Rivalry, Antiquities
  Shop): one shared timer process 0xbfc14, started by 0xc00a8 from a descriptor {process, ..., song request at +0x24}.
  The clock is the mission's SONG: (end marker - stored song position) / 44100 while the song plays, and the mission
  ends when the song reaches the marker. The stored position is a table by player and song (0x5f2610,
  `[song * 4 + player - 1]`) that the song tracker 0xfb518 writes each frame from the voice. When the song is not
  playing the process counts the seconds by itself. The ball's song is picked at the plunge (each mission song is
  one of the tracker's 20), so a mission normally runs on its own song.
- **Headphone Hurryup and the value hurry-ups** wait while the shared check 0x41824 says so (ball off the playfield,
  a show in process group 0x88..0xb8, pause process 0x83). Double Scoring calls the check and drops the answer; Super
  Scoring and the Groot lock never ask.

## The fix (pad_mode_runtime.c "inactivity pauses the game's timers")

Inactive = in play, the setting on, no `score_add` for 6 s (the titles' 372 ticks); coming into play counts as a
score. Then:

1. the song tracker is wrapped and writes a HELD position: it moves with the song while the player is active and
   stands while they are not. The music and its light shows play on; the clock holds. A song that runs out under a
   hold and comes round keeps counting from the held position; any other break (another song, player, a seek, the
   game playing it again from the table) starts again from the voice.
2. the shared check is wrapped to answer paused while inactive. Its second word is a `bl`, so `hook_wrap_at` learned
   to make a moved `bl` itself in the trampoline (`add lr, pc, #0; ldr pc, [pc, #4]; ldr pc, [pc, #-4]`).

It arms whenever the port names the lines, before the score gate. The Modes tab's **Inactivity pauses timers** tick
(only on games that need it) puts `idle.cfg` beside the runtime; with no modes on the card it says `only` and the
runtime arms nothing else, so the card's scores stay on Insider Connected. Port lines: `site timers_paused`,
`site song_track`, `data song_positions`, `value song_now_at 0x160`, `value inactive_adj 175` (port_tool drafts all
five onto another build).

## Proof (emulator, hidden, muted; C:/tmp/PAD-1022/rig, `idle_test_mode.c`)

The instrument starts the mission whose song is playing and logs its clock each second; the job scores every 2 s for
20 s, waits with no score, then scores again.

- Stock (port without the lines), Pro and LE: the clock counts straight through the wait (Pro Knowhere 85 -> 7, LE
  Yaka 54 -> 0 and the mission ended).
- Fixed, Pro (Pod Chase): 6 s into the wait the clock stopped at 124 s and stayed there for the rest of the 30 s while
  the song played on (34 -> 61 s); at the next score it counted on from 124. LE (Knowhere): held at 55 s, the same.
- A 30 s wait on Yaka Arrow's 54 s song ran the song out under the hold; the first build gave the clock its full 54 s
  back. With the held position (final build), a 55 s wait on the same song (LE): the song came round at 54.7 s, the
  clock stayed at 21 s, and after the next score counted 20 -> 5. Pro, Quill's Quest, 55 s wait: held at 135 s for
  53.5 s; Pro, Sibling Rivalry, 30 s: held at 68 s for 28.5 s.
- Idle-only cards, Pro and LE: `armed: inactivity pausing timers only (idle.cfg says the card has no modes) -
  nothing else is hooked`.
- The first build's trampoline crashed a game start (`add lr, pc, #4`: pc reads 8 ahead, so the call came back one
  word too far); `test_the_wrap_calls_a_moved_bl_itself_and_comes_back` checks the words.

Rig slot 2 starts no game on any Guardians card, stock included: its `dump/ballfeed.off` (2026-10-27, "PAD.Controller",
another ticket's) makes the ball feeder stand aside. Left as it is; the proofs ran on the other slots.
