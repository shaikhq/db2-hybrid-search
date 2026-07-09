"use strict";
/* Architecture tab — static, diagrammatic views for a technical audience.
   No data dependencies: the diagrams are drawn from the verified system
   (1_ingest.sql, hybrid_search.core, qu_gate.sql). Dark navy flat style —
   flat fills, no gradients/shadows/icons. Three views via a sub-nav.

   Verified facts encoded here (Phase 0):
     - Db2 does vector storage/index/similarity, BM25 text search, and the SQL
       model callout (TO_EMBEDDING active; TEXT_GENERATION built but off).
     - Text search is backed by OpenSearch; embedding/generation run on local serving.
     - Fusion is a gated, score-normalized weighted sum (NOT reciprocal-rank fusion).
     - Corpus is one row per audiobook (no doc extraction / chunking).
*/

const ARCH = { view: "component" };
const aq = (s) => document.querySelector(s);

/* ---------- shared pieces ---------- */
// vertical bidirectional connector with a caption
function vconn(label) {
  return `<div class="aconn">
    <svg width="22" height="42" viewBox="0 0 22 42" aria-hidden="true">
      <line x1="11" y1="7" x2="11" y2="35" stroke="#5b6488" stroke-width="1.5" />
      <path d="M11 2 l4 7 h-8 z" fill="#5b6488" />
      <path d="M11 40 l4 -7 h-8 z" fill="#5b6488" />
    </svg>${label ? `<span class="aconn-label">${label}</span>` : ""}</div>`;
}

// a single numbered step box
function stepbox(n, h, sub, cls) {
  return `<div class="step ${cls || ""}">
    <div class="step-n">STEP ${n}</div>
    <div class="step-h">${h}</div>
    <div class="step-s">${sub}</div></div>`;
}
// a flow arrow, optionally labelled (used for the search-funnel counts)
function arrow(label) {
  return `<div class="step-arrow" aria-hidden="true"><span>&rarr;</span>${label ? `<em>${label}</em>` : ""}</div>`;
}
// a horizontal run of numbered step boxes joined by plain arrows
function stepboxes(steps) {
  return steps.map((s, i) => stepbox(s[0], s[1], s[2], s[3]) + (i < steps.length - 1 ? arrow() : "")).join("");
}

function archLegend() {
  return `<div class="arch-legend" aria-label="legend">
    <span><i class="swatch" style="border-color:#3b82f6;background:#12183a"></i> used by this app</span>
    <span><i class="swatch" style="border-color:#23263f;background:#0d0f22"></i> Db2 capability &mdash; unused headroom</span>
    <span><i class="swatch" style="border-color:#E8552B"></i> lexical / text search</span>
    <span><i class="swatch" style="border-color:#2dd4bf"></i> semantic / vector</span>
    <span><i class="swatch" style="border-color:#a78bfa"></i> hybrid / fusion</span>
    <span><i class="swatch" style="border-color:#f2a541"></i> reranker (cross-encoder)</span>
  </div>`;
}

function archNotes(items) {
  return `<div class="arch-notes"><h4>Notes</h4><ul>${
    items.map(([k, v]) => `<li><b>${k}:</b> ${v}</li>`).join("")}</ul></div>`;
}

/* ---------- view 1: components ---------- */
function archComponentView() {
  return `
  <div class="arch-thesis">Normally: a vector database + a search cluster + an orchestration service.
    Here: <b>one Db2 database, one SQL surface.</b></div>
  <figure class="arch-fig">
    <div class="arch-layer">
      <div class="abox abox-ui">
        <div class="abox-h">UI &middot; search box</div>
        <div class="abox-s">browser</div>
      </div>
    </div>
    ${vconn("query &darr; &middot; results &uarr;")}
    <div class="arch-db2">
      <div class="arch-db2-h">Db2 12.1.5 &mdash; retrieval + fusion in SQL</div>
      <div class="arch-caps">
        <div class="cap cap-used cap-vec">Vector storage<span>VECTOR(384)</span></div>
        <div class="cap cap-used cap-vec">Vector index &mdash; ANN<span>COSINE</span></div>
        <div class="cap cap-used cap-vec">Similarity search<span>VECTOR_DISTANCE</span></div>
        <div class="cap cap-used cap-text">Text search &mdash; BM25<span>CONTAINS &middot; SCORE</span></div>
        <div class="cap cap-used cap-callout">Model callout (SQL)
          <div class="cap-sub">
            <span class="on">&#9679; TO_EMBEDDING &mdash; used</span>
            <span class="avail">TEXT_GENERATION &mdash; available</span>
          </div>
        </div>
        <div class="cap cap-muted">SQL / relational</div>
        <div class="cap cap-muted">Transactions &middot; SQL&nbsp;PL</div>
      </div>
    </div>
    ${vconn("external services")}
    <div class="arch-deps">
      <div class="abox abox-serve">
        <div class="abox-h">Local model serving</div>
        <div class="abox-s">local llama.cpp servers</div>
        <div class="serve-models">
          <span class="mini mini-emb">embedding &middot; bge-small-en-v1.5</span>
          <span class="mini mini-gen">text generation &middot; Qwen2.5-3B-Instruct</span>
          <span class="mini mini-rr">reranker &middot; bge-reranker-v2-m3</span>
        </div>
      </div>
      <div class="abox abox-os">
        <div class="abox-h">OpenSearch</div>
        <div class="abox-s">backs Db2 Text Search</div>
      </div>
    </div>
  </figure>
  ${archLegend()}
  ${archNotes([
    ["Model calls", "embedding &amp; generation via Db2 SQL callout; reranker from the app layer."],
    ["Batch embedding", "whole corpus embedded in one UPDATE."],
  ])}`;
}

