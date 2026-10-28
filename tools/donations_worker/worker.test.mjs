// node --test worker.test.mjs — the handler against a stand-in for D1 that
// answers the exact statements worker.js prepares.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { meta } from "./worker.js";
const { MILESTONES, RATES, HOLD_OVER_USD } = meta();

function fakeDb() {
  const rows = [];
  const reports = [];
  const live = () => rows.filter((r) => !r.removed && !r.held);
  const stmt = (sql) => {
    let args = [];
    const s = {
      bind(...a) { args = a; return s; },
      async all() {
        if (sql.startsWith("SELECT at, usd")) {
          return { results: live().sort((a, b) => a.at - b.at || (a.id < b.id ? -1 : 1))
            .map((r) => ({ at: r.at, usd: r.usd })) };
        }
        if (sql.startsWith("SELECT at, amount")) {
          const off = args[1] || 0;
          return { results: live().sort((a, b) => b.at - a.at).slice(off, off + args[0]) };
        }
        if (sql.startsWith("SELECT id, at, app_version")) {
          return { results: reports.filter((r) => r.state === "received").sort((a, b) => a.at - b.at).slice(0, 20)
            .map(({ ip_hash, state, version, message, answered_at, ...r }) => r) };
        }
        if (sql.startsWith("SELECT id, at")) {
          return { results: rows.slice().sort((a, b) => b.at - a.at).slice(0, 200) };
        }
        if (sql.startsWith("SELECT country, region, SUM(usd)")) {
          const by = new Map();
          for (const r of live()) {
            if (!r.country) continue;
            const k = r.country + "|" + r.region;
            const p = by.get(k) || { country: r.country, region: r.region, usd: 0, n: 0 };
            p.usd += r.usd; p.n += 1; by.set(k, p);
          }
          return { results: [...by.values()].sort((a, b) => b.usd - a.usd).slice(0, args[0]) };
        }
        throw new Error("unexpected all(): " + sql);
      },
      async first() {
        if (sql.startsWith("SELECT amount, currency, shelter")) {
          return rows.find((x) => x.id === args[0] && x.edit_token === args[1] && !x.removed) || null;
        }
        if (sql.startsWith("SELECT COUNT(*) AS n FROM donations WHERE removed")) {
          return { n: live().length };
        }
        if (sql.startsWith("SELECT COALESCE")) {
          return { total: live().reduce((n, r) => n + r.usd, 0), n: live().length };
        }
        if (sql.startsWith("SELECT COUNT(*) AS n FROM donations WHERE ip_hash")) {
          return { n: rows.filter((r) => r.ip_hash === args[0] && r.at > args[1]).length };
        }
        if (sql.startsWith("SELECT COUNT(*) AS n FROM reports WHERE ip_hash")) {
          return { n: reports.filter((r) => r.ip_hash === args[0] && r.at > args[1]).length };
        }
        if (sql.startsWith("SELECT id, state, version, message, answered_at FROM reports")) {
          const r = reports.find((x) => x.id === args[0]);
          return r ? { id: r.id, state: r.state, version: r.version, message: r.message, answered_at: r.answered_at } : null;
        }
        throw new Error("unexpected first(): " + sql);
      },
      async run() {
        if (sql.startsWith("INSERT INTO reports")) {
          const [id, at, app_version, platform, title, body, name, picture_type, picture, ip_hash] = args;
          reports.push({ id, at, app_version, platform, title, body, name, picture_type, picture, ip_hash,
            state: "received", version: "", message: "", answered_at: 0 });
          return { meta: { changes: 1 } };
        }
        if (sql.startsWith("UPDATE reports SET state = 'filed'")) {
          const r = reports.find((x) => x.id === args[0] && x.state === "received");
          if (r) Object.assign(r, { state: "filed", title: "", body: "", name: "", picture_type: "", picture: "", ip_hash: "" });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET state = ?")) {
          const r = reports.find((x) => x.id === args[4]);
          if (r) Object.assign(r, { state: args[0], version: args[1], message: args[2], answered_at: args[3] });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("DELETE FROM reports WHERE answered_at")) {
          let n = 0;
          for (let i = reports.length - 1; i >= 0; i--) {
            if (reports[i].answered_at > 0 && reports[i].answered_at < args[0]) { reports.splice(i, 1); n++; }
          }
          return { meta: { changes: n } };
        }
        if (sql.startsWith("UPDATE reports SET ip_hash = ''")) {
          let n = 0;
          for (const r of reports) if (r.ip_hash && r.at <= args[0]) { r.ip_hash = ""; n++; }
          return { meta: { changes: n } };
        }
        if (sql.startsWith("INSERT")) {
          const [id, at, amount, currency, usd, shelter, country, region, name, show_name, app_version, ip_hash, edit_token, held] = args;
          rows.push({ id, at, amount, currency, usd, shelter, country, region, name, show_name, app_version, ip_hash, edit_token, held, removed: 0 });
          return { meta: { changes: 1 } };
        }
        if (sql.startsWith("UPDATE donations SET ip_hash = ''")) {
          let n = 0;
          for (const r of rows) if (r.ip_hash && r.at <= args[0]) { r.ip_hash = ""; n++; }
          return { meta: { changes: n } };
        }
        if (sql.startsWith("UPDATE donations SET held = 0")) {
          const r = rows.find((x) => x.id === args[0] && x.held && !x.removed);
          if (r) r.held = 0;
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE donations SET removed = 1 WHERE id = ? AND edit_token")) {
          const r = rows.find((x) => x.id === args[0] && x.edit_token === args[1] && !x.removed);
          if (r) r.removed = 1;
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE donations SET removed")) {
          const r = rows.find((x) => x.id === args[0] && !x.removed);
          if (r) r.removed = 1;
          return { meta: { changes: r ? 1 : 0 } };
        }
        throw new Error("unexpected run(): " + sql);
      },
    };
    return s;
  };
  return { prepare: stmt, rows, reports };
}

