# Score feed overlay (sample)

A small server and a page that show your machine's game live: every player's score, who is up, the ball, and the
multiballs, bonus and modes running. Use it as a Browser source in OBS for streaming, or open it on a second screen.

## What you need

- The card built with **Score feed** on (the app's Network tab), **Also during the game** ticked, and the address
  set to this computer, e.g. `http://192.168.1.50:8080/scores` (the path can be anything).
- Python 3.8 or later on this computer. Nothing else to install.

## Run it

    python overlay_server.py

It listens on port 8080 (`--port 9000` for another; use the port your address names) and prints a line for each
post the machine sends. If your computer's firewall asks, allow it on your private network.

Then open `http://localhost:8080/` in a browser on this computer, or `http://<this computer's IP>:8080/` on
another screen. Add `?bg=1` for a dark background.

## OBS

Sources, +, Browser. URL `http://localhost:8080/`, width 1280, height 300. The page's background is transparent,
so it sits over your camera or playfield shot.

## What it receives

Each event is one JSON object posted to the address (the Network tab's "What your server receives" lists every
field), for example:

    {"source":"PAD score feed","event":"ball_start","seq":12,"game":"Godzilla Premium/LE 1.16","game_number":3,
     "ms":81234,"time":1794326400,"players":2,"player":2,"ball":1,"scores":[123450,0]}

`/state` on this server is the game as it stands, as JSON, if you would rather build your own page.
`--log feed.jsonl` keeps every post, one a line.

The machine never waits for this server: if it is not running, the game plays on and the events are dropped.