/* ---------- view 2: ingestion ---------- */
function archIngestView() {
  const prep = [
    ["1", "Export", "audible-cli (region ca)"],
    ["2", "Enrich", "Audnexus, by ASIN"],
    ["3", "Compose text", "&rarr; data/corpus.csv"],
    ["4", "Import", "one row per book"],
  ];
  const build = [
    ["5", "Text index", "&rarr; OpenSearch", "text"],
    ["6", "Batch embed", "TO_EMBEDDING, all rows", "vec"],
    ["7", "Store vectors", "VECTOR(384)", "vec"],
    ["8", "Vector index", "COSINE &middot; read-only after", "vec"],
  ];
  return `<figure class="arch-fig">
    <div class="arch-rowgroup">
      <div class="arch-rowlabel">A &middot; Corpus preparation</div>
      <div class="arch-flow">${stepboxes(prep)}</div>
    </div>
    <div class="arch-rowgroup">
      <div class="arch-rowlabel">B &middot; Build indexes in Db2 &mdash; text index (BM25) and the vector (ANN) index</div>
      <div class="arch-flow">${stepboxes(build)}</div>
    </div>
  </figure>
  ${archLegend()}
  ${archNotes([
    ["Batch embedding", "step 6 embeds all rows in one UPDATE."],
    ["ANN build-and-swap", "vector index built last; table read-only after."],
  ])}`;
}

/* ---------- view 3: search (hybrid) — the full funnel ---------- */
function archSearchView() {
  // two retrieval legs, each over the full candidate pool, fused into one ranking
  const branch = `<div class="step-branch">
    <div class="step text"><div class="step-n">STEP 3a</div><div class="step-h">Lexical</div>
      <div class="step-s">BM25 &middot; full pool</div></div>
    <div class="step vec"><div class="step-n">STEP 3b</div><div class="step-h">Semantic</div>
      <div class="step-s">vector &middot; full pool</div></div>
  </div>`;
  const flow = [
    stepbox("1", "Query", "from the UI"),
    arrow(),
    stepbox("2", "Clean (SQL)", "keep rare words"),
    arrow(),
    branch,
    arrow("full pool"),
    stepbox("4", "Fuse", "gated weighted sum &middot; not RRF", "fuse"),
    arrow("top 20"),
    stepbox("5", "Rerank", "cross-encoder &middot; optional", "rerank"),
    arrow("top 3"),
    stepbox("6", "Results", "shown in the UI"),
  ].join("");
  return `<figure class="arch-fig"><div class="arch-flow">${flow}</div></figure>
  ${archLegend()}
  ${archNotes([
    ["Funnel", "both legs (full pool) &rarr; fuse &rarr; top 20 to the reranker &rarr; top 3 shown."],
    ["Rerank", "app-layer cross-encoder on top of Db2 fusion; optional (toggle)."],
  ])}`;
}

/* ---------- render + wire ---------- */
const VIEWS = { component: archComponentView, ingest: archIngestView, search: archSearchView };

function renderArch() {
  const host = aq("#arch-canvas");
  if (!host) return;
  host.innerHTML = (VIEWS[ARCH.view] || archComponentView)();
  document.querySelectorAll("#arch-subnav button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.view === ARCH.view)));
}

function archWire() {
  const nav = aq("#arch-subnav");
  if (!nav) return;
  nav.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (!b) return;
    ARCH.view = b.dataset.view;
    renderArch();
  });
}

function archBoot() {
  if (!aq("#page-arch")) return;
  archWire();
  renderArch();
}

archBoot();
