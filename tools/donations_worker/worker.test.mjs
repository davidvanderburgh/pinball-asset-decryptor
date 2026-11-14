// node --test worker.test.mjs — the handler against a stand-in for D1 that
// answers the exact statements worker.js prepares.
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { meta } from "./worker.js";
const { MILESTONES, RATES, HOLD_OVER_USD } = meta();

function fakeDb() {
  const rows = [];
  const reports = [];
  const replyLog = [];
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
            .map(({ ip_hash, state, version, message, answered_at, stage, ticket, progress, stage_at,
                    seen_at, question, question_at, reply, reply_files, reply_at, reply_pending, ...r }) => r) };
        }
        if (sql.startsWith("SELECT id, ticket, question, question_at, reply_at, reply, reply_files FROM reports")) {
          return { results: reports.filter((r) => r.reply_pending === 1).sort((a, b) => a.reply_at - b.reply_at)
            .slice(0, 10).map((r) => ({ id: r.id, ticket: r.ticket, question: r.question,
              question_at: r.question_at, reply_at: r.reply_at, reply: r.reply, reply_files: r.reply_files })) };
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
        if (sql.startsWith("SELECT id, state, version, message, answered_at, stage, ticket, progress, " +
                           "question, question_at, reply_at FROM reports")) {
          const r = reports.find((x) => x.id === args[0]);
          return r ? { id: r.id, state: r.state, version: r.version, message: r.message, answered_at: r.answered_at,
            stage: r.stage, ticket: r.ticket, progress: r.progress, question: r.question,
            question_at: r.question_at, reply_at: r.reply_at } : null;
        }
        if (sql.startsWith("SELECT state, reply_pending FROM reports WHERE id = ?")) {
          const r = reports.find((x) => x.id === args[0]);
          return r ? { state: r.state, reply_pending: r.reply_pending } : null;
        }
        if (sql.startsWith("SELECT COUNT(*) AS n FROM reply_log WHERE ip_hash")) {
          return { n: replyLog.filter((r) => r.ip_hash === args[0] && r.at > args[1]).length };
        }
        if (sql.startsWith("SELECT seen_at FROM reports")) {
          const r = reports.find((x) => x.id === args[0]);
          return r ? { seen_at: r.seen_at } : null;
        }
        throw new Error("unexpected first(): " + sql);
      },
      async run() {
        if (sql.startsWith("INSERT INTO reports")) {
          const [id, at, app_version, platform, title, body, name, picture_type, picture, ip_hash, install] = args;
          reports.push({ id, at, app_version, platform, title, body, name, picture_type, picture, ip_hash, install,
            state: "received", version: "", message: "", answered_at: 0,
            stage: "", ticket: "", progress: -1, stage_at: 0, seen_at: 0,
            question: "", question_at: 0, reply: "", reply_files: "[]", reply_at: 0, reply_pending: 0 });
          return { meta: { changes: 1 } };
        }
        if (sql.startsWith("UPDATE reports SET state = 'filed'")) {
          const r = reports.find((x) => x.id === args[0] && x.state === "received");
          if (r) Object.assign(r, { state: "filed", title: "", body: "", name: "", picture_type: "", picture: "",
            ip_hash: "", install: "", stage: "queued" });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET stage = ?, ticket = ?, progress = ?, stage_at = ?, question = ?, " +
                           "question_at = ?, reply = '', reply_files = '[]', reply_pending = 0 WHERE id = ?")) {
          const r = reports.find((x) => x.id === args[6]);
          if (r) Object.assign(r, { stage: args[0], ticket: args[1], progress: args[2], stage_at: args[3],
            question: args[4], question_at: args[5], reply: "", reply_files: "[]", reply_pending: 0 });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET reply = ?, reply_files = ?, reply_at = ?, reply_pending = 1, " +
                           "stage = 'working' WHERE id = ? AND stage = 'question' AND reply_pending = 0 " +
                           "AND reply_at < question_at")) {
          const r = reports.find((x) => x.id === args[3] && x.stage === "question" && x.reply_pending === 0
            && x.reply_at < x.question_at);
          if (r) Object.assign(r, { reply: args[0], reply_files: args[1], reply_at: args[2], reply_pending: 1,
            stage: "working" });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET reply = ?, reply_files = ?, reply_at = ?, reply_pending = 1, " +
                           "stage = CASE WHEN stage = 'question' THEN 'working' ELSE stage END " +
                           "WHERE id = ? AND reply_pending = 0 AND state != 'received'")) {
          const r = reports.find((x) => x.id === args[3] && x.reply_pending === 0 && x.state !== "received");
          if (r) Object.assign(r, { reply: args[0], reply_files: args[1], reply_at: args[2], reply_pending: 1,
            stage: r.stage === "question" ? "working" : r.stage });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET reply = '', reply_files = '[]', reply_pending = 0 WHERE id = ?")) {
          const r = reports.find((x) => x.id === args[0]);
          if (r) Object.assign(r, { reply: "", reply_files: "[]", reply_pending: 0 });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("DELETE FROM reply_log WHERE at <= ?")) {
          let n = 0;
          for (let i = replyLog.length - 1; i >= 0; i--) {
            if (replyLog[i].at <= args[0]) { replyLog.splice(i, 1); n++; }
          }
          return { meta: { changes: n } };
        }
        if (sql.startsWith("INSERT INTO reply_log")) {
          replyLog.push({ ip_hash: args[0], at: args[1] });
          return { meta: { changes: 1 } };
        }
        if (sql.startsWith("UPDATE reports SET stage = ?, ticket = ?, progress = ?, stage_at = ? WHERE id = ?")) {
          const r = reports.find((x) => x.id === args[4]);
          if (r) Object.assign(r, { stage: args[0], ticket: args[1], progress: args[2], stage_at: args[3] });
          return { meta: { changes: r ? 1 : 0 } };
        }
        if (sql.startsWith("UPDATE reports SET seen_at = ?")) {
          let n = 0;
          for (const r of reports) if (args.slice(1).includes(r.id)) { r.seen_at = args[0]; n++; }
          return { meta: { changes: n } };
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
  return { prepare: stmt, rows, reports, replyLog };
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

test("the tracker moves a report along the app's board, and hears when the app last looked", async () => {
  const e = env();
  const [, a] = await postReport(e, { body: RECORD, install: "0123456789abcdef" });
  const [, b] = await postReport(e, { body: RECORD, install: "not an id" });
  assert.equal(e.DB.reports[0].install, "0123456789abcdef");
  assert.equal(e.DB.reports[1].install, "", "only 16 hex digits are kept");
  const [, list] = await get(e, "/v1/admin/reports", { "X-PAD-Admin": "adm" });
  assert.equal(list.rows[0].install, "0123456789abcdef");
  await admin(e, "/v1/admin/reports/" + a.id + "/taken");
  assert.deepEqual([e.DB.reports[0].stage, e.DB.reports[0].install], ["queued", ""]);
  const hdr = { "X-PAD-Key": "k" };
  // not yet asked: the push hears seen_at 0
  let r = await admin(e, "/v1/admin/reports/" + a.id + "/stage", { stage: "working", ticket: "PAD-914", progress: 45 });
  assert.equal(r.status, 200);
  const first = await r.json();
  assert.deepEqual([first.ok, first.id, first.stage, first.seen_at], [true, a.id, "working", 0]);
  assert.ok(first.at > 0, "the push answers with the Worker's own clock");
  let [, out] = await get(e, "/v1/report/status?ids=" + a.id + "," + b.id, hdr);
  assert.deepEqual([out.rows[0].stage, out.rows[0].ticket, out.rows[0].progress], ["working", "PAD-914", 45]);
  assert.deepEqual([out.rows[1].stage, out.rows[1].progress], ["", -1]);
  assert.ok(e.DB.reports[0].seen_at > 0 && e.DB.reports[1].seen_at > 0);
  r = await admin(e, "/v1/admin/reports/" + a.id + "/stage", { stage: "ready", ticket: "PAD-914", progress: 250 });
  const j = await r.json();
  assert.equal(j.seen_at, e.DB.reports[0].seen_at, "the push says when the app last asked");
  assert.equal(e.DB.reports[0].progress, -1, "a percent out of range is not said");
  assert.equal((await admin(e, "/v1/admin/reports/" + a.id + "/stage", { stage: "fixed" })).status, 400);
  assert.equal((await admin(e, "/v1/admin/reports/" + "0".repeat(32) + "/stage", { stage: "queued" })).status, 404);
  const anon = await worker.fetch(new Request(BASE + "/v1/admin/reports/" + a.id + "/stage",
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }), e);
  assert.equal(anon.status, 403);
  // an unknown id is still "unknown", with the board's fields blank
  [, out] = await get(e, "/v1/report/status?ids=" + "f".repeat(32), hdr);
  assert.deepEqual([out.rows[0].state, out.rows[0].stage, out.rows[0].progress], ["unknown", "", -1]);
});

