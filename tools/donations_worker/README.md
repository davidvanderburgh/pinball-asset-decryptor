# The animal shelter donations Worker

The app's paw chip ("$4,320 to shelters") and its Animal shelters window read
one URL and write one URL. This folder is the service behind them: a
Cloudflare Worker in front of a D1 table. Free tier, no server to keep up.

It takes no money. People give to an animal shelter near them, then report
the amount in the app, and the Worker keeps the running total everyone sees.

## Deploy once

Needs a Cloudflare account and Node. From this folder:

```bash
npx wrangler login
npx wrangler d1 create pad-donations
```

Paste the printed `database_id` into `wrangler.toml`, then:

```bash
npx wrangler d1 execute pad-donations --remote --file schema.sql
npx wrangler secret put APP_KEY
npx wrangler secret put ADMIN_KEY
npx wrangler secret put IP_SALT
npx wrangler deploy
```

- `APP_KEY` must equal `DONATIONS_APP_KEY` in `pinball_decryptor/core/config.py`.
  It ships inside the app, so it is only a speed bump against casual
  scripts; the per-address limit (five an hour) and the single-entry cap
  (10,000) are the real guards.
- `ADMIN_KEY` is yours alone: it lists rows with their ids and hides one.
- `IP_SALT` is any long random string. Addresses are never stored: a row
  carries a salted hash of its sender's address for the five-an-hour limit,
  and that hash is blanked once the row is an hour old, so nothing in the
  database can be matched to an address after that. Nothing is logged.
  What a row keeps for good is what the user typed: amount, shelter, place,
  and a name if they gave one, with their choice of whether it shows.

`wrangler deploy` prints the URL (`https://pad-donations.<account>.workers.dev`).
Put it in `DONATIONS_URL` in `pinball_decryptor/core/config.py` and release.
Until then the app shows the chip with no total and says the total cannot
be reached when someone tries to add to it (their entry is kept and sent
once it can).

## Hear about every entry on Discord

In your Discord server: Server Settings, Integrations, Webhooks, New
Webhook, pick the channel, Copy Webhook URL. Then

```bash
npx wrangler secret put DISCORD_WEBHOOK
```

