// The animal shelter donations total (PAD-754): a Cloudflare Worker over a
// D1 table.  The app (pinball_decryptor/core/donations.py) reads the
// running total and recent list from GET /v1/summary and adds a donation a
// user reports with POST /v1/donate.  Nothing here takes money: the app
// tells people to give to an animal shelter near them, then say so here so
// it counts toward the total everyone sees.
//
// Routes
//   GET    /v1/summary              the total, count, milestones, recent list
//   GET    /v1/all?offset=0         every donation, newest first, 100 a page
//   POST   /v1/donate               add one (header X-PAD-Key = APP_KEY)
//   POST   /v1/report               a problem report from the app (X-PAD-Key)
//   GET    /v1/report/status?ids=   how the app's own reports are doing
//   POST   /v1/report/<id>/reply    the user's answer to a question (PAD-972)
//   GET    /v1/admin/reports        reports not yet taken; .../<id>/taken,
//                                   /answer, /stage, /reply-taken (X-PAD-Admin)
//   GET    /v1/admin/replies        answers waiting for the tracker (X-PAD-Admin)
//   GET    /v1/admin/list           the last 200 rows with ids (X-PAD-Admin);
//                                   held = 1 marks one waiting for review
//   POST   /v1/admin/review/<id>    {"approve": true|false}: count a held
//                                   row, or hide it (X-PAD-Admin)
//   DELETE /v1/donate/<id>          hide a row: the app that added it, with
//                                   the token the POST answered (X-PAD-Edit),
//                                   or David (X-PAD-Admin = ADMIN_KEY)
//
// Bindings (wrangler.toml / secrets): DB (D1), APP_KEY, ADMIN_KEY, IP_SALT,
// and DISCORD_WEBHOOK (optional, the #donations channel): every entry, hold
// and take-back is posted there so David hears about it as it happens.
// Problem reports are not: pad-triage posts those in #bug-reports.
// APP_KEY ships inside the public app, so it only keeps casual scripts
// out; the per-address rate limit and the single-entry cap do the real
// work.  ADMIN_KEY and IP_SALT are real secrets (`wrangler secret put`).

// The ladder the app's thermometer climbs (core/donations.py MILESTONES
// is the same list; change both).
const MILESTONES = [100, 200, 500, 1000, 2500, 5000, 10000, 25000, 50000,
                    100000, 250000, 500000, 1000000];

// USD per unit, fixed: a donation is converted when it is reported, and
// the stored usd never changes after.  Update now and then with
// `wrangler deploy`.
const RATES = {
  USD: 1, EUR: 1.08, GBP: 1.27, CAD: 0.73, AUD: 0.65, NZD: 0.60, CHF: 1.13,
  SEK: 0.095, NOK: 0.092, DKK: 0.145, JPY: 0.0067, PLN: 0.25, CZK: 0.043,
  BRL: 0.18, MXN: 0.052,
};

const MAX_AMOUNT = 10000;          // in the donation's own currency
// an entry worth more than this (USD) is HELD: it does not count until
// David approves it (POST /v1/admin/review/<id>), so a joker typing 9,999
// never moves the thermometer
const HOLD_OVER_USD = 299;
const MAX_SHELTER = 80;
const MAX_NAME = 40;
const MAX_REGION = 40;
const RECENT = 12;
const PLACES = 500;                // every place, for the board and the map
const PAGE = 100;                  // /v1/all rows per page
const PER_HOUR = 5;                // donations one address may add per hour
// Problem reports (PAD-780): what the app's Report a problem window sends.
// A row is the whole record plus a picture until David's tracker takes it
// (POST .../taken blanks everything the user wrote), then only its STATE:
// filed, and later released (with the version and David's message) or
// closed.  The app that sent it asks after its own ids (GET
// /v1/report/status) and tells the user in the app, so no address is ever
// asked for or stored.  An answered row is dropped after REPORT_KEEP_DAYS.
// PAD-914: between filed and the answer the tracker also pushes the row's
// STAGE on the app's board (POST .../stage: queued, working or ready, the
// ticket's number and how far through the work it is), and every ask from
// the app stamps `seen_at`, which the push answers with, so the tracker
// knows when the user's app last looked.  `install` (an anonymous id the
// app made) goes to the tracker with the report and is blanked on taken.
const REPORTS_PER_HOUR = 5;
const REPORT_MAX_BODY = 400000;    // the record (log tail included)
const REPORT_MAX_PICTURE = 1000000; // base64 of a shrunk JPEG
const REPORT_KEEP_DAYS = 90;
const REPORT_STATES = ["released", "closed"];
const REPORT_STAGES = ["queued", "working", "ready", "done", "question"];
// PAD-972: a question for the reporter.  The tracker pushes the stage
// "question" with its words; the app shows it on the board and posts the
// user's answer (words and files) to /v1/report/<id>/reply, which the
// tracker collects from /v1/admin/replies and clears with /reply-taken.
// One answer per question: a new question opens the way again.
const QUESTION_MAX = 4000;
const REPLY_MAX = 20000;
const REPLY_FILES = 5;
const REPLY_MAX_B64 = 1500000;     // every file's base64 together (D1: 2 MB a row)
const REPLY_NAME = 120;