const env = () => ({ DB: fakeDb(), APP_KEY: "k", ADMIN_KEY: "adm", IP_SALT: "s" });
const BASE = "https://pad-donations.example.workers.dev";

async function post(e, body, headers = { "X-PAD-Key": "k", "CF-Connecting-IP": "1.2.3.4" }) {
  const r = await worker.fetch(new Request(BASE + "/v1/donate", {
    method: "POST", headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body) }), e);
  return [r.status, await r.json()];
}
async function get(e, path, headers = {}) {
  const r = await worker.fetch(new Request(BASE + path, { headers }), e);
  return [r.status, await r.json()];
}

test("an empty table sums to nothing", async () => {
  const [st, s] = await get(env(), "/v1/summary");
  assert.equal(st, 200);
  assert.deepEqual([s.ok, s.total_usd, s.count, s.milestones, s.recent], [true, 0, 0, [], []]);
  assert.equal(s.rates.USD, 1);
});

test("a donation needs the app key and a sane amount", async () => {
  const e = env();
  assert.equal((await post(e, { amount: 5 }, {}))[0], 403);
  assert.equal((await post(e, { amount: 0 }))[0], 400);
  assert.equal((await post(e, { amount: "lots" }))[0], 400);
  assert.equal((await post(e, { amount: 10001 }))[0], 400);
  assert.equal((await post(e, { amount: 5, currency: "XXX" }))[0], 400);
  assert.equal(e.DB.rows.length, 0);
});

test("a donation is converted when reported and the summary comes back", async () => {
  const e = env();
  const [st, s] = await post(e, { amount: 40, currency: "gbp", shelter: "  Dogs   Trust ", name: "pinhead77", show_name: true, app_version: "1.265.0" });
  assert.equal(st, 201);
  assert.ok(s.id);
  assert.equal(s.total_usd, Math.round(40 * RATES.GBP * 100) / 100);
  assert.equal(s.count, 1);
  assert.deepEqual(s.recent[0].shelter, "Dogs Trust");
  assert.equal(s.recent[0].name, "pinhead77");
  assert.equal(s.recent[0].currency, "GBP");
  assert.equal(e.DB.rows[0].ip_hash.length, 16);
});

test("a hidden name stays hidden in the list", async () => {
  const e = env();
  const [, s] = await post(e, { amount: 20, name: "Mike", show_name: false });
  assert.equal(s.recent[0].name, "");
  const [, a] = await get(e, "/v1/admin/list", { "X-PAD-Admin": "adm" });
  assert.equal(a.rows[0].name, "Mike");       // David still sees it
});