test("a report without a title is named by its first line, and one address gets five an hour", async () => {
  const e = env();
  const [, out] = await postReport(e, { body: "Write stopped\nmore" });
  assert.equal(e.DB.reports.find((r) => r.id === out.id).title, "Write stopped");
  for (let i = 0; i < 4; i++) assert.equal((await postReport(e, { body: RECORD }))[0], 201);
  assert.equal((await postReport(e, { body: RECORD }))[0], 429);
  assert.equal((await postReport(e, { body: RECORD }, { "X-PAD-Key": "k", "CF-Connecting-IP": "8.8.8.8" }))[0], 201);
});

test("a report posts nothing to the #donations webhook", async () => {
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
    assert.equal(posts.length, 0);                        // pad-triage posts it in #bug-reports
    assert.equal(waited.length, 0);
  } finally {
    globalThis.fetch = realFetch;
  }
});

// ---- questions and answers (PAD-972) ---------------------------------------
const reply = (e, id, body, headers = { "X-PAD-Key": "k", "CF-Connecting-IP": "7.7.7.7" }) =>
  worker.fetch(new Request(BASE + "/v1/report/" + id + "/reply", {
    method: "POST", headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body) }), e);

async function asked(e) {
  const [, a] = await postReport(e, { body: RECORD });
  await admin(e, "/v1/admin/reports/" + a.id + "/taken");
  return a.id;
}