const json = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extra },
  });
const fail = (error, status) => json({ ok: false, error }, status);

function clean(text, max) {
  return String(text == null ? "" : text).replace(/\s+/g, " ").trim().slice(0, max);
}

async function ipHash(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const data = new TextEncoder().encode((env.IP_SALT || "") + ip);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].slice(0, 8)
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

// The milestones the total has passed, with the moment each fell: a walk
// over every live row in time order.  Fine for the size this will ever be.
async function milestones(env) {
  const { results } = await env.DB.prepare(
    "SELECT at, usd FROM donations WHERE removed = 0 AND held = 0 ORDER BY at, id").all();
  const out = [];
  let sum = 0;
  let i = 0;
  for (const row of results) {
    sum += row.usd;
    while (i < MILESTONES.length && sum >= MILESTONES[i]) {
      out.push({ usd: MILESTONES[i], at: row.at });
      i += 1;
    }
  }
  return out;
}

async function summary(env) {
  const tot = await env.DB.prepare(
    "SELECT COALESCE(SUM(usd), 0) AS total, COUNT(*) AS n FROM donations WHERE removed = 0 AND held = 0")
    .first();
  const { results } = await env.DB.prepare(
    "SELECT at, amount, currency, shelter, country, region, name, show_name " +
    "FROM donations WHERE removed = 0 AND held = 0 ORDER BY at DESC, id DESC LIMIT ?")
    .bind(RECENT).all();
  const recent = results.map((r) => ({
    at: r.at, amount: r.amount, currency: r.currency, shelter: r.shelter,
    country: r.country, region: r.region, name: r.show_name ? r.name : "",
  }));
  // the Top places board: a country with a state or province is a place of
  // its own ("Texas, US"); a country alone is one too
  const places = (await env.DB.prepare(
    "SELECT country, region, SUM(usd) AS usd, COUNT(*) AS n FROM donations " +
    "WHERE removed = 0 AND held = 0 AND country != '' GROUP BY country, region " +
    "ORDER BY usd DESC LIMIT ?").bind(PLACES).all()).results
    .map((r) => ({ country: r.country, region: r.region,
                   usd: Math.round(r.usd * 100) / 100, count: r.n }));
  return {
    ok: true,
    total_usd: Math.round(tot.total * 100) / 100,
    count: tot.n,
    milestones: await milestones(env),
    recent,
    places,
    rates: RATES,
    updated: Math.floor(Date.now() / 1000),
  };
}

function validate(body) {
  const amount = Number(body.amount);
  if (!isFinite(amount) || amount <= 0) return [null, "Enter the amount you gave."];
  if (amount > MAX_AMOUNT) return [null, "That is more than one entry can hold."];
  const currency = String(body.currency || "USD").toUpperCase();
  if (!(currency in RATES)) return [null, "Unknown currency."];
  return [{
    amount: Math.round(amount * 100) / 100,
    currency,
    usd: Math.round(amount * RATES[currency] * 100) / 100,
    shelter: clean(body.shelter, MAX_SHELTER),
    country: clean(body.country, 2).toUpperCase().replace(/[^A-Z]/g, ""),
    region: clean(body.region, MAX_REGION),
    name: clean(body.name, MAX_NAME),
    show_name: body.show_name ? 1 : 0,
    app_version: clean(body.app_version, 24),
  }, null];
}