test("one address gets five an hour", async () => {
  const e = env();
  for (let i = 0; i < 5; i++) assert.equal((await post(e, { amount: 1 }))[0], 201);
  assert.equal((await post(e, { amount: 1 }))[0], 429);
  const other = { "X-PAD-Key": "k", "CF-Connecting-IP": "9.9.9.9" };
  assert.equal((await post(e, { amount: 1 }, other))[0], 201);
});

test("milestones fall in order with the moment they fell", async () => {
  const e = env();
  const ip = (n) => ({ "X-PAD-Key": "k", "CF-Connecting-IP": "10.0.0." + n });
  for (let i = 0; i < 12; i++) await post(e, { amount: 100 }, ip(i));
  e.DB.rows.forEach((r, i) => { r.at = 1000 + i; });
  const [, s] = await get(e, "/v1/summary");
  assert.equal(s.total_usd, 1200);
  assert.deepEqual(s.milestones, [{ usd: 100, at: 1000 }, { usd: 200, at: 1001 }, { usd: 500, at: 1004 }, { usd: 1000, at: 1009 }]);
});

test("places add up by country and state; no place, no row on the board", async () => {
  const e = env();
  const ip = (n) => ({ "X-PAD-Key": "k", "CF-Connecting-IP": "10.0.1." + n });
  await post(e, { amount: 50, country: "us", region: "Texas" }, ip(1));
  await post(e, { amount: 25, country: "US", region: "Texas" }, ip(2));
  await post(e, { amount: 40, currency: "GBP", country: "GB", region: "" }, ip(3));
  await post(e, { amount: 50, country: "", region: "Nowhere" }, ip(4));
  e.DB.rows.forEach((r, i) => { r.at = 1000 + i; });   // one a second, in order
  const [, s] = await get(e, "/v1/summary");
  assert.deepEqual(s.places.map((p) => [p.country, p.region, p.usd, p.count]),
    [["US", "Texas", 75, 2], ["GB", "", Math.round(40 * RATES.GBP * 100) / 100, 1]]);
  assert.equal(s.recent[0].region, "Nowhere");
  assert.equal(s.recent[0].country, "");
});

test("an admin hides a row; anyone else cannot", async () => {
  const e = env();
  const [, s] = await post(e, { amount: 50 });
  const r1 = await worker.fetch(new Request(BASE + "/v1/donate/" + s.id, { method: "DELETE" }), e);
  assert.equal(r1.status, 403);
  const r2 = await worker.fetch(new Request(BASE + "/v1/donate/" + s.id, { method: "DELETE", headers: { "X-PAD-Admin": "adm" } }), e);
  assert.equal(r2.status, 200);
  const [, after] = await get(e, "/v1/summary");
  assert.deepEqual([after.total_usd, after.count], [0, 0]);
  const r3 = await worker.fetch(new Request(BASE + "/v1/donate/" + s.id, { method: "DELETE", headers: { "X-PAD-Admin": "adm" } }), e);
  assert.equal(r3.status, 404);
});

test("the app that added a row can take it back with its token", async () => {
  const e = env();
  const [, s] = await post(e, { amount: 300, shelter: "typo" });
  assert.match(s.token, /^[0-9a-f]{32}$/);
  const del = (headers) => worker.fetch(new Request(BASE + "/v1/donate/" + s.id, { method: "DELETE", headers }), e);
  assert.equal((await del({ "X-PAD-Key": "k", "X-PAD-Edit": "0".repeat(32) })).status, 404);
  assert.equal((await del({ "X-PAD-Edit": s.token })).status, 403);            // no app key
  assert.equal((await del({ "X-PAD-Key": "k", "X-PAD-Edit": "nope" })).status, 403);
  const ok = await del({ "X-PAD-Key": "k", "X-PAD-Edit": s.token });
  assert.equal(ok.status, 200);
  const body = await ok.json();
  assert.deepEqual([body.ok, body.id, body.total_usd, body.count], [true, s.id, 0, 0]);
  assert.equal((await del({ "X-PAD-Key": "k", "X-PAD-Edit": s.token })).status, 404);
  const [, a] = await get(e, "/v1/admin/list", { "X-PAD-Admin": "adm" });
  assert.equal(a.rows[0].removed, 1);                                          // kept, hidden
});