test("a question reaches the app's status with its words and clears an earlier answer", async () => {
  const e = env();
  const id = await asked(e);
  const hdr = { "X-PAD-Key": "k" };
  let [, out] = await get(e, "/v1/report/status?ids=" + id, hdr);
  assert.deepEqual([out.rows[0].question, out.rows[0].question_at, out.rows[0].reply_at], ["", 0, 0]);
  const r = await admin(e, "/v1/admin/reports/" + id + "/stage",
    { stage: "question", ticket: "PAD-968", question: "  Can you send DirectOutput.log?\r\nIt is in the DOF folder.  " });
  assert.equal(r.status, 200);
  const j = await r.json();
  assert.deepEqual([j.ok, j.id, j.stage], [true, id, "question"]);
  assert.ok(j.at > 0 && "seen_at" in j, "the answer is unchanged");
  [, out] = await get(e, "/v1/report/status?ids=" + id, hdr);
  const row = out.rows[0];
  assert.deepEqual([row.stage, row.ticket, row.question],
    ["question", "PAD-968", "Can you send DirectOutput.log?\nIt is in the DOF folder."]);
  assert.ok(row.question_at > 0 && row.reply_at === 0);
  // a long question is cut at 4000
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "question", question: "q".repeat(5000) });
  assert.equal(e.DB.reports[0].question.length, 4000);
  // any other stage leaves the question alone
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "working", ticket: "PAD-968", progress: 30 });
  assert.equal(e.DB.reports[0].question.length, 4000);
  assert.ok(e.DB.reports[0].question_at > 0);
  // a new question clears an answer the tracker has not taken
  Object.assign(e.DB.reports[0], { reply: "old", reply_files: "[{}]", reply_pending: 1, reply_at: 5 });
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "question", question: "Again?" });
  assert.deepEqual([e.DB.reports[0].reply, e.DB.reports[0].reply_files, e.DB.reports[0].reply_pending,
    e.DB.reports[0].reply_at], ["", "[]", 0, 5], "reply_at stays");
  // an unknown id still answers every field
  [, out] = await get(e, "/v1/report/status?ids=" + "e".repeat(32), hdr);
  assert.deepEqual([out.rows[0].question, out.rows[0].question_at, out.rows[0].reply_at], ["", 0, 0]);
});