// every live donation, newest first, a page at a time (the window's
// All donations list)
async function all(env, url) {
  const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
  const limit = Math.min(PAGE * 2, Math.max(1, parseInt(url.searchParams.get("limit") || String(PAGE), 10) || PAGE));
  const tot = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM donations WHERE removed = 0 AND held = 0").first();
  const { results } = await env.DB.prepare(
    "SELECT at, amount, currency, shelter, country, region, name, show_name " +
    "FROM donations WHERE removed = 0 AND held = 0 ORDER BY at DESC, id DESC LIMIT ? OFFSET ?")
    .bind(limit, offset).all();
  const rows = results.map((r) => ({
    at: r.at, amount: r.amount, currency: r.currency, shelter: r.shelter,
    country: r.country, region: r.region, name: r.show_name ? r.name : "",
  }));
  return { ok: true, rows, total: tot.n, offset, limit };
}

// Tell David on Discord (a webhook URL in DISCORD_WEBHOOK).  Runs after
// the answer has gone out (ctx.waitUntil), never delays or fails a request,
// and does nothing without the secret.  A name the user chose not to show
// is not posted: it leaves the database only through the admin list.
function money(amount, currency) {
  const sym = { USD: "$", EUR: "€", GBP: "£", JPY: "¥", CAD: "CA$", AUD: "A$", NZD: "NZ$", BRL: "R$", MXN: "MX$" };
  const n = Number(amount);
  return (sym[currency] || currency + " ") + (Number.isInteger(n) ? n.toLocaleString("en-US") : n.toFixed(2));
}
function place(country, region) {
  if (!country) return "";
  return region ? region + ", " + country : country;
}
function notify(env, ctx, text) {
  if (!env.DISCORD_WEBHOOK) return;
  const p = fetch(env.DISCORD_WEBHOOK, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content: text.slice(0, 1900), allowed_mentions: { parse: [] } }),
  }).catch(() => null);
  if (ctx && ctx.waitUntil) ctx.waitUntil(p);
}
function describe(e) {
  const bits = [money(e.amount, e.currency)];
  if (e.shelter) bits.push("to " + e.shelter);
  const where = place(e.country, e.region);
  if (where) bits.push("in " + where);
  bits.push(e.show_name && e.name ? "as " + e.name : "anonymous");
  if (e.app_version) bits.push("· app " + e.app_version);
  return bits.join(" ");
}
function tallyLine(s) {
  return "\ntally now $" + s.total_usd.toLocaleString("en-US") + " from " + s.count + " donations";
}

async function donate(request, env, ctx) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const [entry, error] = validate(body || {});
  if (error) return fail(error, 400);
  const who = await ipHash(request, env);
  const now = Math.floor(Date.now() / 1000);
  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM donations WHERE ip_hash = ? AND at > ?")
    .bind(who, now - 3600).first();
  if (recent.n >= PER_HOUR) return fail("Too many in one hour. Try again later.", 429);
  // the hash exists for that count alone, which never looks back further
  // than an hour: older rows lose theirs now, so nothing in the database
  // can be matched to an address once the hour is up
  await env.DB.prepare(
    "UPDATE donations SET ip_hash = '' WHERE ip_hash != '' AND at <= ?")
    .bind(now - 3600).run();
  const id = crypto.randomUUID();
  const held = entry.usd > HOLD_OVER_USD ? 1 : 0;
  // the token lets the app that added the row take it back (a typo, the
  // wrong amount); it is answered once, here, and the app keeps it
  const token = crypto.randomUUID().replace(/-/g, "");
  await env.DB.prepare(
    "INSERT INTO donations (id, at, amount, currency, usd, shelter, country, " +
    "region, name, show_name, app_version, ip_hash, edit_token, held, removed) " +
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)")
    .bind(id, now, entry.amount, entry.currency, entry.usd, entry.shelter,
          entry.country, entry.region, entry.name, entry.show_name,
          entry.app_version, who, token, held).run();
  const s = await summary(env);
  s.id = id;
  s.token = token;
  s.held = !!held;
  notify(env, ctx, held
    ? "⏸ HELD for your review: " + describe(entry) + "\napprove: curl -X POST -H \"X-PAD-Admin: $ADMIN_KEY\" "
      + "-H 'content-type: application/json' -d '{\"approve\": true}' " + new URL(request.url).origin + "/v1/admin/review/" + id
    : "🐾 New donation: " + describe(entry) + tallyLine(s));
  return json(s, 201);
}