and paste it. From then on the Worker posts a line for every entry ("🐾
New donation: $30 to Lollypop Farm in New York, US as David · app 1.266.0,
tally now $4,350 from 62 donations"), for every held one ("⏸ HELD for your
review: ..." with the curl that approves it), and for every take-back. It
posts after the app's request has been answered, so a slow or dead webhook
never slows or fails an entry; without the secret it posts nothing. A name
the user chose not to show is not posted (the entry reads "anonymous"; the
name is in the admin list); shelters and shown names are posted as typed,
with mentions disarmed.

## Routes

| | |
|---|---|
| `GET /v1/summary` | total in USD, count, the milestones passed and when, the last twelve |
| `GET /v1/all?offset=0&limit=100` | every live donation, newest first, a page at a time |
| `POST /v1/donate` | header `X-PAD-Key`; JSON `amount, currency, shelter, name, show_name, app_version` |
| `GET /v1/admin/list` | header `X-PAD-Admin`; the last 200 rows with ids; `held` = 1 is one waiting for your review |
| `POST /v1/admin/review/<id>` | header `X-PAD-Admin`; JSON `{"approve": true}` counts a held row from then on, `false` hides it |
| `DELETE /v1/donate/<id>` | header `X-PAD-Admin` hides any row; `X-PAD-Key` plus `X-PAD-Edit` (the token the POST answered) lets the app that added a row take it back |
| `POST /v1/report` | header `X-PAD-Key`; JSON `title, body, name, app_version, platform, picture_type, picture_b64`: the app's Report a problem (PAD-780) |
| `GET /v1/report/status?ids=a,b` | header `X-PAD-Key`; each id's `state` (received, filed, released, closed, unknown), `version` and `message`: how the app tells its user |
| `GET /v1/admin/reports` | header `X-PAD-Admin`; the reports not yet taken, oldest first, picture included |
| `POST /v1/admin/reports/<id>/taken` | header `X-PAD-Admin`; blanks everything the user wrote, state `filed` |
| `POST /v1/admin/reports/<id>/answer` | header `X-PAD-Admin`; JSON `{"state": "released"\|"closed", "version", "message"}`: what the app shows its user |

Remove a junk entry:

```bash
curl -X DELETE -H "X-PAD-Admin: $ADMIN_KEY" https://pad-donations.<account>.workers.dev/v1/donate/<id>
```

## Problem reports

The app's Report a problem window (PAD-780) posts its record here: the
user's words, the app's version and system, the card and project it had
open, the tail of its log and, if they added one, a picture shrunk to a
JPEG under 700 KB. The row is the whole record plus the picture (base64),
so it stays well under D1's 2 MB row limit. David's tracker (pad-triage,
`padtriage/appreports.py`) polls `/v1/admin/reports`, files each as a
ticket and posts `/taken`, which blanks everything the user wrote; from
then on the row is only a state. When the ticket ships or closes the
tracker posts `/answer` with the version and David's message, and the app
that sent the report (it keeps its ids) reads `/v1/report/status` and
tells the user in the app. No address is asked for or stored; an answered
row is dropped after 90 days. The same five-an-hour, hash-blanked-after-
an-hour rule as donations applies. Discord gets one line per report (the
title, the app version and the platform; never the name or the record).

Adding this to a Worker deployed before it is one command, since the
schema only creates what is missing:

```bash
npx wrangler d1 execute pad-donations --remote --file schema.sql
npx wrangler deploy
```

## Big entries wait for you

An entry worth more than `HOLD_OVER_USD` (299) in `worker.js` is stored
held: it is not in the total, the list or the board until you approve it.
The app tells the person so before they send it and marks it "in review"
in their Yours list. See what is waiting and decide:

```bash
curl -s -H "X-PAD-Admin: $ADMIN_KEY" https://pad-donations.<account>.workers.dev/v1/admin/list | python -m json.tool | grep -B8 '"held": 1'
```

```bash
curl -X POST -H "X-PAD-Admin: $ADMIN_KEY" -H 'content-type: application/json' -d '{"approve": true}' https://pad-donations.<account>.workers.dev/v1/admin/review/<id>
```

## Rates

A donation is converted to USD when it is reported, with the fixed table
`RATES` in `worker.js`, and the stored figure never changes after. Update
the table now and then and `npx wrangler deploy`. The list shows each
donation in its own currency.

## Milestones

`MILESTONES` in `worker.js` is the ladder the app's thermometer climbs
(500, 1k, 2.5k, 5k, 10k ...). `core/donations.py` holds the same list;
change both.

## Prove it, before and after deploying

Three layers, cheapest first:

```bash
node --test worker.test.mjs
```

runs the handler against an in-memory stand-in for D1 (logic only).

```bash
npx wrangler d1 execute pad-donations --local --file schema.sql
npx wrangler dev --local --port 8787
```

runs the REAL worker.js on a SQLite-backed D1 on this PC, no account
needed (secrets for it go in `.dev.vars`: `APP_KEY=...`, `ADMIN_KEY=...`,
`IP_SALT=...`; the file is git-ignored). Then, from the repo root:

```bash
python scripts/donations_smoke.py http://127.0.0.1:8787 --admin <ADMIN_KEY>
```

drives the app's own client (core/donations.py) through every call: summary,
add, take back, the hold on big entries, the review route, the paged list;
it leaves nothing behind. And

```bash
python scripts/shot_pad754.py --out C:\tmp\PAD-754_shots --tag live --url http://127.0.0.1:8787
```

runs the real app against it and adds an entry through the window.

**After `wrangler deploy`**, run the smoke script once against production:

```bash
python scripts/donations_smoke.py https://pad-donations.<account>.workers.dev --admin <ADMIN_KEY>
```

(The app key it sends is `DONATIONS_APP_KEY` from core/config.py; if the
service answers "Not from the app", the `APP_KEY` secret does not match.)
Then start the app, open Donate, add $1 and take it back from Yours.

What differs in production from the local run: the real Cloudflare edge in
front (HTTPS with a certificate the app trusts through certifi, the
visitor's real address for the rate limit, the `max-age=60` on the summary,
which only a browser would honour and the app does not), D1 on
Cloudflare's storage instead of a local SQLite file, and the secrets you
put in with `wrangler secret put`. The code path is the same, but the edge
is not transparent: Cloudflare's browser integrity check refuses Python's
default user agent with a 403 (error 1010), which the local run could not
show. Every request the app and the smoke script make therefore names the
app (`User-Agent: Pinball-Asset-Decryptor-Donations`); keep that on any new
call. Deployed 2026-10-27; the smoke script passed against the live Worker
the same day, including the review route.