test("the app answers a question once, with words and files, and the tracker collects and clears it", async () => {
  const e = env();
  const id = await asked(e);
  const other = await asked(e);
  // no question yet: 409
  assert.equal((await reply(e, id, { message: "hi" })).status, 409);
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "question", ticket: "PAD-968", question: "Log?" });
  e.DB.reports[0].question_at -= 10;          // the answer comes later than the question
  // the app key, words or a file, and the limits
  assert.equal((await reply(e, id, { message: "x" }, { "CF-Connecting-IP": "7.7.7.7" })).status, 403);
  assert.equal((await reply(e, id, { message: "   " })).status, 400);
  assert.equal((await reply(e, id, { message: "x".repeat(20001) })).status, 400);
  assert.equal((await reply(e, id, { files: [{ name: "a", b64: "not base 64!" }] })).status, 400);
  const six = Array.from({ length: 6 }, (_, i) => ({ name: "f" + i, type: "text/plain", b64: "aGk=" }));
  assert.equal((await reply(e, id, { files: six })).status, 400);
  assert.equal((await reply(e, id, { files: [{ name: "big", b64: "A".repeat(1500001) }] })).status, 400);
  assert.equal(e.DB.reports[0].reply_pending, 0, "a refused answer changes nothing");
  // the answer
  const files = [{ name: "../Direct Output?.log", type: "text/plain", b64: "bG9nIGxpbmUK" },
                 { name: "shot.png", type: "image/png", b64: "iVBORw0K" }];
  let r = await reply(e, id, { message: "  Here it is.\nTwo lines.  ", files });
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { ok: true, id });
  const row = e.DB.reports[0];
  assert.deepEqual([row.stage, row.reply_pending, row.reply], ["working", 1, "Here it is.\nTwo lines."]);
  assert.ok(row.reply_at >= row.question_at);
  // one answer per question
  assert.equal((await reply(e, id, { message: "and another" })).status, 409);
  // the app hears it is answered: reply_at is past question_at
  const [, st] = await get(e, "/v1/report/status?ids=" + id, { "X-PAD-Key": "k" });
  assert.ok(st.rows[0].reply_at >= st.rows[0].question_at && st.rows[0].stage === "working");
  // the tracker collects it
  assert.equal((await get(e, "/v1/admin/replies"))[0], 403);
  let [, list] = await get(e, "/v1/admin/replies", { "X-PAD-Admin": "adm" });
  assert.equal(list.ok, true);
  assert.equal(list.rows.length, 1);
  const got = list.rows[0];
  assert.deepEqual([got.id, got.ticket, got.question, got.message], [id, "PAD-968", "Log?", "Here it is.\nTwo lines."]);
  assert.ok(got.question_at > 0 && got.reply_at > 0);
  assert.deepEqual(got.files, [{ name: ".._Direct Output_.log", type: "text/plain", b64: "bG9nIGxpbmUK" },
                               { name: "shot.png", type: "image/png", b64: "iVBORw0K" }]);
  // ... and says it has it
  assert.equal((await admin(e, "/v1/admin/reports/" + "0".repeat(32) + "/reply-taken")).status, 404);
  const anon = await worker.fetch(new Request(BASE + "/v1/admin/reports/" + id + "/reply-taken",
    { method: "POST" }), e);
  assert.equal(anon.status, 403);
  r = await admin(e, "/v1/admin/reports/" + id + "/reply-taken");
  assert.equal(r.status, 200);
  assert.deepEqual([row.reply, row.reply_files, row.reply_pending], ["", "[]", 0]);
  assert.ok(row.reply_at > 0, "reply_at stays");
  [, list] = await get(e, "/v1/admin/replies", { "X-PAD-Admin": "adm" });
  assert.equal(list.rows.length, 0);
  // still answered: no second answer until a new question
  assert.equal((await reply(e, id, { message: "more" })).status, 409);
  // the other report was never asked
  assert.equal((await reply(e, other, { message: "hi" })).status, 409);
  // a new question opens the way again (it comes after the last answer)
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "question", question: "And the table?" });
  row.reply_at = row.question_at - 1;
  assert.equal((await reply(e, id, { message: "Godzilla." })).status, 200);
  [, list] = await get(e, "/v1/admin/replies", { "X-PAD-Admin": "adm" });
  assert.deepEqual([list.rows[0].question, list.rows[0].message, list.rows[0].files], ["And the table?", "Godzilla.", []]);
});

