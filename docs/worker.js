// Runs Relate (WASM) off the main thread: builds the RFC graph from data/graph.json, then answers Cypher.
const RELATE = "https://cdn.jsdelivr.net/npm/@relate/relate-wasm@1.3.0/relate.js";
let db = null;

const post = (msg) => self.postMessage(msg);

function run(q, params) {
  const env = JSON.parse(db.execute(q, params ? JSON.stringify(params) : null));
  if (env.error) throw new Error(env.error.message || JSON.stringify(env.error));
  return env;
}

async function load() {
  const mod = await import(RELATE);
  await mod.default();
  db = new mod.RelateDb();
  post({ type: "progress", text: "downloading the graph", pct: 5 });
  const G = await (await fetch("data/graph.json")).json();
  const steps = [], timings = [];
  steps.push(["constraints", () => {
    run("CREATE CONSTRAINT rfc_number IF NOT EXISTS FOR (r:RFC) REQUIRE r.number IS UNIQUE");
    run("CREATE CONSTRAINT rfc_id IF NOT EXISTS FOR (r:RFC) REQUIRE r.id IS UNIQUE");
  }]);
  for (let i = 0; i < G.rfcs.length; i += 5000) {
    const rows = G.rfcs.slice(i, i + 5000);
    steps.push([`RFC nodes ${i + rows.length}`, () => run(
      "UNWIND $rows AS x CREATE (:RFC {number: x[0], id: 'RFC' + toString(x[0]), title: x[1], date: x[2], " +
      "status: x[3], obsolete: x[4] = 1, errata: x[5], wg: x[6], oldVersion: x[7] = 1})", { rows })]);
  }
  const later = [];  // normative references load after the page is usable
  for (const [type, all] of Object.entries(G.edges)) {
    const list = type === "NORMATIVE_REF" ? later : steps;
    for (let i = 0; i < all.length; i += 10000) {
      const rows = all.slice(i, i + 10000);
      const props = type === "OBSOLETES" ? " {kind: x[2]}" : "";
      list.push([`${type} ${i + rows.length}`, () => run(
        `UNWIND $rows AS x MATCH (a:RFC {number: x[0]}), (b:RFC {number: x[1]}) CREATE (a)-[:${type}${props}]->(b)`, { rows })]);
    }
  }
  steps.push(["series", () => run(
    "UNWIND $rows AS x CREATE (s:Series {id: x[0]}) WITH s, x UNWIND x[1] AS n MATCH (r:RFC {number: n}) CREATE (s)-[:INCLUDES]->(r)",
    { rows: G.series })]);
  steps.push(["projects", () => {
    for (const p of G.projects) {
      run("CREATE (:Project {name: $name, repo: $repo, commit: $commit, url: $url})", p);
      const rows = p.files.map(([path, cites]) => ({ path, cites }));
      run(`MATCH (p:Project {name: $name}) UNWIND $rows AS f
           CREATE (p)-[:HAS_FILE]->(file:File {path: f.path, project: $name})
           WITH file, f UNWIND f.cites AS c MATCH (r:RFC {number: c[0]})
           CREATE (file)-[:CITES {lines: c[1]}]->(r)`, { name: p.name, rows });
    }
  }]);
  steps.push(["full-text index", () => run("CREATE FULLTEXT INDEX rfc_title IF NOT EXISTS FOR (r:RFC) ON EACH [r.title]")]);
  for (let i = 0; i < steps.length; i++) {
    post({ type: "progress", text: `building in your browser: ${steps[i][0]}`, pct: 10 + Math.round(88 * i / steps.length) });
    await new Promise((r) => setTimeout(r, 0));
    const t = performance.now();
    steps[i][1]();
    timings.push(`${steps[i][0]} ${Math.round(performance.now() - t)}ms`);
  }
  console.log("[specrot] build " + timings.join(", "));
  const count = () => run("MATCH (n) WITH count(n) AS n MATCH ()-[r]->() RETURN n, count(r) AS r").rows[0];
  post({ type: "ready", ...count(), built: G.built, partial: true });
  for (const [, fn] of later) {
    await new Promise((r) => setTimeout(r, 0));  // let queued queries run between batches
    fn();
  }
  post({ type: "ready", ...count(), built: G.built, partial: false });
}

// The console is read-only: the page's own queries never write, and a visitor's DELETE would only
// break this tab's copy, but refusing it keeps the demo intact. Backtick names, comments and string
// literals are blanked in one left-to-right pass, so a quote inside one cannot hide a keyword.
const WRITES = /\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|INSERT|FOREACH|LOAD\s+CSV)\b/i;
const OPAQUE = /`[^`]*`|\/\*[\s\S]*?\*\/|\/\/[^\n]*|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g;

self.onmessage = (e) => {
  const { id, q, params, console: fromConsole } = e.data;
  const t = performance.now();
  try {
    if (fromConsole && WRITES.test(q.replace(OPAQUE, " x ")))
      throw new Error("This console is read-only (it runs on the copy of the graph in your tab). Use MATCH ... RETURN; the CLI has `specrot cypher --write` for a local store.");
    const env = run(q, params);
    post({ id, rows: env.rows, columns: env.columns, ms: performance.now() - t });
  } catch (err) {
    post({ id, error: String(err.message || err) });
  }
};

load().catch((err) => post({ type: "fatal", error: String(err.message || err) }));