// the app taking back its own row: the id and the token the POST answered
async function removeOwn(request, env, ctx, id) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  const token = request.headers.get("X-PAD-Edit") || "";
  if (!/^[0-9a-f]{32}$/.test(token)) return fail("Not allowed.", 403);
  const row = await env.DB.prepare(
    "SELECT amount, currency, shelter, country, region, name, show_name, app_version, held " +
    "FROM donations WHERE id = ? AND edit_token = ? AND removed = 0").bind(id, token).first();
  if (!row) return fail("No such donation.", 404);
  await env.DB.prepare(
    "UPDATE donations SET removed = 1 WHERE id = ? AND edit_token = ? AND removed = 0")
    .bind(id, token).run();
  const s = await summary(env);
  s.id = id;
  notify(env, ctx, "↩ Taken back by the app that added it: " + describe(row)
    + (row.held ? " (was held)" : "") + tallyLine(s));
  return json(s);
}

function isAdmin(request, env) {
  return env.ADMIN_KEY && request.headers.get("X-PAD-Admin") === env.ADMIN_KEY;
}

async function adminList(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, at, amount, currency, usd, shelter, country, region, name, " +
    "show_name, app_version, held, removed FROM donations " +
    "ORDER BY at DESC LIMIT 200").all();
  return json({ ok: true, rows: results, hold_over_usd: HOLD_OVER_USD });
}

// David's verdict on a held row: approve (it counts from now) or hide it
async function review(request, env, id) {
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const approve = !!(body && body.approve);
  const r = await env.DB.prepare(approve
    ? "UPDATE donations SET held = 0 WHERE id = ? AND held = 1 AND removed = 0"
    : "UPDATE donations SET removed = 1 WHERE id = ? AND removed = 0").bind(id).run();
  const changed = r.meta ? r.meta.changes : 0;
  if (!changed) return fail("No such held donation.", 404);
  return json({ ok: true, id, approved: approve });
}

async function remove(env, id) {
  const r = await env.DB.prepare(
    "UPDATE donations SET removed = 1 WHERE id = ? AND removed = 0").bind(id).run();
  const changed = r.meta ? r.meta.changes : 0;
  if (!changed) return fail("No such donation.", 404);
  return json({ ok: true, id });
}

// ---- problem reports (PAD-780) --------------------------------------------
function validateReport(body) {
  const title = clean(body.title, 120);
  const record = typeof body.body === "string" ? body.body : "";
  if (!record.trim()) return [null, "The report is empty."];
  if (record.length > REPORT_MAX_BODY) return [null, "The report is too long."];
  const picture = typeof body.picture_b64 === "string" ? body.picture_b64 : "";
  if (picture.length > REPORT_MAX_PICTURE) return [null, "The picture is too big."];
  if (picture && !/^[A-Za-z0-9+/=\r\n]+$/.test(picture)) return [null, "The picture is not base64."];
  return [{
    title: title || record.split("\n")[0].slice(0, 120),
    body: record,
    name: clean(body.name, 80),
    app_version: clean(body.app_version, 40),
    platform: clean(body.platform, 40),
    install: /^[0-9a-f]{16}$/.test(body.install || "") ? body.install : "",
    picture_type: picture ? clean(body.picture_type, 40) || "image/jpeg" : "",
    picture,
  }, null];
}

