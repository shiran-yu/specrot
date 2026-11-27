// specrot explorer: every query below is Cypher run by Relate (WASM) in worker.js.
const worker = new Worker("worker.js", { type: "module" });
const pending = new Map();
let seq = 0;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function cypher(q, params, fromConsole = false, needs = null) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject, q });
    worker.postMessage({ id, q, params, console: fromConsole, needs });
  });
}

worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "progress") {
    $("#progress-text").textContent = m.text;
    $("#progress-bar").style.width = m.pct + "%";
  } else if (m.type === "ready") {
    $("#loading").hidden = true;
    $("#stats").textContent = `${m.n.toLocaleString()} nodes · ${m.r.toLocaleString()} relationships (RFCs, series, projects; obsoletes, updates, normative references) · RFC index of ${m.built} · built in this tab by Relate (WASM)` + (m.partial ? " · loading 50k normative references…" : "");
    if (!document.body.classList.contains("ready")) { document.body.classList.add("ready"); route(); }
  } else if (m.type === "fatal") {
    $("#progress-text").textContent = "Could not start Relate: " + m.error;
  } else if (pending.has(m.id)) {
    const p = pending.get(m.id);
    pending.delete(m.id);
    lastQuery = { q: p.q, ms: m.ms };
    m.error ? p.reject(new Error(m.error)) : p.resolve(m.rows);
  }
};
let lastQuery = null;

// ---------- queries (same as specrot/graph.py) ----------
const Q = {
  // where a section of an obsolete RFC lives now: CONTINUES_AS (matched headings) to a document in force
  section: `MATCH (s:Section {id: $id})
MATCH p = (s)-[:CONTINUES_AS]->+(t:Section)
MATCH (r:RFC {id: t.rfc}) WHERE NOT r.obsolete
RETURN r.id AS rfc, t.number AS section, t.title AS title, s.title AS was,
       all(e IN relationships(p) WHERE e.exact) AS exact, size(relationships(p)) AS hops ORDER BY hops`,
  info: `MATCH (r:RFC {number: $n})
OPTIONAL MATCH (s:Series)-[:INCLUDES]->(r)
RETURN r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete,
       r.oldVersion AS oldVersion, r.errata AS errata, r.wg AS wg, collect(s.id) AS series`,
  replacements: `MATCH (r:RFC {number: $n})
MATCH p = (r)<-[:OBSOLETES]-+(cur:RFC) WHERE NOT cur.obsolete
RETURN [x IN nodes(p) | x.id] AS chain, [e IN relationships(p) | e.kind] AS kinds,
       cur.id AS current, cur.title AS title, cur.date AS date
ORDER BY size(chain)`,
  updates: `MATCH (r:RFC {number: $n})<-[:UPDATES]-(u:RFC) WHERE NOT u.obsolete
RETURN u.id AS id, u.title AS title, u.date AS date ORDER BY u.date DESC`,
  lineage: `MATCH (r:RFC {number: $n})
CALL (r) {
  MATCH p = (r)-[:OBSOLETES]->{1,6}(:RFC) RETURN p
  UNION MATCH p = (r)<-[:OBSOLETES]-{1,6}(:RFC) RETURN p
  UNION MATCH p = (r)<-[:UPDATES]-(:RFC) RETURN p
  UNION MATCH p = (r)-[:UPDATES]->(:RFC) RETURN p
}
UNWIND relationships(p) AS rel
RETURN DISTINCT startNode(rel).id AS a, endNode(rel).id AS b, type(rel) AS type`,
  nodes: `UNWIND $ids AS id MATCH (r:RFC {id: id})
RETURN r.id AS id, r.title AS title, r.date AS date, r.obsolete AS obsolete,
       EXISTS { (r)<-[:UPDATES]-(u:RFC) WHERE NOT u.obsolete } AS amended`,
  projectsCiting: `MATCH (p:Project)-[:HAS_FILE]->(f:File)-[c:CITES]->(r:RFC {number: $n})
RETURN p.name AS project, p.repo AS repo, p.url AS url, f.path AS path, c.lines AS lines ORDER BY project, path`,
  search: `MATCH (r:RFC) SEARCH r IN (FULLTEXT INDEX rfc_title FOR $q LIMIT 25) SCORE AS score
RETURN r.number AS n, r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete
ORDER BY score DESC`,
  judge: `UNWIND $ns AS n MATCH (r:RFC {number: n})
OPTIONAL MATCH p = (r)<-[:OBSOLETES]-+(cur:RFC) WHERE NOT cur.obsolete AND last(relationships(p)).kind <> 'retired'
WITH r, collect(DISTINCT cur.id) AS current
RETURN r.number AS n, r.id AS id, r.title AS title, r.obsolete AS obsolete, r.oldVersion AS oldVersion,
       r.status AS status, current,
       COLLECT { MATCH (r)<-[:UPDATES]-(u:RFC) WHERE NOT u.obsolete RETURN u.id } AS updates,
       r.errata AS errata`,
  projects: `MATCH (p:Project)
OPTIONAL MATCH (p)-[:HAS_FILE]->(:File)-[c:CITES]->(r:RFC)
WITH p, sum(size(c.lines)) AS cites, sum(CASE WHEN r.obsolete AND NOT r.oldVersion THEN size(c.lines) ELSE 0 END) AS stale
RETURN p.name AS name, p.repo AS repo, p.url AS url, cites, stale ORDER BY toFloat(stale) / cites DESC`,
  projectStale: `MATCH (p:Project {name: $name})-[:HAS_FILE]->(f:File)-[c:CITES]->(r:RFC) WHERE r.obsolete AND NOT r.oldVersion
OPTIONAL MATCH q = (r)<-[:OBSOLETES]-+(cur:RFC) WHERE NOT cur.obsolete AND last(relationships(q)).kind <> 'retired'
RETURN r.id AS id, r.title AS title, f.path AS path, c.lines AS lines, collect(DISTINCT cur.id) AS current
ORDER BY id, path`,
};

