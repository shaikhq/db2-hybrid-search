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

// a horizontal run of numbered step boxes joined by arrows
function stepboxes(steps) {
  return steps.map((s, i) => {
    const [n, h, sub, cls] = s;
    const box = `<div class="step ${cls || ""}">
      <div class="step-n">STEP ${n}</div>
      <div class="step-h">${h}</div>
      <div class="step-s">${sub}</div></div>`;
    return box + (i < steps.length - 1 ? `<div class="step-arrow" aria-hidden="true">&rarr;</div>` : "");
  }).join("");
}

function archLegend() {
  return `<div class="arch-legend" aria-label="legend">
    <span><i class="swatch" style="border-color:#3b82f6;background:#12183a"></i> used by this app</span>
    <span><i class="swatch" style="border-color:#23263f;background:#0d0f22"></i> Db2 capability &mdash; unused headroom</span>
    <span><i class="swatch" style="border-color:#E8552B"></i> lexical / text search</span>
    <span><i class="swatch" style="border-color:#2dd4bf"></i> semantic / vector</span>
    <span><i class="swatch" style="border-color:#a78bfa"></i> hybrid / fusion</span>
    <span><i class="swatch" style="border-style:dashed;border-color:#8790b0"></i> built, off by default</span>
  </div>`;
}

function archNotes(items) {
  return `<div class="arch-notes"><h4>Performance notes</h4><ul>${
    items.map(([k, v]) => `<li><b>${k}:</b> ${v}</li>`).join("")}</ul></div>`;
}

/* ---------- view 1: components ---------- */
function archComponentView() {
  return `
  <div class="arch-thesis">Typically this takes <b>three</b> systems &mdash; a vector database, a search
    cluster, and an orchestration service. Here it collapses into <b>one Db2 database on one SQL surface</b>.
    The single external dependency is local model serving; OpenSearch is a supporting text-search backend.</div>
  <figure class="arch-fig">
    <div class="arch-layer">
      <div class="abox abox-ui">
        <div class="abox-h">UI &middot; search box</div>
        <div class="abox-s">entry client (browser)</div>
      </div>
    </div>
    ${vconn("query &darr; &nbsp; ranked results &uarr;")}
    <div class="arch-db2">
      <div class="arch-db2-h">Db2 12.1.5 &mdash; retrieval + fusion orchestration implemented in SQL</div>
      <div class="arch-caps">
        <div class="cap cap-used cap-vec">Vector storage<span>VECTOR(384, FLOAT32) column</span></div>
        <div class="cap cap-used cap-vec">Vector index &mdash; ANN<span>CREATE VECTOR INDEX &middot; COSINE</span></div>
        <div class="cap cap-used cap-vec">Similarity search<span>VECTOR_DISTANCE &middot; FETCH APPROX</span></div>
        <div class="cap cap-used cap-text">Text search &mdash; BM25<span>CONTAINS &middot; SCORE</span></div>
        <div class="cap cap-used cap-callout">Language-model callout (SQL)
          <div class="cap-sub">
            <span class="on">&#9679; TO_EMBEDDING &mdash; active</span>
            <span class="off">&#9675; TEXT_GENERATION &mdash; available, off by default</span>
          </div>
        </div>
        <div class="cap cap-muted">SQL / relational engine</div>
        <div class="cap cap-muted">Transactions &middot; SQL&nbsp;PL</div>
        <div class="cap cap-muted">JSON &middot; temporal &middot; federation &hellip;</div>
      </div>
    </div>
    ${vconn("external dependencies")}
    <div class="arch-deps">
      <div class="abox abox-serve">
        <div class="abox-h">Local model serving</div>
        <div class="abox-s">reached through the SQL model callout (OpenAI-compatible endpoint)</div>
        <div class="serve-models">
          <span class="mini mini-emb">embedding model &middot; 384-dim</span>
          <span class="mini mini-off">text-generation model &middot; off by default</span>
        </div>
      </div>
      <div class="abox abox-os">
        <div class="abox-h">OpenSearch</div>
        <div class="abox-s">backend engine for Db2 Text&nbsp;Search (BM25)</div>
      </div>
    </div>
  </figure>
  ${archLegend()}
  ${archNotes([
    ["Batch embedding", "Ingestion embeds every row in one set-based pass (a single UPDATE &hellip; TO_EMBEDDING over the table)."],
    ["ANN index", "The vector index serves similarity by approximate nearest-neighbour (FETCH APPROX), not a full scan."],
  ])}`;
}