async function report(request, env, ctx) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const [rep, error] = validateReport(body || {});
  if (error) return fail(error, 400);
  const who = await ipHash(request, env);
  const now = Math.floor(Date.now() / 1000);
  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM reports WHERE ip_hash = ? AND at > ?")
    .bind(who, now - 3600).first();
  if (recent.n >= REPORTS_PER_HOUR) return fail("Too many reports in one hour. Try again later.", 429);
  await env.DB.prepare(
    "UPDATE reports SET ip_hash = '' WHERE ip_hash != '' AND at <= ?")
    .bind(now - 3600).run();
  const id = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO reports (id, at, app_version, platform, title, body, name, " +
    "picture_type, picture, ip_hash, install, state) VALUES (?,?,?,?,?,?,?,?,?,?,?,'received')")
    .bind(id, now, rep.app_version, rep.platform, rep.title, rep.body, rep.name,
          rep.picture_type, rep.picture, who, rep.install).run();
  // no Discord line (PAD-836): the webhook is #donations, and pad-triage
  // posts each report in #bug-reports itself once it takes it
  return json({ ok: true, id }, 201);
}

// David's tracker (pad-triage) polls this with the admin key, files each
// row as a ticket, then takes it
async function adminReports(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, at, app_version, platform, title, body, name, " +
    "picture_type, picture, install FROM reports WHERE state = 'received' ORDER BY at LIMIT 20").all();
  return json({ ok: true, rows: results });
}

// taken: everything the user wrote goes; the id stays so the app can ask
// how its report is doing
async function reportTaken(env, id) {
  const r = await env.DB.prepare(
    "UPDATE reports SET state = 'filed', title = '', body = '', name = '', " +
    "picture_type = '', picture = '', ip_hash = '', install = '', stage = 'queued' " +
    "WHERE id = ? AND state = 'received'")
    .bind(id).run();
  if (!r.meta.changes) return fail("No such report.", 404);
  return json({ ok: true, id });
}

// the tracker's answer once the report's ticket shipped or closed: the
// state, the release version and the message David wrote for the reporter
async function reportAnswer(request, env, id) {
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const state = clean(body.state, 20);
  if (!REPORT_STATES.includes(state)) return fail("state must be released or closed.", 400);
  const now = Math.floor(Date.now() / 1000);
  const r = await env.DB.prepare(
    "UPDATE reports SET state = ?, version = ?, message = ?, answered_at = ? WHERE id = ?")
    .bind(state, clean(body.version, 40), clean(body.message, 2000), now, id).run();
  if (!r.meta.changes) return fail("No such report.", 404);
  return json({ ok: true, id, state });
}

// the tracker moving a report along the app's board (PAD-914): its stage,
// its ticket's number and how far through the work it is (-1: not said).
// The answer carries when the app last asked, so the tracker can say
// whether the user has seen this stage yet.
async function reportStage(request, env, id) {
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const stage = clean(body.stage, 20);
  if (!REPORT_STAGES.includes(stage)) return fail("stage must be one of " + REPORT_STAGES.join(", ") + ".", 400);
  const p = Number.isInteger(body.progress) && body.progress >= 0 && body.progress <= 100 ? body.progress : -1;
  const now = Math.floor(Date.now() / 1000);
  // a question also carries its words and clears any earlier answer;
  // every other stage leaves the question columns as they are
  const r = stage === "question"
    ? await env.DB.prepare(
      "UPDATE reports SET stage = ?, ticket = ?, progress = ?, stage_at = ?, question = ?, " +
      "question_at = ?, reply = '', reply_files = '[]', reply_pending = 0 WHERE id = ?")
      .bind(stage, clean(body.ticket, 20), p, now, cleanText(body.question, QUESTION_MAX), now, id).run()
    : await env.DB.prepare(
      "UPDATE reports SET stage = ?, ticket = ?, progress = ?, stage_at = ? WHERE id = ?")
      .bind(stage, clean(body.ticket, 20), p, now, id).run();
  if (!r.meta.changes) return fail("No such report.", 404);
  const row = await env.DB.prepare("SELECT seen_at FROM reports WHERE id = ?").bind(id).first();
  // `at` is this Worker's clock, which seen_at is on too: the tracker
  // compares the two, never its own clock with ours
  return json({ ok: true, id, stage, seen_at: (row && row.seen_at) || 0, at: now });
}