// same order as graph.py Verdict.level: a retired protocol version (TLS 1.0) is historic, not old-version
const level = (r) => r === null ? "unknown" : r.obsolete && !r.oldVersion ? "obsolete" : r.status === "HISTORIC" ? "historic"
  : r.obsolete ? "old-version" : (r.updates?.length || r.errata) ? "amended" : "ok";
const badge = (lvl) => `<span class="badge ${lvl}">${{ obsolete: "✗ obsolete", "old-version": "↑ old version", historic: "✗ historic", amended: "! amended", ok: "✓ current", unknown: "? unknown" }[lvl]}</span>`;
const rfcLink = (id) => `<a href="#rfc=${id.replace("RFC", "")}" class="rfc">${id}</a>`;
const DEPRECATING = /deprecat|prohibit|obsolet|historic|retir|removing|sunset/i;
// Kinds of OBSOLETES edges, computed when the store is built (specrot/build.py).
const KIND_TEXT = { edition: "new edition of the same specification", version: "newer protocol version: the old RFC still defines the old version",
  split: "content split across several documents", retired: "retired without a replacement" };
const pathKind = (k) => k.at(-1) === "retired" ? "retired" : k.includes("version") ? "version" : k.includes("split") ? "split" : "edition";

function showQuery(el, q = lastQuery) {
  if (!q) return;
  el.innerHTML = `<details><summary>Cypher · ${q.ms.toFixed(1)} ms in Relate WASM</summary><pre>${esc(q.q)}</pre></details>`;
}

