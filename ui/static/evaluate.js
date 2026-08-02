"use strict";

// Evaluate tab — score a named test set across the three Db2 legs.
//
// This file computes NO metrics. Everything numeric comes from /api/evaluate, which uses
// hybrid_search.metrics — the same functions scripts/eval.py imports. The repo already
// grew three copies of nDCG that drifted apart; a fourth one here, in JavaScript, would
// eventually make the tab and the CLI disagree about the same test set.
//
// Offline (./ui/run.sh, no Db2) it renders frozen results from eval_fixtures.json, the
// same pattern demo.js uses for demo_fixtures.json.

const EV = {
  sets: {},        // name -> {queries, sources, graded, ...} from /api/eval_sets
  set: "",
  data: null,      // the evaluate payload being rendered
  frozen: null,    // eval_fixtures.json, when present
  open: null,      // id of the query drilled into
};

const EV_BLOCKS = [
  ["heldout", "HELDOUT — the honest number (never tuned on)"],
  ["train", "TRAIN"],
  ["all", "ALL"],
];
const EV_COLS = [["mrr", "MRR"], ["hits1", "Hits@1"], ["recall", "Recall@5"],
                 ["ndcg", "nDCG@5"]];

// null means "not measured in this slice" (e.g. MRR over zero known-item queries).
// Showing it as a dash rather than 0.000 keeps that distinction visible.
const evNum = (v) => (v === null || v === undefined) ? "—" : Number(v).toFixed(3);

/* ---------- boot ---------- */
async function evaluateBoot() {
  if (!$("#ev-set")) return;                 // older cached markup
  $("#ev-run").addEventListener("click", runEvaluation);
  $("#ev-set").addEventListener("change", (e) => {
    EV.set = e.target.value;
    EV.data = (EV.frozen && EV.frozen.sets && EV.frozen.sets[EV.set]) || null;
    EV.open = null;
    renderEvaluation();
  });
  $("#ev-queries").addEventListener("click", (e) => {
    const row = e.target.closest(".evq-head"); if (!row) return;
    const id = Number(row.dataset.id);
    EV.open = EV.open === id ? null : id;    // aggregates hide WHICH queries fail
    renderQueries();
  });

  // Sets are created in the Label tab while this page is already loaded, so a one-shot
  // fetch at boot goes stale the moment you make one. Re-read the list whenever the tab
  // is opened.
  $("#tabs").addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t && t.dataset.page === "evaluate") loadEvalSets();
  });

  try { EV.frozen = await (await fetch("eval_fixtures.json", { cache: "no-store" })).json(); }
  catch (_) { EV.frozen = null; }
  await loadEvalSets();
}

async function loadEvalSets() {
  const previous = EV.set;
  try {
    const j = await (await fetch("/api/eval_sets", { cache: "no-store" })).json();
    EV.sets = j.sets || {};
  } catch (_) {
    EV.sets = (EV.frozen && EV.frozen.available) || {};
  }
  // Keep the selection across a refresh; fall back to the first set only if it vanished.
  EV.set = (previous && EV.sets[previous]) ? previous : (Object.keys(EV.sets).sort()[0] || "");
  if (EV.set !== previous) {
    EV.data = (EV.frozen && EV.frozen.sets && EV.frozen.sets[EV.set]) || null;
    EV.open = null;
  }
  renderEvaluation();
}

/* ---------- run ---------- */
async function runEvaluation() {
  if (!LIVE) {
    $("#ev-blocks").innerHTML = needsLive("Evaluation");
    $("#ev-status").textContent = "";
    return;
  }
  if (!EV.set) return;
  $("#ev-status").textContent = "running all three legs…";
  $("#ev-run").disabled = true;
  try {
    const r = await fetch(`/api/evaluate?set=${encodeURIComponent(EV.set)}`,
                          { cache: "no-store" });
    if (!r.ok) throw 0;
    EV.data = await r.json();
    EV.data.computed = null;                  // live: not a frozen result
    EV.open = null;
    $("#ev-status").textContent = "";
    renderEvaluation();
  } catch (_) {
    $("#ev-blocks").innerHTML = backendFailed("Evaluation");
    $("#ev-status").textContent = "";
  } finally {
    $("#ev-run").disabled = false;
  }
}