/* ---------- view 2: ingestion ---------- */
function archIngestView() {
  const prep = [
    ["1", "Export", "Audible library via audible-cli (region ca)"],
    ["2", "Enrich", "Audnexus metadata, joined by ASIN"],
    ["3", "Compose text", "per book: &ldquo;{title} by {authors}. Narrated by {narrators}. {desc}&rdquo; &rarr; data/corpus.csv"],
    ["4", "Import", "IMPORT into Db2 &mdash; one row per audiobook"],
  ];
  const build = [
    ["5", "Text index", "Db2 Text Search (SYSTS_CREATE / SYSTS_UPDATE) &rarr; OpenSearch", "text"],
    ["6", "Batch embed", "UPDATE &hellip; TO_EMBEDDING(chunk_text) &rarr; local serving (all rows)", "vec"],
    ["7", "Store vectors", "VECTOR(384, FLOAT32) column", "vec"],
    ["8", "Vector index", "CREATE VECTOR INDEX &middot; COSINE &mdash; makes the table read-only", "vec"],
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
    ["Batch embedding generation", "Step&nbsp;6 embeds the whole corpus in a single set-based UPDATE, not row by row."],
    ["ANN index build-and-swap", "Step&nbsp;8 builds the vector index last; once built the table is read-only, so adding books means rebuilding the index."],
  ])}`;
}

/* ---------- view 3: search (hybrid) ---------- */
function archSearchView() {
  const pre = [
    ["1", "Query", "user types in the UI search box"],
    ["2", "Clean (SQL)", "QU_LEXICAL &mdash; strip filler / stopwords, keep the rare words"],
    ["3", "To Db2", "one SQL statement carries the query"],
  ];
  const post = [
    ["5", "Fuse", "gated, score-normalized weighted sum of the two legs &mdash; not RRF", "fuse"],
    ["6", "Results", "ranked hybrid list &rarr; UI"],
  ];
  const branch = `<div class="step-branch">
    <div class="step text"><div class="step-n">STEP 4a</div><div class="step-h">Lexical</div>
      <div class="step-s">text search &middot; BM25 (CONTAINS &middot; SCORE)</div></div>
    <div class="step vec"><div class="step-n">STEP 4b</div><div class="step-h">Semantic</div>
      <div class="step-s">vector similarity (VECTOR_DISTANCE &middot; COSINE &middot; FETCH APPROX)</div></div>
  </div>`;
  return `<figure class="arch-fig"><div class="arch-flow">
    ${stepboxes(pre)}<div class="step-arrow" aria-hidden="true">&rarr;</div>${branch}<div class="step-arrow" aria-hidden="true">&rarr;</div>${stepboxes(post)}
  </div></figure>
  ${archLegend()}
  ${archNotes([
    ["Fusion method", "Each leg is max-normalized; a low-confidence leg is gated out; the survivors combine as W_LEX&middot;lex + W_VEC&middot;vec. Deliberately <b>not</b> reciprocal-rank fusion (which discards each leg&rsquo;s real score)."],
    ["ANN index", "The semantic leg (4b) uses the vector index via FETCH APPROX for fast approximate similarity."],
    ["SQL query cleaning", "Step&nbsp;2 is deterministic SQL (no model) &mdash; it focuses the lexical leg on rare, meaningful tokens."],
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
