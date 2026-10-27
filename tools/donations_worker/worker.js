// The animal shelter donations total (PAD-754): a Cloudflare Worker over a
// D1 table.  The app (pinball_decryptor/core/donations.py) reads the
// running total and recent list from GET /v1/summary and adds a donation a
// user reports with POST /v1/donate.  Nothing here takes money: the app
// tells people to give to an animal shelter near them, then say so here so
// it counts toward the total everyone sees.
//
// Routes
//   GET    /v1/summary              the total, count, milestones, recent list
//   POST   /v1/donate               add one (header X-PAD-Key = APP_KEY)
//   GET    /v1/admin/list           the last 200 rows with ids (X-PAD-Admin);
//                                   held = 1 marks one waiting for review
//   POST   /v1/admin/review/<id>    {"approve": true|false}: count a held
//                                   row, or hide it (X-PAD-Admin)
//   DELETE /v1/donate/<id>          hide a row: the app that added it, with
//                                   the token the POST answered (X-PAD-Edit),
//                                   or David (X-PAD-Admin = ADMIN_KEY)
//
// Bindings (wrangler.toml / secrets): DB (D1), APP_KEY, ADMIN_KEY, IP_SALT.
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
const PLACES = 10;                 // the Top places board
const PER_HOUR = 5;                // donations one address may add per hour

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

async function donate(request, env) {
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
  return json(s, 201);
}

// the app taking back its own row: the id and the token the POST answered
async function removeOwn(request, env, id) {
  if (env.APP_KEY && request.headers.get("X-PAD-Key") !== env.APP_KEY) {
    return fail("Not from the app.", 403);
  }
  const token = request.headers.get("X-PAD-Edit") || "";
  if (!/^[0-9a-f]{32}$/.test(token)) return fail("Not allowed.", 403);
  const r = await env.DB.prepare(
    "UPDATE donations SET removed = 1 WHERE id = ? AND edit_token = ? AND removed = 0")
    .bind(id, token).run();
  const changed = r.meta ? r.meta.changes : 0;
  if (!changed) return fail("No such donation.", 404);
  const s = await summary(env);
  s.id = id;
  return json(s);
}

function isAdmin(request, env) {
  return env.ADMIN_KEY && request.headers.get("X-PAD-Admin") === env.ADMIN_KEY;
}

async function adminList(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, at, amount, currency, usd, shelter, country, region, name, " +
    "show_name, app_version, ip_hash, held, removed FROM donations " +
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "");
    try {
      if (request.method === "GET" && path === "/v1/summary") {
        return json(await summary(env), 200, { "cache-control": "public, max-age=60" });
      }
      if (request.method === "POST" && path === "/v1/donate") {
        return donate(request, env);
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
        if (request.headers.get("X-PAD-Edit")) return removeOwn(request, env, m[1]);
        return fail("Not allowed.", 403);
      }
      return fail("Not found.", 404);
    } catch (e) {
      return fail("Something went wrong: " + (e && e.message ? e.message : e), 500);
    }
  },
};

export { MILESTONES, RATES, HOLD_OVER_USD, validate };