test("an answer counts against the reports' hourly limit for its address", async () => {
  const e = env();
  const ids = [];
  for (let i = 0; i < 3; i++) {
    const [, a] = await postReport(e, { body: RECORD }, { "X-PAD-Key": "k", "CF-Connecting-IP": "6.6.6.6" });
    await admin(e, "/v1/admin/reports/" + a.id + "/taken");
    await admin(e, "/v1/admin/reports/" + a.id + "/stage", { stage: "question", question: "?" });
    ids.push(a.id);
  }
  for (const r of e.DB.reports) r.question_at -= 10;
  const from = { "X-PAD-Key": "k", "CF-Connecting-IP": "6.6.6.6" };
  // the reports were taken, so their hashes are gone: answers count in the log
  assert.equal((await reply(e, ids[0], { message: "a" }, from)).status, 200);
  assert.equal(e.DB.replyLog.length, 1);
  assert.equal((await postReport(e, { body: RECORD }, from))[0], 201);
  assert.equal((await postReport(e, { body: RECORD }, from))[0], 201);
  assert.equal((await postReport(e, { body: RECORD }, from))[0], 201);
  // three reports still carrying the hash + one answer = 4; one more answer is 5 ...
  assert.equal((await reply(e, ids[1], { message: "b" }, from)).status, 200);
  // ... and the sixth thing in the hour is refused
  assert.equal((await reply(e, ids[2], { message: "c" }, from)).status, 429);
  assert.equal((await reply(e, ids[2], { message: "c" }, { "X-PAD-Key": "k", "CF-Connecting-IP": "5.5.5.5" })).status, 200);
  // an hour on, the log forgets the address
  for (const r of e.DB.replyLog) r.at -= 3601;
  const [, a] = await postReport(e, { body: RECORD }, { "X-PAD-Key": "k", "CF-Connecting-IP": "4.4.4.4" });
  await admin(e, "/v1/admin/reports/" + a.id + "/taken");
  await admin(e, "/v1/admin/reports/" + a.id + "/stage", { stage: "question", question: "?" });
  e.DB.reports.find((r) => r.id === a.id).question_at -= 10;
  assert.equal((await reply(e, a.id, { message: "d" }, { "X-PAD-Key": "k", "CF-Connecting-IP": "4.4.4.4" })).status, 200);
  assert.equal(e.DB.replyLog.length, 1, "older log rows went");
});

test("anything else is not found", async () => {
  assert.equal((await get(env(), "/v1/nope"))[0], 404);
  assert.equal((await get(env(), "/v1/admin/list"))[0], 403);
});

// ---- follow-ups (PAD-1254) --------------------------------------------------
test("a follow-up goes onto a filed report in any stage, one at a time, and the tracker collects it", async () => {
  const e = env();
  const id = await asked(e);
  const row = e.DB.reports[0];
  // an answer still needs a question: an older app is unchanged
  assert.equal((await reply(e, id, { message: "more" })).status, 409);
  // a follow-up while it is being worked on: words and files, stage left alone
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "ready", ticket: "PAD-1225", progress: 100 });
  const files = [{ name: "pad-report.txt", type: "text/plain", b64: "bG9nCg==" },
                 { name: "picture.jpg", type: "image/jpeg", b64: "/9j/" }];
  let r = await reply(e, id, { message: "Still happens.", files, follow_up: true });
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { ok: true, id, follow_up: true });
  assert.deepEqual([row.stage, row.reply_pending, row.reply], ["ready", 1, "Still happens."]);
  // one waiting at a time: the next waits for the tracker
  r = await reply(e, id, { message: "And again.", follow_up: true });
  assert.equal(r.status, 409);
  assert.equal((await r.json()).code, "pending");
  let [, list] = await get(e, "/v1/admin/replies", { "X-PAD-Admin": "adm" });
  assert.deepEqual([list.rows[0].id, list.rows[0].ticket, list.rows[0].message, list.rows[0].files.length],
    [id, "PAD-1225", "Still happens.", 2]);
  await admin(e, "/v1/admin/reports/" + id + "/reply-taken");
  // released: still takes one, and the answer the app has stays
  await admin(e, "/v1/admin/reports/" + id + "/answer", { state: "released", version: "1.428.0", message: "Fixed." });
  assert.equal((await reply(e, id, { message: "Not fixed for me.", follow_up: true })).status, 200);
  assert.deepEqual([row.state, row.version, row.reply_pending], ["released", "1.428.0", 1]);
  await admin(e, "/v1/admin/reports/" + id + "/reply-taken");
  // a question it answers moves on, as an answer does
  await admin(e, "/v1/admin/reports/" + id + "/stage", { stage: "question", question: "Log?" });
  row.question_at -= 10;
  assert.equal((await reply(e, id, { message: "Here.", follow_up: true })).status, 200);
  assert.equal(row.stage, "working");
  assert.ok(row.reply_at >= row.question_at);
  // not yet filed, or gone
  const [, fresh] = await postReport(e, { body: RECORD });
  r = await reply(e, fresh.id, { message: "x", follow_up: true });
  assert.equal(r.status, 409);
  assert.equal((await r.json()).code, "not_filed");
  r = await reply(e, "f".repeat(32), { message: "x", follow_up: true });
  assert.equal(r.status, 404);
  assert.equal((await r.json()).code, "gone");
  // the same limits as an answer
  assert.equal((await reply(e, id, { message: "x", follow_up: true }, { "CF-Connecting-IP": "7.7.7.7" })).status, 403);
});