/* ---------- render ---------- */
function renderEvaluation() {
  const names = Object.keys(EV.sets).sort();
  $("#ev-set").innerHTML = names.map((n) =>
    `<option value="${esc(n)}"${n === EV.set ? " selected" : ""}>${esc(n)}</option>`).join("")
    || `<option value="">(no test sets — export one from the Label tab)</option>`;
  $("#ev-run").disabled = !LIVE || !EV.set;

  const info = EV.sets[EV.set] || {};
  const provenance = [
    info.queries !== undefined ? `${info.queries} queries` : null,
    info.skipped ? `${info.skipped} not yet complete` : null,
    info.known_item !== undefined
      ? `${info.known_item} known-item · ${info.topical} topical` : null,
    info.graded === true ? "graded 0–2" : info.graded === false ? "binary judgments" : null,
    (info.sources || []).length ? `source: ${info.sources.join(", ")}` : null,
    // Where the deck came from: the live judgments store, or an exported snapshot.
    info.origin === "store" ? "live judgments" : info.origin === "file" ? "exported deck" : null,
  ].filter(Boolean).join(" · ");
  const frozen = EV.data && EV.data.computed
    ? ` <span class="ev-frozen">frozen · computed ${esc(EV.data.computed)}</span>` : "";
  $("#ev-meta").innerHTML = esc(provenance) + frozen;

  if (!EV.data) {
    $("#ev-blocks").innerHTML = `<p class="placeholder">${LIVE
      ? "Press Run to score this set."
      : "No frozen results for this set — run <code>./ui/run.sh --live</code> and press Run, "
        + "or rebuild them with <code>./ui/build_eval_fixtures.sh</code>."}</p>`;
    $("#ev-queries").innerHTML = "";
    return;
  }
  // An empty or entirely-unfinished set is a state, not a table of dashes. Say which
  // queries are missing and why — a half-judged query is excluded on purpose, because
  // query_class is derived from the complete relevant set.
  if (!EV.data.queries) {
    const why = (EV.data.skipped || []).map((s) =>
      `<li><b>${esc(s.query || s.qid)}</b> — ${esc(s.why)}</li>`).join("");
    $("#ev-blocks").innerHTML = `<p class="placeholder">Nothing to score in this set yet.${
      why ? ` Judged but not exportable:<ul class="ev-skipped">${why}</ul>`
          : " Label some queries into it from the <b>Label</b> tab."}</p>`;
    $("#ev-queries").innerHTML = "";
    return;
  }
  $("#ev-blocks").innerHTML = EV_BLOCKS.map(([key, title]) => {
    const b = (EV.data.blocks || {})[key]; if (!b) return "";
    const any = EV.data.legs.map((l) => b[l]).find(Boolean) || {};
    return `<div class="ev-block">
      <h3>${esc(title)} <span>(known_item=${any.known_item || 0}, topical=${any.topical || 0})</span></h3>
      <table class="ev-table"><thead><tr><th>leg</th>
        ${EV_COLS.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead>
      <tbody>${EV.data.legs.map((leg) => `<tr><td class="ev-leg">${esc(leg)}</td>
        ${EV_COLS.map(([k]) => `<td>${evNum(b[leg][k])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div>`;
  }).join("");
  renderQueries();
}

// Per-query drill-down. An aggregate says the run is worse; only this says which query.
function renderQueries() {
  const rows = (EV.data && EV.data.per_query) || [];
  if (!rows.length) { $("#ev-queries").innerHTML = ""; return; }
  $("#ev-queries").innerHTML = `<h3 class="ev-qh">Per query</h3>` + rows.map((q) => {
    const open = EV.open === q.id;
    const body = open ? `<div class="evq-body">${EV.data.legs.map((leg) => `
      <div class="evq-leg"><h4>${esc(leg)}</h4>
        <ol>${(q.legs[leg] || []).map((d) => `<li class="${d.gold ? "evq-gold" : ""}">
          ${esc(d.title || ("#" + d.chunk_id))}
          ${d.author ? `<span class="evq-by">${esc(d.author)}</span>` : ""}
          ${d.gold ? `<span class="evq-mark">gold${d.grade !== null && d.grade !== undefined
            ? ` · grade ${d.grade}` : ""}</span>` : ""}
        </li>`).join("")}</ol>
      </div>`).join("")}</div>` : "";
    return `<div class="evq${open ? " open" : ""}">
      <button type="button" class="evq-head" data-id="${q.id}">
        <span class="evq-caret" aria-hidden="true">▸</span>
        <span class="evq-q">${esc(q.query)}</span>
        <span class="evq-t">${esc(q.query_class)} · ${q.gold_ids.length} gold · ${esc(q.split)}</span>
      </button>${body}</div>`;
  }).join("");
}

evaluateBoot();
