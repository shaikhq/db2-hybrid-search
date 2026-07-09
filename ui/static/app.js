"use strict";

// Search tab = open-ended search: type anything, see the top 3 results from all
// three strategies side by side. Needs the live backend (./ui/run.sh --live) since
// arbitrary queries must hit Db2. The Golden-eval tab reads the frozen eval_set.json.

const state = { showScores: false, rerank: false, record: null };
let LIVE = false;      // /api/search reachable (live backend up)?
let EVAL = null;       // eval_set.json (featured queries + their gold answers)

const TOP = 3;         // results shown per strategy
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const TYPE_LABEL = { keyword: "Lexical", semantic: "Semantic", mixed: "Mixed" };
const legChip = (leg) => leg === "bm25"
  ? '<span class="chip chip-bm25">Lexical</span>'
  : '<span class="chip chip-vector">Semantic</span>';

// Highlight the query's terms inside an already-escaped chunk (lexical results).
const HL_STOP = new Set(("the a an of to in on and or for with your you how what is are do it this that " +
  "by we our not into out up who i be book books looking find need want about one").split(" "));
function queryTerms(q) {
  return [...new Set(String(q || "").toLowerCase().match(/[a-z0-9]+/g) || [])]
    .filter((w) => w.length > 2 && !HL_STOP.has(w));
}
function highlight(escaped, terms) {
  if (!terms || !terms.length) return escaped;
  const re = new RegExp("(" + terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  return escaped.replace(re, "<mark>$1</mark>");
}

/* ---------- boot ---------- */
async function boot() {
  try { LIVE = (await fetch("/api/queries", { cache: "no-store" })).ok; }
  catch (_) { LIVE = false; }
  try { EVAL = await (await fetch("eval_set.json", { cache: "no-store" })).json(); }
  catch (_) { EVAL = null; }
  renderEval();
  wire();
}

/* ---------- golden eval set page ---------- */
function renderEval() {
  const host = $("#eval-list");
  if (!host) return;
  if (!EVAL || !EVAL.queries || !EVAL.queries.length) {
    host.innerHTML = `<p class="placeholder">No eval set found —
      run <code>./ui/build_eval_set.sh</code> to generate it.</p>`;
    return;
  }
  host.innerHTML = EVAL.queries.map((q, i) => {
    const type = TYPE_LABEL[q.query_type] || q.query_type;
    const n = q.gold.length;
    const passages = q.gold.map((g) => {
      const preview = String(g.text).replace(/\s+/g, " ").trim();
      return `
      <div class="gold-passage" title="Click to expand">
        <span class="cid">#${g.chunk_id}</span>
        <div class="gp-body">
          <span class="snip">${esc(preview)}</span>
          <div class="full">${esc(g.text)}</div>
        </div>
        <span class="gp-caret" aria-hidden="true">▸</span>
      </div>`;
    }).join("");
    return `<article class="eval-card">
      <div class="eval-q">
        <span class="qnum">${i + 1}</span>
        <span class="qtext">${esc(q.query)}</span>
        <span class="type type-${q.query_type}">${type}</span>
      </div>
      ${q.note ? `<p class="eval-why">${esc(q.note)}</p>` : ""}
      <div class="eval-gold-head">Gold answer${n > 1 ? "s" : ""}
        <span>· the book${n > 1 ? "s" : ""} search should find</span></div>
      ${passages}
    </article>`;
  }).join("");
}

/* ---------- nav ---------- */
function setPage(page) {
  document.querySelectorAll("#tabs .tab").forEach((t) =>
    t.setAttribute("aria-selected", String(t.dataset.page === page)));
  // Generic: show #page-<page>, hide the rest. Force display too, so hiding works
  // even if an older/cached stylesheet lacks the [hidden] override.
  document.querySelectorAll('[id^="page-"]').forEach((sec) => {
    const on = sec.id === "page-" + page;
    sec.hidden = !on;
    sec.style.display = on ? "" : "none";
  });
}

/* ---------- controls ---------- */
function wire() {
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab"); if (!t) return;
    setPage(t.dataset.page);
  });
  $("#eval-list").addEventListener("click", (e) => {
    const gp = e.target.closest(".gold-passage"); if (gp) gp.classList.toggle("open");
  });
  $("#run").addEventListener("click", run);
  $("#searchbox").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  $("#t-scores").addEventListener("change", (e) => {
    state.showScores = e.target.checked; if (state.record) render();
  });
  $("#t-rerank").addEventListener("change", (e) => {
    state.rerank = e.target.checked; if (state.record) run();   // re-search with the new setting
  });
  $("#output").addEventListener("click", (e) => {
    const row = e.target.closest(".row"); if (row) row.classList.toggle("open");
  });
}

