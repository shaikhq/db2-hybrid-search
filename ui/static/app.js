"use strict";

// Search tab = open-ended search: type anything, see the top 3 results from all
// three strategies side by side. Needs the live backend (./ui/run.sh --live) since
// arbitrary queries must hit Db2. The Golden-eval tab reads the frozen eval_set.json.

const state = { showScores: false, explain: false,
                rerank: false, record: null, recordFusion: null };
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
// Rerank and the leg toggles are competing VIEW selectors; keep state + UI in sync.
function setRerank(on) {
  state.rerank = on;
  $("#btn-rerank").setAttribute("aria-pressed", String(on));
}
// Searching a new query (Search button or Enter) is always a plain search. Rerank
// is an explicit, per-query action — it never rides along on a fresh query, so we
// clear it here. Leg toggles persist (you may want to keep comparing legs).
const PLACEHOLDER = `<p class="placeholder">Type a query and hit Search to see the top 3 Hybrid results.</p>`;
function newSearch() {
  setRerank(false);
  run();
}
// Reset the Search tab to its opening state: empty box, no view/modifier selected.
function resetAll() {
  $("#searchbox").value = "";
  setRerank(false);
  state.explain = false;    $("#t-explain").checked = false;
  state.showScores = false; $("#t-scores").checked = false;
  state.record = null; state.recordFusion = null;
  $("#output").innerHTML = PLACEHOLDER;
  $("#searchbox").focus();
}

