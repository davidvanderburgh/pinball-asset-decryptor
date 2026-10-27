# Animal shelter donations (PAD-754)

The app takes no money. David tells people who ask how to give back to
donate to an animal shelter near them instead. This feature keeps a running
total of what PAD users report giving, so everyone can see it grow.

## What the user sees

- **The paw chip** in the top bar, beside the version chip: "$4,320 to
  shelters" (or "Animal shelters" before the first total arrives). Click it
  and the window opens. The gear menu has the same entry.
- **The window**: a one-line pitch (no donations here, give to a shelter,
  then tell us so it counts); a thermometer toward the next milestone on a
  ladder (500, 1k, 2.5k, 5k, 10k, 25k, 50k, 100k, 250k, 500k, 1M) with the
  date the last one fell; the last twelve donations (name or Anonymous,
  shelter, the amount in its own currency); a small form: currency, amount,
  shelter and name both optional, where the shelter is (a country from a
  list, a state or province typed), a "show my name" tick, Add to the total.
  Footer line: honor system, nothing else about you is sent.
- **Top places** (David, mid-ticket): a board under the list ranking
  "Texas, US", "United Kingdom" and so on by what was given there, with a
  bar each, so states and countries can race. The place is optional; an
  entry that names one is also easier for David to vet in the admin list
  (shelter name plus location). A drawn map is the follow-up, once there
  are enough places to light up.
- **Once, unasked**: after the first successful card write on an install,
  the window opens with "Your card is written." in front of the pitch. It
  never opens by itself again; the chip is always there.

## What goes over the wire

Amount, currency, shelter text, display name, whether to show the name, and
the app version. No machine id, no email, no paths. The service stores a
salted hash of the address for its rate limit, nothing more.

## Pieces

| | |
|---|---|
| `tools/donations_worker/` | the Cloudflare Worker over a D1 table, its schema, config, README and node tests |
| `core/donations.py` | the entry (validate), the wire (fetch, submit), the cache, and `view()` - the one shape the page renders |
| `webui/shellx_donations.py` | the `shellx` mixin: cache + settings, background fetch, the once-only prompt, the `shellx.donations_*` calls |
| `webui/static/js/shellx_dialogs.js` | `DonationsDialog` |
| `webui/static/js/shell.js` | the chip |
| `core/config.py` | `DONATIONS_URL`, `DONATIONS_APP_KEY` |

The cache (`donations_cache.json` beside `settings.json`) holds the last
summary and any entries that could not be sent, so the chip draws at once
with no network and a failed entry goes the next time the app can.
`settings.json` `donations` remembers that the prompt was shown and the
form's last currency and name.

## Guards

Self-reported, and the window says so. A single entry is capped at 10,000
in its currency, one address may add five an hour, and David can hide any
row with the admin key (README). Currency is converted to USD when the
entry is reported with a fixed table in the Worker; the stored figure never
moves after, and the list shows the original currency.

## Deploying

`tools/donations_worker/README.md`. Until the Worker is deployed and its
URL is in `config.py`, the chip shows no total and an entry is kept locally
with a toast saying so.

## Later

- A raised-over-time sparkline once there are a few months of entries.
- A Discord post when a milestone falls (the triage bot can poll the summary).