test("a big entry is held until David says so", async () => {
  const e = env();
  const [st, s] = await post(e, { amount: HOLD_OVER_USD + 1, shelter: "big" });
  assert.equal(st, 201);
  assert.equal(s.held, true);
  assert.deepEqual([s.total_usd, s.count, s.recent], [0, 0, []]);      // not counted yet
  const [, small] = await post(e, { amount: HOLD_OVER_USD }, { "X-PAD-Key": "k", "CF-Connecting-IP": "2.2.2.2" });
  assert.equal(small.held, false);
  assert.equal(small.count, 1);
  const [, a] = await get(e, "/v1/admin/list", { "X-PAD-Admin": "adm" });
  assert.equal(a.hold_over_usd, HOLD_OVER_USD);
  assert.equal(a.rows.find((r) => r.id === s.id).held, 1);
  const rev = (id, approve, headers = { "X-PAD-Admin": "adm" }) => worker.fetch(new Request(BASE + "/v1/admin/review/" + id, {
    method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify({ approve }) }), e);
  assert.equal((await rev(s.id, true, {})).status, 403);
  assert.equal((await rev(s.id, true)).status, 200);
  const [, after] = await get(e, "/v1/summary");
  assert.deepEqual([after.total_usd, after.count], [HOLD_OVER_USD * 2 + 1, 2]);
  assert.equal((await rev(s.id, true)).status, 404);                   // no longer held
  const [, big2] = await post(e, { amount: 5000 }, { "X-PAD-Key": "k", "CF-Connecting-IP": "3.3.3.3" });
  assert.equal((await rev(big2.id, false)).status, 200);                // hidden
  const [, last] = await get(e, "/v1/summary");
  assert.equal(last.count, 2);
});

test("every donation can be read a page at a time, newest first", async () => {
  const e = env();
  const ip = (n) => ({ "X-PAD-Key": "k", "CF-Connecting-IP": "10.0.2." + n });
  for (let i = 0; i < 7; i++) await post(e, { amount: 10 + i, name: "n" + i, show_name: i % 2 === 0 }, ip(i));
  e.DB.rows.forEach((r, i) => { r.at = 2000 + i; });
  const [st, p1] = await get(e, "/v1/all?limit=3");
  assert.equal(st, 200);
  assert.deepEqual([p1.total, p1.offset, p1.rows.length], [7, 0, 3]);
  assert.deepEqual(p1.rows.map((r) => r.amount), [16, 15, 14]);
  assert.deepEqual(p1.rows.map((r) => r.name), ["n6", "", "n4"]);
  const [, p3] = await get(e, "/v1/all?limit=3&offset=6");
  assert.deepEqual(p3.rows.map((r) => r.amount), [10]);
  const [, bad] = await get(e, "/v1/all?limit=junk&offset=-4");
  assert.deepEqual([bad.offset, bad.limit], [0, 100]);
});