// ---------- check tab ----------
let renderSeq = 0;  // render token: a newer check or search makes slower, older ones drop their output
async function check(input) {
  const out = $("#check-out");
  const m = String(input).match(/^\s*(?:rfc)?\s*[-#]?\s*0*(\d{1,5})(?:\s*(?:#|§|,?\s*sec(?:tion)?\.?)\s*([A-Z](?:\.\d+)*|\d+(?:\.\d+)*))?\.?\s*$/i);
  if (!m) return search(input);
  const n = Number(m[1]), sec = m[2] ? m[2].toUpperCase() : null;
  rendered = sec ? `rfc=${n}&s=${sec}` : `rfc=${n}`;
  if (location.hash.slice(1) !== rendered) location.hash = rendered;  // the hashchange handler skips it
  $("#q").value = sec ? `RFC ${n} §${sec}` : `RFC ${n}`;
  const my = ++renderSeq;
  const [info] = await cypher(Q.info, { n });
  if (my !== renderSeq) return;
  if (!info) { out.innerHTML = `<div class="card">${badge("unknown")} RFC ${n} is not in the RFC index.</div>`; return; }
  const repl = info.obsolete ? await cypher(Q.replacements, { n }) : [];
  const ups = await cypher(Q.updates, { n });
  if (my !== renderSeq) return;
  const lvl = level({ ...info, updates: ups });
  const infoQuery = lastQuery;
  let secRows = null, secQuery = null;
  if (sec && info.obsolete) {
    secRows = await cypher(Q.section, { id: `RFC${n}#${sec}` }, false, "sections");
    secQuery = lastQuery;
    if (my !== renderSeq) return;
  }
  const shortest = {};
  for (const r of repl) if (!shortest[r.current] || r.chain.length < shortest[r.current].chain.length) shortest[r.current] = { ...r, kind: pathKind(r.kinds) };
  const deps = ups.filter((u) => DEPRECATING.test(u.title));
  const others = ups.filter((u) => !DEPRECATING.test(u.title));
  let html = `<div class="card verdict ${lvl}">
    <div class="head">${badge(lvl)} <h2>${info.id}</h2> <span class="title">${esc(info.title)}</span></div>
    <div class="meta">${esc(info.date)} · ${esc((info.status || "").toLowerCase())}${info.wg && info.wg !== "NON WORKING GROUP" ? " · " + esc(info.wg) + " WG" : ""}${info.series.length ? " · part of " + info.series.join(", ") : ""} · <a href="https://www.rfc-editor.org/rfc/rfc${n}" target="_blank" rel="noopener">read it</a></div>`;
  if (Object.keys(shortest).length) {
    html += `<h3>Replaced by</h3><ul class="chains">` + Object.values(shortest).map((r) =>
      `<li>${r.chain.map((c, i) => i === r.chain.length - 1 ? `<b class="${r.kind === "retired" ? "dim" : "ok"}">${rfcLink(c)}</b>` : rfcLink(c)).join(' <span class="arrow">→</span> ')} ${esc(r.title)} <span class="dim">(${r.date}) · ${KIND_TEXT[r.kind]}</span></li>`).join("") + `</ul>`;
  }
  if (deps.length) html += `<h3>Partly deprecated by</h3><ul>` + deps.map((u) => `<li>${rfcLink(u.id)} ${esc(u.title)} <span class="dim">(${u.date})</span></li>`).join("") + `</ul>`;
  if (others.length) html += `<h3>Updated by ${others.length} document${others.length > 1 ? "s" : ""} still in force</h3><ul>` + others.slice(0, 10).map((u) => `<li>${rfcLink(u.id)} ${esc(u.title)} <span class="dim">(${u.date})</span></li>`).join("") + (others.length > 10 ? `<li class="dim">… ${others.length - 10} more</li>` : "") + `</ul>`;
  if (info.errata) html += `<p>${info.errata} verified technical errata · <a href="https://www.rfc-editor.org/errata/rfc${n}" target="_blank" rel="noopener">errata</a></p>`;
  if (secRows) {
    html += `<h3>Section ${esc(sec)} ${secRows[0] ? "· " + esc(secRows[0].was) : ""}</h3><ul class="chains">` + (secRows.length
      ? secRows.map((s) => `<li><b class="ok">${rfcLink(s.rfc)} §${esc(s.section)}</b> ${esc(s.title)}${s.exact ? "" : ' <span class="dim">(reworded heading)</span>'}</li>`).join("")
      : `<li class="dim">No section of the replacement has a matching heading; read its change log.</li>`) + `</ul><div class="q" id="q-sec"></div>`;
  }
  html += `<div class="q" id="q-info"></div></div>`;
  html += `<div class="card"><h3>Lineage</h3><p class="dim">OBSOLETES chains in both directions and live UPDATES. Click a node to open it.</p><div id="cy"></div><div class="legend"><span class="dot obsolete"></span>obsolete <span class="dot amended"></span>in force, amended <span class="dot ok"></span>in force <span class="line obs"></span>obsoletes <span class="line upd"></span>updates</div><div class="q" id="q-lineage"></div></div>`;
  html += `<div class="card" id="citing"></div>`;
  out.innerHTML = html;
  showQuery($("#q-info"), infoQuery);
  if (secQuery) showQuery($("#q-sec"), secQuery);
  await drawLineage(n, info.id, my);
  const cites = await cypher(Q.projectsCiting, { n });
  if (my !== renderSeq) return;
  const by = {};
  for (const c of cites) (by[c.project] ||= []).push(c);
  $("#citing").innerHTML = `<h3>Cited by ${Object.keys(by).length} of 26 scanned projects</h3>` + (cites.length ? `<ul>` + Object.entries(by).map(([p, cs]) =>
    `<li><b>${esc(p)}</b> ${cs.slice(0, 4).map((c) => ghLink(c.url, c.path, c.lines[0])).join(", ")}${cs.length > 4 ? ` <span class="dim">+${cs.length - 4} files</span>` : ""}</li>`).join("") + `</ul>` : `<p class="dim">none</p>`);
}

function ghLink(projectUrl, path, line) {
  // projectUrl: https://github.com/<repo>/tree/<commit>[/<sub>]
  const blob = projectUrl.replace("/tree/", "/blob/");
  return `<a href="${blob}/${path}#L${line}" target="_blank" rel="noopener"><code>${esc(path)}:${line}</code></a>`;
}

async function drawLineage(n, rootId, my) {
  const rows = await cypher(Q.lineage, { n });
  showQuery($("#q-lineage"));
  const edges = rows.filter((r) => r.a);
  const ids = [...new Set([rootId, ...edges.flatMap((r) => [r.a, r.b])])];
  const nodes = await cypher(Q.nodes, { ids });
  if (my !== renderSeq) return;
  const el = $("#cy");
  if (ids.length === 1) { el.innerHTML = `<p class="dim">No OBSOLETES or UPDATES relationships: this RFC stands alone.</p>`; el.style.height = "auto"; return; }
  el.style.height = Math.min(560, 160 + ids.length * 18) + "px";
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();
  cytoscape({
    container: el,
    elements: [
      ...nodes.map((x) => ({ data: { id: x.id, label: `${x.id}\n${x.date.slice(0, 4)}`, title: x.title, cls: x.obsolete ? "obsolete" : x.amended ? "amended" : "ok", root: x.id === rootId } })),
      ...edges.map((r, i) => ({ data: { id: "e" + i, source: r.a, target: r.b, type: r.type } })),
    ],
    layout: { name: "breadthfirst", directed: true, spacingFactor: 1.1, padding: 12 },
    style: [
      { selector: "node", style: { label: "data(label)", "text-wrap": "wrap", "text-valign": "center", "font-size": 10, color: "#fff", width: 64, height: 34, shape: "round-rectangle", "background-color": color("--ok") } },
      { selector: "node[cls = 'obsolete']", style: { "background-color": color("--bad") } },
      { selector: "node[cls = 'amended']", style: { "background-color": color("--warn") } },
      { selector: "node[?root]", style: { "border-width": 3, "border-color": color("--fg") } },
      { selector: "edge", style: { width: 1.6, "curve-style": "bezier", "target-arrow-shape": "triangle", "line-color": color("--muted"), "target-arrow-color": color("--muted") } },
      { selector: "edge[type = 'UPDATES']", style: { "line-style": "dashed", "line-color": color("--warn"), "target-arrow-color": color("--warn") } },
    ],
  }).on("tap", "node", (e) => check(e.target.id().replace("RFC", "")))
    .on("mouseover", "node", (e) => { el.title = e.target.data("title"); });
}

async function search(text) {
  const out = $("#check-out");
  const q = text.trim().split(/\s+/).filter(Boolean).map((w) => w.replace(/[^\p{L}\p{N}.-]/gu, "").toLowerCase()).filter(Boolean).join(" AND "); // lower case: AND/OR/NOT are operators
  if (!q) return;
  rendered = "q=" + text;
  if (decodeURIComponent(location.hash.slice(1)) !== rendered) location.hash = "q=" + encodeURIComponent(text);  // the hashchange handler skips it
  const my = ++renderSeq;
  const rows = await cypher(Q.search, { q });
  if (my !== renderSeq) return;
  out.innerHTML = `<div class="card"><h3>${rows.length} RFCs match “${esc(text)}”</h3><table><tr><th>RFC</th><th>title</th><th>date</th><th>status</th></tr>` +
    rows.map((r) => `<tr><td>${rfcLink(r.id)}</td><td>${esc(r.title)}</td><td>${r.date}</td><td>${r.obsolete ? badge("obsolete") : esc((r.status || "").toLowerCase())}</td></tr>`).join("") +
    `</table><div class="q" id="q-s"></div></div>`;
  showQuery($("#q-s"));
}

// ---------- scan tab ----------
const CITATION = /(?<![a-z0-9])rfc[ \t_#-]{0,2}(\d{1,5})(?!\d)/gi;
async function scanText() {
  const text = $("#code").value;
  const cites = [];
  text.split("\n").forEach((line, i) => {
    for (const m of line.matchAll(CITATION)) {
      const before = line.slice(0, m.index);
      if (/(message|text|x-)\/$/i.test(before)) continue;
      cites.push({ n: Number(m[1]), line: i + 1 });
    }
  });
  const ns = [...new Set(cites.map((c) => c.n))];
  const rows = await cypher(Q.judge, { ns });
  const byN = Object.fromEntries(rows.map((r) => [r.n, r]));
  const order = { obsolete: 0, historic: 1, "old-version": 2, amended: 3, ok: 4, unknown: 5 };
  const found = ns.map((n) => ({ n, r: byN[n] ?? null, lines: cites.filter((c) => c.n === n).map((c) => c.line) }))
    .map((x) => ({ ...x, lvl: level(x.r) })).sort((a, b) => order[a.lvl] - order[b.lvl]);
  const counts = {};
  found.forEach((f) => (counts[f.lvl] = (counts[f.lvl] || 0) + 1));
  $("#scan-out").innerHTML = `<div class="card"><p>${cites.length} citations of ${ns.length} RFCs · ${Object.entries(counts).map(([k, v]) => `${badge(k)} ${v}`).join(" ")}</p>
    <table><tr><th>status</th><th>RFC</th><th>title</th><th>replaced by / amended by</th><th>lines</th></tr>` +
    found.map((f) => `<tr><td>${badge(f.lvl)}</td><td>${f.r ? rfcLink(f.r.id) : "RFC" + f.n}</td><td>${esc(f.r?.title ?? "not in the RFC index")}</td><td>${f.r ? (f.r.current.length ? f.r.current.map(rfcLink).join(", ") : f.r.updates.slice(0, 4).map(rfcLink).join(", ")) : ""}</td><td>${f.lines.join(", ")}</td></tr>`).join("") +
    `</table><div class="q" id="q-scan"></div></div>`;
  showQuery($("#q-scan"));
}

// ---------- projects tab ----------
async function projects() {
  const rows = await cypher(Q.projects);
  const total = rows.reduce((a, r) => a + r.cites, 0), stale = rows.reduce((a, r) => a + r.stale, 0);
  $("#projects-out").innerHTML = `<div class="card"><p><b>${stale.toLocaleString()}</b> of <b>${total.toLocaleString()}</b> RFC citations (${Math.round(100 * stale / total)}%) in the source and docs of 26 projects point at an RFC that a newer edition has replaced (tests, identifiers and older protocol versions such as TLS 1.2 excluded). Click a project.</p>
  <table class="bars">` + rows.map((r) => `<tr data-p="${esc(r.name)}"><td><b>${esc(r.name)}</b><br><span class="dim">${esc(r.repo)}</span></td><td class="barcell"><div class="bar"><div style="width:${(100 * r.stale / Math.max(1, r.cites)).toFixed(1)}%"></div></div></td><td>${r.stale} / ${r.cites}</td></tr>`).join("") +
    `</table><div class="q" id="q-p"></div></div><div id="project-detail"></div>`;
  showQuery($("#q-p"));
  document.querySelectorAll("tr[data-p]").forEach((tr) => tr.onclick = () => project(tr.dataset.p, rows.find((r) => r.name === tr.dataset.p)));
}

async function project(name, meta) {
  const rows = await cypher(Q.projectStale, { name });
  const by = {};
  for (const r of rows) (by[r.id] ||= { ...r, files: [] }).files.push(r);
  $("#project-detail").innerHTML = `<div class="card"><h3>${esc(name)}: obsolete RFCs cited</h3><table><tr><th>RFC</th><th>replaced by</th><th>cited at (pinned commit)</th></tr>` +
    Object.values(by).map((x) => `<tr><td>${rfcLink(x.id)} <span class="dim">${esc(x.title)}</span></td><td>${x.current.map(rfcLink).join(", ")}</td><td>${x.files.slice(0, 5).map((f) => ghLink(meta.url, f.path, f.lines[0])).join("<br>")}${x.files.length > 5 ? `<br><span class="dim">+${x.files.length - 5} files</span>` : ""}</td></tr>`).join("") +
    `</table><div class="q" id="q-pd"></div></div>`;
  showQuery($("#q-pd"));
  $("#project-detail").scrollIntoView({ behavior: "smooth" });
}

// ---------- cypher tab ----------
const EXAMPLES = {
  "Longest replacement chains": `MATCH p = (old:RFC)<-[:OBSOLETES]-+(new:RFC)
WHERE NOT new.obsolete AND NOT EXISTS { (old)-[:OBSOLETES]->() }
RETURN length(p) AS hops, old.id, new.id, new.title ORDER BY hops DESC LIMIT 5`,
  "In-force RFCs citing obsolete ones": `MATCH (a:RFC)-[:NORMATIVE_REF]->(b:RFC) WHERE NOT a.obsolete AND b.obsolete
RETURN b.id, b.title, count(a) AS citedBy ORDER BY citedBy DESC LIMIT 10`,
  "Most-cited obsolete RFCs in the 26 projects": `MATCH (p:Project)-[:HAS_FILE]->(:File)-[c:CITES]->(r:RFC) WHERE r.obsolete AND NOT r.oldVersion
RETURN r.id, r.title, count(DISTINCT p) AS projects, sum(size(c.lines)) AS citations
ORDER BY projects DESC, citations DESC LIMIT 10`,
  "What TLS 1.3 must read": `MATCH (r:RFC {id: 'RFC9846'})-[:NORMATIVE_REF]->(d:RFC)
RETURN d.id, d.title, d.obsolete ORDER BY d.number`,
};
async function runCypher() {
  const out = $("#cypher-out");
  try {
    const rows = await cypher($("#cy-q").value, null, true);
    const cols = rows.length ? Object.keys(rows[0]) : [];
    out.innerHTML = `<p class="dim">${rows.length} rows · ${lastQuery.ms.toFixed(1)} ms</p><table><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>` +
      rows.slice(0, 500).map((r) => `<tr>${cols.map((c) => `<td>${esc(typeof r[c] === "object" ? JSON.stringify(r[c]) : r[c])}</td>`).join("")}</tr>`).join("") + `</table>`;
  } catch (err) {
    out.innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
}

// ---------- routing ----------
function tab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("section.tab").forEach((s) => (s.hidden = s.id !== name));
}
function route() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (h.startsWith("rfc=")) { tab("check"); check(h.slice(4).replace("&s=", "#")); }
  else if (h.startsWith("q=")) { tab("check"); $("#q").value = h.slice(2); search(h.slice(2)); }
  else if (h === "scan") { tab("scan"); scanText(); }
  else if (h === "projects") { tab("projects"); projects(); }
  else if (h === "cypher") { tab("cypher"); }
  else { tab("check"); check("8446"); }
}
let rendered = "";
window.addEventListener("hashchange", () => document.body.classList.contains("ready") && decodeURIComponent(location.hash.slice(1)) !== rendered && route());
document.querySelectorAll("nav button").forEach((b) => (b.onclick = () => {
  if (b.dataset.tab === "check") location.hash = "rfc=" + ($("#q").value.match(/\d+/)?.[0] ?? "8446");
  else location.hash = b.dataset.tab;
}));
$("#check-form").onsubmit = (e) => { e.preventDefault(); check($("#q").value); };
$("#scan-btn").onclick = scanText;
$("#cy-run").onclick = runCypher;
$("#cy-q").onkeydown = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runCypher(); };
const ex = $("#examples");
for (const [k, v] of Object.entries(EXAMPLES)) {
  const b = document.createElement("button");
  b.textContent = k;
  b.onclick = () => { $("#cy-q").value = v; runCypher(); };
  ex.appendChild(b);
}
$("#cy-q").value = EXAMPLES["Longest replacement chains"];
