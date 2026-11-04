// worker.js on this PC, over a real SQLite database: a stand-in for
// `wrangler dev` that needs nothing installed beyond Node 22.5+ (node:sqlite).
// The app's tests and proof shots point PAD_REPORTS_URL at it (PAD-972).
//
//   node local_worker.mjs [port] [--dir <folder with worker.js + schema.sql>]
//                         [--db <file>] [--migrate <file.sql>]
//
// Prints "local worker on <port>" once it listens.  --db keeps the database
// in a file (default: in memory).  --migrate runs that file after
// schema.sql, which is how a migration is tried on an old schema.  The
// keys are APP_KEY / ADMIN_KEY from the environment (default: the app's
// public key, and "adm").
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath, pathToFileURL } from "node:url";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const port = Number(args[0] && !args[0].startsWith("--") ? args[0] : 8799);
const dir = path.resolve(opt("--dir", path.dirname(fileURLToPath(import.meta.url))));
const worker = (await import(pathToFileURL(path.join(dir, "worker.js")).href)).default;
const db = new DatabaseSync(opt("--db", ":memory:"));
db.exec(fs.readFileSync(path.join(dir, "schema.sql"), "utf8"));
if (opt("--migrate")) db.exec(fs.readFileSync(opt("--migrate"), "utf8"));

// D1's prepare / bind / all / first / run, on node:sqlite
const D1 = {
  prepare(sql) {
    const st = db.prepare(sql);
    let bound = [];
    const s = {
      bind(...a) { bound = a; return s; },
      async all() { return { results: st.all(...bound) }; },
      async first() { return st.get(...bound) || null; },
      async run() { return { meta: { changes: Number(st.run(...bound).changes) } }; },
    };
    return s;
  },
};
const env = {
  DB: D1,
  APP_KEY: process.env.APP_KEY || "pad-shelters-2026",
  ADMIN_KEY: process.env.ADMIN_KEY || "adm",
  IP_SALT: "local",
};

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks);
  const r = await worker.fetch(new Request("http://127.0.0.1:" + port + req.url, {
    method: req.method,
    headers: { ...req.headers, "cf-connecting-ip": req.socket.remoteAddress || "" },
    body: body.length ? body : undefined,
  }), env, { waitUntil() {} });
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
  console.log(req.method + " " + req.url.split("?")[0] + " " + r.status);
}).listen(port, "127.0.0.1", () => console.log("local worker on " + port));