test("David hears on Discord about an entry, a hold and a take-back", async () => {
  const e = { ...env(), DISCORD_WEBHOOK: "https://discord.example/api/webhooks/1/x" };
  const posts = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => { posts.push([url, JSON.parse(init.body)]); return new Response("ok"); };
  const waited = [];
  const ctx = { waitUntil: (p) => waited.push(p) };
  const hdr = (ip) => ({ "content-type": "application/json", "X-PAD-Key": "k", "CF-Connecting-IP": ip });
  try {
    const r1 = await worker.fetch(new Request(BASE + "/v1/donate", { method: "POST", headers: hdr("5.5.5.5"),
      body: JSON.stringify({ amount: 30, shelter: "Lollypop Farm", country: "US", region: "New York", name: "David", show_name: true, app_version: "1.266.0" }) }), e, ctx);
    const s1 = await r1.json();
    await Promise.all(waited);
    assert.equal(posts.length, 1);
    assert.equal(posts[0][0], e.DISCORD_WEBHOOK);
    assert.equal(posts[0][1].content, "🐾 New donation: $30 to Lollypop Farm in New York, US as David · app 1.266.0\ntally now $30 from 1 donations");
    assert.deepEqual(posts[0][1].allowed_mentions, { parse: [] });
    const r2 = await worker.fetch(new Request(BASE + "/v1/donate", { method: "POST", headers: hdr("6.6.6.6"),
      body: JSON.stringify({ amount: 5000, name: "Shy", show_name: false }) }), e, ctx);
    const s2 = await r2.json();
    await Promise.all(waited);
    assert.ok(posts[1][1].content.startsWith("⏸ HELD for your review: $5,000 anonymous\napprove: curl "),
      posts[1][1].content);                                // the hidden name stays off Discord
    assert.ok(posts[1][1].content.endsWith("/v1/admin/review/" + s2.id));
    await worker.fetch(new Request(BASE + "/v1/donate/" + s1.id, { method: "DELETE", headers: { "X-PAD-Key": "k", "X-PAD-Edit": s1.token } }), e, ctx);
    await Promise.all(waited);
    assert.equal(posts[2][1].content, "↩ Taken back by the app that added it: $30 to Lollypop Farm in New York, US as David · app 1.266.0\ntally now $0 from 0 donations");
    const quiet = env();                                   // no webhook: nothing posted
    const before = posts.length;
    await worker.fetch(new Request(BASE + "/v1/donate", { method: "POST", headers: hdr("7.7.7.7"), body: JSON.stringify({ amount: 2 }) }), quiet, ctx);
    assert.equal(posts.length, before);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("an address hash is blanked once its row is an hour old", async () => {
  const e = env();
  const post = (ip, amount) => worker.fetch(new Request(BASE + "/v1/donate", { method: "POST",
    headers: { "content-type": "application/json", "X-PAD-Key": "k", "CF-Connecting-IP": ip },
    body: JSON.stringify({ amount }) }), e, {});
  assert.equal((await post("8.8.8.8", 1)).status, 201);
  assert.equal(e.DB.rows[0].ip_hash.length, 16);
  e.DB.rows[0].at -= 3601;                               // an hour and a second ago
  assert.equal((await post("9.9.9.9", 2)).status, 201);
  assert.equal(e.DB.rows[0].ip_hash, "", "the old row's hash is gone");
  assert.equal(e.DB.rows[1].ip_hash.length, 16, "the fresh row keeps its hash for the limit");
  assert.equal((await get(e, "/v1/admin/list", { "X-PAD-Admin": "adm" }))[0], 200);
});

// ---- problem reports (PAD-780) -------------------------------------------
async function postReport(e, body, headers = { "X-PAD-Key": "k", "CF-Connecting-IP": "9.9.9.9" }, ctx) {
  const r = await worker.fetch(new Request(BASE + "/v1/report", {
    method: "POST", headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body) }), e, ctx);
  return [r.status, await r.json()];
}
const RECORD = "Pinball Asset Decryptor problem report\n=====\nApp: v1.274.0\n\nWhat happened\n-------------\nWrite stopped at 40%\n\nLog (last 2 lines)\n---\n[12:00] one\n[12:01] two\n";

test("a report needs the app key and some words", async () => {
  const e = env();
  assert.equal((await postReport(e, { body: RECORD }, {}))[0], 403);
  assert.equal((await postReport(e, { body: "   " }))[0], 400);
  assert.equal((await postReport(e, { body: "x".repeat(400001) }))[0], 400);
  assert.equal((await postReport(e, { body: RECORD, picture_b64: "not base 64!" }))[0], 400);
  assert.equal(e.DB.reports.length, 0);
});

const admin = (e, path, body) => worker.fetch(new Request(BASE + path,
  { method: "POST", headers: { "X-PAD-Admin": "adm", "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) }), e);

test("a report is stored whole, listed for the tracker, and blanked once taken", async () => {
  const e = env();
  const [st, out] = await postReport(e, { title: "Write stopped at 40%", body: RECORD, name: "Joe",
    email: "joe@example.com", app_version: "1.274.0", platform: "win32",
    picture_type: "image/jpeg", picture_b64: "/9j/4AAQ" });
  assert.equal(st, 201);
  assert.equal(out.ok, true);
  assert.equal((await get(env(), "/v1/admin/reports"))[0], 403);
  const [, list] = await get(e, "/v1/admin/reports", { "X-PAD-Admin": "adm" });
  assert.equal(list.rows.length, 1);
  const row = list.rows[0];
  assert.deepEqual([row.id, row.title, row.name, row.app_version, row.platform, row.picture_type, row.picture],
    [out.id, "Write stopped at 40%", "Joe", "1.274.0", "win32", "image/jpeg", "/9j/4AAQ"]);
  assert.equal(row.body, RECORD);
  assert.equal("email" in row, false);          // never asked for, never stored
  assert.equal("ip_hash" in row, false);
  const r = await admin(e, "/v1/admin/reports/" + out.id + "/taken");
  assert.equal(r.status, 200);
  const kept = e.DB.reports[0];
  assert.deepEqual([kept.state, kept.title, kept.body, kept.name, kept.picture, kept.ip_hash],
    ["filed", "", "", "", "", ""]);
  assert.equal((await get(e, "/v1/admin/reports", { "X-PAD-Admin": "adm" }))[1].rows.length, 0);
  const again = await admin(e, "/v1/admin/reports/" + out.id + "/taken");
  assert.equal(again.status, 404);
});

test("the app asks after its reports and hears when a release addresses one", async () => {
  const e = env();
  const [, a] = await postReport(e, { body: RECORD });
  const [, b] = await postReport(e, { body: RECORD });
  assert.equal((await get(e, "/v1/report/status?ids=" + a.id))[0], 403);
  const hdr = { "X-PAD-Key": "k" };
  let [st, out] = await get(e, "/v1/report/status?ids=" + a.id + "," + b.id + ",nope", hdr);
  assert.equal(st, 200);
  assert.deepEqual(out.rows.map((r) => [r.id, r.state]), [[a.id, "received"], [b.id, "received"]]);
  await admin(e, "/v1/admin/reports/" + a.id + "/taken");
  assert.equal((await admin(e, "/v1/admin/reports/" + a.id + "/answer", { state: "fixed" })).status, 400);
  assert.equal((await admin(e, "/v1/admin/reports/" + "0".repeat(32) + "/answer", { state: "released" })).status, 404);
  const ans = await admin(e, "/v1/admin/reports/" + a.id + "/answer",
    { state: "released", version: "1.275.0", message: "Fixed: the write no longer stops at 40%." });
  assert.equal(ans.status, 200);
  [st, out] = await get(e, "/v1/report/status?ids=" + a.id + "," + b.id, hdr);
  assert.deepEqual([out.rows[0].state, out.rows[0].version, out.rows[0].message, out.rows[1].state],
    ["released", "1.275.0", "Fixed: the write no longer stops at 40%.", "received"]);
  assert.ok(out.rows[0].answered_at > 0);
  // an answered row is dropped once it is old, and the app then hears "unknown"
  e.DB.reports[0].answered_at = 1;
  [st, out] = await get(e, "/v1/report/status?ids=" + a.id, hdr);
  assert.deepEqual([out.rows[0].state, e.DB.reports.length], ["unknown", 1]);
});

test("a report without a title is named by its first line, and one address gets five an hour", async () => {
  const e = env();
  const [, out] = await postReport(e, { body: "Write stopped\nmore" });
  assert.equal(e.DB.reports.find((r) => r.id === out.id).title, "Write stopped");
  for (let i = 0; i < 4; i++) assert.equal((await postReport(e, { body: RECORD }))[0], 201);
  assert.equal((await postReport(e, { body: RECORD }))[0], 429);
  assert.equal((await postReport(e, { body: RECORD }, { "X-PAD-Key": "k", "CF-Connecting-IP": "8.8.8.8" }))[0], 201);
});

test("David hears on Discord that a report came, never who sent it", async () => {
  const e = { ...env(), DISCORD_WEBHOOK: "https://discord.example/api/webhooks/1/x" };
  const posts = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => { posts.push([url, JSON.parse(init.body)]); return new Response("ok"); };
  const waited = [];
  const ctx = { waitUntil: (p) => waited.push(p) };
  try {
    await postReport(e, { title: "Write stopped at 40%", body: RECORD, name: "Joe",
      app_version: "1.274.0", platform: "darwin", picture_b64: "/9j/" }, undefined, ctx);
    await Promise.all(waited);
    assert.equal(posts.length, 1);
    assert.equal(posts[0][1].content, "🐞 Problem report from the app: Write stopped at 40% · app 1.274.0 on darwin · with a picture");
    assert.equal(posts[0][1].content.includes("Joe"), false);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("anything else is not found", async () => {
  assert.equal((await get(env(), "/v1/nope"))[0], 404);
  assert.equal((await get(env(), "/v1/admin/list"))[0], 403);
});