// the app asking after the reports it sent (ids it was answered, up to 20)
async function reportStatus(request, env, url) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  const ids = (url.searchParams.get("ids") || "").split(",")
    .map((x) => x.trim()).filter((x) => /^[0-9a-f-]{8,40}$/.test(x)).slice(0, 20);
  const now = Math.floor(Date.now() / 1000);
  // an answered row has done its job once the app has had months to ask
  await env.DB.prepare(
    "DELETE FROM reports WHERE answered_at > 0 AND answered_at < ?")
    .bind(now - REPORT_KEEP_DAYS * 86400).run();
  const rows = [];
  for (const id of ids) {
    const r = await env.DB.prepare(
      "SELECT id, state, version, message, answered_at, stage, ticket, progress, " +
      "question, question_at, reply_at FROM reports WHERE id = ?")
      .bind(id).first();
    rows.push(r || { id, state: "unknown", version: "", message: "", answered_at: 0,
                     stage: "", ticket: "", progress: -1, question: "", question_at: 0,
                     reply_at: 0 });
  }
  // when the app last looked, for the tracker's copy of the board
  if (ids.length) {
    await env.DB.prepare(
      "UPDATE reports SET seen_at = ? WHERE id IN (" + ids.map(() => "?").join(",") + ")")
      .bind(now, ...ids).run();
  }
  return json({ ok: true, rows });
}

// ---- questions and answers (PAD-972) ----------------------------------------
// A question or an answer keeps its lines; only the ends are trimmed.
function cleanText(text, max) {
  return String(text == null ? "" : text).replace(/\r\n?/g, "\n").trim().slice(0, max);
}

function validateReply(body) {
  const message = typeof body.message === "string" ? cleanText(body.message, REPLY_MAX + 1) : "";
  if (message.length > REPLY_MAX) return [null, "The answer is too long."];
  const list = Array.isArray(body.files) ? body.files : [];
  if (list.length > REPLY_FILES) return [null, "At most " + REPLY_FILES + " files go with an answer."];
  const files = [];
  let total = 0;
  for (const f of list) {
    const b64 = f && typeof f.b64 === "string" ? f.b64 : "";
    if (!b64 || !/^[A-Za-z0-9+/=\r\n]+$/.test(b64)) return [null, "A file is not base64."];
    total += b64.length;
    const name = String(f.name || "").replace(/[^A-Za-z0-9._ -]/g, "_").trim().slice(0, REPLY_NAME) || "file";
    files.push({ name, type: clean(f.type, 80) || "application/octet-stream", b64 });
  }
  if (total > REPLY_MAX_B64) return [null, "The files are too big to send together."];
  if (!message && !files.length) return [null, "Write an answer or attach a file."];
  return [{ message, files }, null];
}

// the user's answer, from the app that sent the report: the report's id is
// the secret (nothing else names it once /taken blanked the row)
async function reportReply(request, env, id) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return fail("Bad request.", 400);
  }
  const [rep, error] = validateReply(body || {});
  if (error) return fail(error, 400);
  const who = await ipHash(request, env);
  const now = Math.floor(Date.now() / 1000);
  // one allowance an hour for reports and answers together
  const reports = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM reports WHERE ip_hash = ? AND at > ?")
    .bind(who, now - 3600).first();
  const answers = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM reply_log WHERE ip_hash = ? AND at > ?")
    .bind(who, now - 3600).first();
  if (reports.n + answers.n >= REPORTS_PER_HOUR) return fail("Too many in one hour. Try again later.", 429);
  const r = await env.DB.prepare(
    "UPDATE reports SET reply = ?, reply_files = ?, reply_at = ?, reply_pending = 1, stage = 'working' " +
    "WHERE id = ? AND stage = 'question' AND reply_pending = 0 AND reply_at < question_at")
    .bind(rep.message, JSON.stringify(rep.files), now, id).run();
  if (!r.meta.changes) return fail("That question is no longer open.", 409);
  // the log is for that count alone, so nothing older than the hour stays
  await env.DB.prepare("DELETE FROM reply_log WHERE at <= ?").bind(now - 3600).run();
  await env.DB.prepare("INSERT INTO reply_log (ip_hash, at) VALUES (?, ?)").bind(who, now).run();
  return json({ ok: true, id });
}