function wire() {
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab"); if (!t) return;
    setPage(t.dataset.page);
  });
  $("#eval-list").addEventListener("click", (e) => {
    const gp = e.target.closest(".gold-passage"); if (gp) gp.classList.toggle("open");
  });
  $("#run").addEventListener("click", newSearch);
  $("#searchbox").addEventListener("keydown", (e) => { if (e.key === "Enter") newSearch(); });
  $("#btn-reset").addEventListener("click", resetAll);
  // Explain / Show scores are display MODIFIERS: they annotate whichever view is
  // showing (leg comparison, plain Hybrid, or the Rerank comparison). They never
  // switch views, so they don't touch Rerank — just re-render.
  $("#t-scores").addEventListener("change", (e) => {
    state.showScores = e.target.checked; if (state.record) render();
  });
  $("#t-explain").addEventListener("change", (e) => {
    state.explain = e.target.checked; if (state.record) render();
  });
  $("#btn-rerank").addEventListener("click", () => {
    setRerank(!state.rerank);
    if (state.record) run();                     // re-search (fetches both orderings when on)
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
  const enc = encodeURIComponent(text);
  try {
    if (state.rerank) {
      // Re-rank pressed: fetch both orderings so we can show Hybrid vs Hybrid reranked
      const [rr, fu] = await Promise.all([
        fetch(`/api/search?q=${enc}&rerank=1`).then((r) => { if (!r.ok) throw 0; return r.json(); }),
        fetch(`/api/search?q=${enc}&rerank=0`).then((r) => { if (!r.ok) throw 0; return r.json(); }),
      ]);
      // Reranker requested but its server was unreachable: report it, don't silently
      // show the un-reranked fusion order as if it were reranked.
      if (rr.rerank_unavailable) {
        $("#output").innerHTML = `<p class="placeholder rerank-err">
          <b>Reranker is not available.</b> The reranker server (<code>:8087</code>) isn't
          reachable, so results were not reranked. Start it with
          <code>./scripts/0_start-services.sh</code> (needs the bge-reranker model — see
          the README), then click Rerank again.</p>`;
        setRerank(false);                 // reflect that reranking did not happen
        state.record = null; state.recordFusion = null;
        return;
      }
      state.record = rr; state.recordFusion = fu;
    } else {
      const r = await fetch(`/api/search?q=${enc}&rerank=0`);
      if (!r.ok) throw new Error("bad status");
      state.record = await r.json(); state.recordFusion = null;
    }
    render();
  } catch (_) {
    $("#output").innerHTML = `<p class="placeholder">Search failed — is the live backend running?</p>`;
    state.record = null;
  }
}

function render() {
  const rec = state.record;
  if (!rec) return;
  let html;
  if (state.rerank && state.recordFusion) html = compareHtml(state.recordFusion, rec);   // Re-rank: Hybrid vs Hybrid reranked
  else html = hybridHtml(rec);
  $("#output").innerHTML = html;
  markClamped($("#output"));
}

// A description longer than its 3-line clamp gets a "Show more" affordance; a short
// one that fits doesn't. Measured after layout (scrollHeight vs clientHeight) so the
// cue only appears when there's genuinely more to reveal. Clicking the card (existing
// #output handler toggles .open) un-clamps it.
function markClamped(root) {
  root.querySelectorAll(".row").forEach((row) => {
    const d = row.querySelector(".rdesc");
    if (d && d.scrollHeight - d.clientHeight > 2) row.classList.add("clamped");
  });
}

// The keyword leg searches your query minus English stopwords (core.keywords()).
// Surface that ONLY when it actually differs from what you typed — i.e. stopwords
// were dropped — so a filler-free query shows no redundant note. Explain-gated.
function lexNoteHtml(lexq, fullq) {
  const a = (lexq || "").trim(), b = (fullq || "").trim();
  if (!state.explain || !a || a.toLowerCase() === b.toLowerCase()) return "";
  return `<p class="lex-note">Keyword leg searched <code>${esc(a)}</code>
    <span>· stopwords dropped; semantic leg uses your full query</span></p>`;
}

// The book's cover thumbnail (path from Db2, served under ui/static/). Falls back
// to a neutral placeholder when a book has no cover or the image fails to load.
function coverImg(r) {
  return r && r.cover
    ? `<img class="cover" src="${esc(r.cover)}" alt="" loading="lazy"
         onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'cover cover-missing'}))">`
    : `<span class="cover cover-missing" aria-hidden="true"></span>`;
}

// A search-result card: cover on the left; title, author, and description on the
// right. The description shows by default (click the card to un-clamp it in full).
// `extra` slots in provenance / rank-delta for the hybrid legs. Falls back to
// snippet/text so any fixture predating the structured fields still renders.
function resultCard(r, hl, extra) {
  const title = r.title || r.snippet || "";
  const desc = r.description || r.text || "";
  return `<div class="row">
    ${coverImg(r)}
    <div class="rbody">
      <div class="rline"><span class="rank">${r.rank}</span><span class="rtitle">${highlight(esc(title), hl)}</span></div>
      ${r.author ? `<div class="rby">by ${esc(r.author)}</div>` : ""}
      ${desc ? `<div class="rdesc">${highlight(esc(desc), hl)}</div><span class="rmore" aria-hidden="true"></span>` : ""}
      ${extra || ""}
      ${scoresHtml(r)}
    </div>
  </div>`;
}

// Rerank vs fusion, side by side — same query, two orderings of the same candidates.
function compareHtml(fu, rr) {
  const lexq = (rr.lexical && rr.lexical.lex_query) || (fu.lexical && fu.lexical.lex_query);
  const terms = queryTerms(lexq || rr.query);
  const lexNote = lexNoteHtml(lexq, rr.query);
  const fuAll = (fu.hybrid && fu.hybrid.results) || [];
  const fuTop = fuAll.slice(0, TOP);
  const rrTop = ((rr.hybrid && rr.hybrid.results) || []).slice(0, TOP);
  const fusionRankById = {};
  fuAll.forEach((r, i) => { fusionRankById[r.chunk_id] = i + 1; });   // fusion rank of each candidate
  const col = (title, rows, ranks) => `
    <div class="cmp-col">
      <h3 class="results-h"><span class="dot hyb"></span>${title}</h3>
      <div class="rows">${rows.map((r) => hybRowHtml(r, terms, ranks)).join("")}</div>
    </div>`;
  return `${lexNote}
    <div class="cmp-grid">
      ${col("Hybrid", fuTop, null)}
      ${col("Hybrid · reranked", rrTop, fusionRankById)}
    </div>${scoreNote()}`;
}

// Search tab shows only the Hybrid top-3. Each result is annotated with which
// strategy found it and at what rank within that strategy.
function hybridHtml(rec) {
  // highlight the keyword terms the lexical leg actually searched (stopwords dropped)
  const lexq = rec.lexical && rec.lexical.lex_query;
  const lexNote = lexNoteHtml(lexq, rec.query);
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

function hybRowHtml(r, hl, fusionRankById) {
  // Explain OFF (default): just rank + result. ON: per-leg provenance + rank-delta labels.
  let delta = "";
  if (state.explain && fusionRankById) {   // reranked compare column: how it moved vs fusion
    const fr = fusionRankById[r.chunk_id];
    if (fr == null)        delta = `<span class="delta up">↑ promoted from the fusion pool</span>`;
    else if (fr > r.rank)  delta = `<span class="delta up">↑ fusion #${fr} → #${r.rank}</span>`;
    else if (fr < r.rank)  delta = `<span class="delta down">↓ fusion #${fr} → #${r.rank}</span>`;
    else                   delta = `<span class="delta same">unchanged · #${fr}</span>`;
  }
  return resultCard(r, hl, `${state.explain ? provenanceHtml(r) : ""}${delta}`);
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