/* ---------- run + render ---------- */
async function run() {
  const text = $("#searchbox").value.trim();
  if (!text) return;
  if (!LIVE) {
    $("#output").innerHTML = `<p class="placeholder">Open-ended search needs the live backend —
      run <code>./ui/run.sh --live</code>, then search any query here.</p>`;
    state.record = null; return;
  }
  $("#output").innerHTML = `<p class="placeholder">Searching…</p>`;
  try {
    const r = await fetch("/api/search?q=" + encodeURIComponent(text) + "&rerank=" + (state.rerank ? "1" : "0"));
    if (!r.ok) throw new Error("bad status");
    state.record = await r.json();
    render();
  } catch (_) {
    $("#output").innerHTML = `<p class="placeholder">Search failed — is the live backend running?</p>`;
    state.record = null;
  }
}

function render() {
  const rec = state.record;
  if (!rec) return;
  $("#output").innerHTML = hybridHtml(rec);
}

// Search tab shows only the Hybrid top-3. Each result is annotated with which
// strategy found it and at what rank within that strategy.
function hybridHtml(rec) {
  // highlight the cleaned rare-word terms the lexical leg actually searched
  const lexq = rec.lexical && rec.lexical.lex_query;
  const lexNote = lexq
    ? `<p class="lex-note">Lexical leg searched <code>${esc(lexq)}</code>
         <span>· semantic leg uses your full query</span></p>`
    : "";
  const terms = queryTerms(lexq || rec.query);
  const results = ((rec.hybrid && rec.hybrid.results) || []).slice(0, TOP);
  if (!results.length) return lexNote + `<p class="placeholder">No results.</p>`;
  const tag = rec.reranked ? ` <span class="rerank-tag">reranked</span>` : "";
  return `${lexNote}<h3 class="results-h"><span class="dot hyb"></span>Top ${results.length} · Hybrid${tag}</h3>
    <div class="rows">${results.map((r) => hybRowHtml(r, terms)).join("")}</div>${scoreNote()}`;
}

// "found by Lexical (rank N) · Semantic (rank M)" — the ranks are each strategy's
// own ranking of this result (a strategy is listed only if it surfaced it).
function provenanceHtml(r) {
  const pl = r.per_leg || {};
  const legs = [];
  if (pl.bm25 && pl.bm25.rank != null)
    legs.push(`<span class="chip chip-bm25">Lexical &middot; rank ${pl.bm25.rank}${pl.bm25.gated ? " &middot; gated" : ""}</span>`);
  if (pl.vector && pl.vector.rank != null)
    legs.push(`<span class="chip chip-vector">Semantic &middot; rank ${pl.vector.rank}${pl.vector.gated ? " &middot; gated" : ""}</span>`);
  if (!legs.length) return "";
  return `<div class="prov"><span class="prov-label">found by</span>${legs.join("")}</div>`;
}

function hybRowHtml(r, hl) {
  return `<div class="row">
    <div class="rline">
      <span class="rank">${r.rank}</span>
      <span class="snip">${highlight(esc(r.snippet), hl)}</span>
    </div>
    ${provenanceHtml(r)}
    ${scoresHtml(r)}
    <div class="full">${highlight(esc(r.text), hl)}</div>
  </div>`;
}

function scoresHtml(r) {
  if (!state.showScores) return "";
  const parts = [];
  if (r.score_type === "bm25") parts.push(`Lexical <b>${r.score}</b>`);
  else if (r.score_type === "cosine") parts.push(`Semantic <b>${r.score}</b>`);
  else {
    parts.push(`${r.score_type === "rerank" ? "rerank" : "fused"} <b>${r.score}</b>`);
    if (r.per_leg) {
      const b = r.per_leg.bm25, v = r.per_leg.vector;
      parts.push(`Lexical${b.gated ? " (gated)" : ""} raw ${b.score ?? "—"} · norm ${b.norm} → +${r.contribution.bm25}`);
      parts.push(`Semantic${v.gated ? " (gated)" : ""} raw ${v.score ?? "—"} · norm ${v.norm} → +${r.contribution.vector}`);
    }
  }
  return `<div class="scores">${parts.map((p) => `<span>${p}</span>`).join("")}</div>`;
}

function scoreNote() {
  if (!state.showScores) return "";
  return `<p class="score-note">The Lexical and Semantic scores are on different scales, so each leg is
    normalized (score ÷ its best) and a low-confidence leg is gated out before the weighted sum.
    The fusion ranks by normalized score, not raw score.</p>`;
}

boot();