// the tracker collecting the answers that came in, oldest first
async function adminReplies(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, ticket, question, question_at, reply_at, reply, reply_files FROM reports " +
    "WHERE reply_pending = 1 ORDER BY reply_at LIMIT 10").all();
  const rows = results.map((r) => {
    let files;
    try {
      files = JSON.parse(r.reply_files || "[]");
    } catch (e) {
      files = [];
    }
    return { id: r.id, ticket: r.ticket, question: r.question, question_at: r.question_at,
             reply_at: r.reply_at, message: r.reply, files: Array.isArray(files) ? files : [] };
  });
  return json({ ok: true, rows });
}

// ... and saying it has one: the words and files go, the moment stays
async function replyTaken(env, id) {
  const r = await env.DB.prepare(
    "UPDATE reports SET reply = '', reply_files = '[]', reply_pending = 0 WHERE id = ?")
    .bind(id).run();
  if (!r.meta.changes) return fail("No such report.", 404);
  return json({ ok: true, id });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");
    try {
      if (request.method === "GET" && path === "/v1/all") {
        return json(await all(env, url), 200, { "cache-control": "public, max-age=60" });
      }
      if (request.method === "GET" && path === "/v1/summary") {
        return json(await summary(env), 200, { "cache-control": "public, max-age=60" });
      }
      if (request.method === "POST" && path === "/v1/donate") {
        return donate(request, env, ctx);
      }
      if (request.method === "POST" && path === "/v1/report") {
        return report(request, env, ctx);
      }
      if (request.method === "GET" && path === "/v1/report/status") {
        return reportStatus(request, env, url);
      }
      const rp = path.match(/^\/v1\/report\/([0-9a-f-]{8,40})\/reply$/);
      if (request.method === "POST" && rp) {
        return reportReply(request, env, rp[1]);
      }
      if (request.method === "GET" && path === "/v1/admin/replies") {
        if (!isAdmin(request, env)) return fail("Not allowed.", 403);
        return adminReplies(env);
      }
      if (request.method === "GET" && path === "/v1/admin/reports") {
        if (!isAdmin(request, env)) return fail("Not allowed.", 403);
        return adminReports(env);
      }
      const tk = path.match(/^\/v1\/admin\/reports\/([0-9a-f-]{8,40})\/(taken|answer|stage|reply-taken)$/);
      if (request.method === "POST" && tk) {
        if (!isAdmin(request, env)) return fail("Not allowed.", 403);
        if (tk[2] === "stage") return reportStage(request, env, tk[1]);
        if (tk[2] === "reply-taken") return replyTaken(env, tk[1]);
        return tk[2] === "taken" ? reportTaken(env, tk[1]) : reportAnswer(request, env, tk[1]);
      }
      if (path === "/v1/admin/list") {
        if (!isAdmin(request, env)) return fail("Not allowed.", 403);
        return adminList(env);
      }
      const rv = path.match(/^\/v1\/admin\/review\/([0-9a-f-]{8,40})$/);
      if (request.method === "POST" && rv) {
        if (!isAdmin(request, env)) return fail("Not allowed.", 403);
        return review(request, env, rv[1]);
      }
      const m = path.match(/^\/v1\/donate\/([0-9a-f-]{8,40})$/);
      if (request.method === "DELETE" && m) {
        if (isAdmin(request, env)) return remove(env, m[1]);
        if (request.headers.get("X-PAD-Edit")) return removeOwn(request, env, ctx, m[1]);
        return fail("Not allowed.", 403);
      }
      return fail("Not found.", 404);
    } catch (e) {
      return fail("Something went wrong: " + (e && e.message ? e.message : e), 500);
    }
  },
};

// For the tests.  A module worker may export only handlers and functions
// (workerd refuses a constant: "not of type 'function or ExportedHandler'"),
// so the tables come out through a function.
export function meta() {
  return { MILESTONES, RATES, HOLD_OVER_USD };
}
export { validate, validateReport, validateReply };
