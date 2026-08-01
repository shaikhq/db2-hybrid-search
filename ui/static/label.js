"use strict";

// Label tab — pooled relevance judging (TREC-style). Build a pool from both retrievers,
// discard where each result came from, judge every unique document against the query.
// Spec + the five approved interaction rules: docs/label-tab-plan.md.
//
// Deliberately does NOT reuse app.js's resultCard(): it renders a position badge, which
// is exactly the anchoring this tab exists to avoid (and the pool carries no such field,
// so it would print "undefined"). coverImg / highlight / queryTerms / esc / $ / LIVE are
// reused as-is.

const LAB = {
  set: "",         // test set being labeled into
  sets: {},        // name -> {members, queries: {qid: summary}, ...} from /api/sets
  qid: "",         // qid of the loaded query, once it has one
  query: "",
  pool: [],        // [{chunk_id, title, author, description, cover, snippet}]
  labels: {},      // "cid" -> "relevant" | "irrelevant" | "skip"
  legs: null,      // {lexical: n, vector: n} — aggregate counts, never per document
  active: 0,       // index of the card the keyboard acts on
  terms: [],
  busy: false,
};

// Graded relevance, 3-point (see ui/api.py GRADES). The key IS the grade: press 2 for a
// 2, 1 for a 1, 0 for a 0. Nothing to memorise, and it keeps the scale in front of you
// while judging.
const LKEYS = { "2": "highly_relevant", "1": "relevant", "0": "irrelevant", "s": "skip" };
const LORDER = ["highly_relevant", "relevant", "irrelevant", "skip"];
const LNAME = { highly_relevant: "Highly relevant", relevant: "Relevant",
                irrelevant: "Not relevant", skip: "Skip" };
const LGRADE = { highly_relevant: "2", relevant: "1", irrelevant: "0", skip: "s" };

/* ---------- boot ---------- */
function labelBoot() {
  const box = $("#label-query");
  if (!box) return;                       // tab not on the page (older cached markup)
  $("#label-build").addEventListener("click", buildLabelPool);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") buildLabelPool(); });

  // Delegated: label buttons, and clicking a card body makes it the active one.
  $("#label-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".lbtn");
    if (btn) {
      const card = btn.closest(".lcard");
      applyLabel(Number(card.dataset.cid), btn.dataset.label);
      return;
    }
    const card = e.target.closest(".lcard");
    if (card) setActive(LAB.pool.findIndex((d) => d.chunk_id === Number(card.dataset.cid)));
  });

  // Sidebar: pick a set, create one, or open a query already in it.
  $("#label-set").addEventListener("change", (e) => {
    LAB.set = e.target.value;
    renderSets();
  });
  $("#label-newset").addEventListener("click", createSet);
  $("#label-addset").addEventListener("change", refreshAddTo);
  $("#label-add").addEventListener("click", addToSet);
  $("#label-members").addEventListener("click", (e) => {
    const row = e.target.closest(".dchip"); if (!row) return;
    $("#label-query").value = row.dataset.text;
    buildLabelPool();                       // rehydrates: reviewing IS re-labeling
  });

  // Contract 1: the keyboard is the primary path — ~300 judgments makes mouse travel
  // the difference between one sitting and three.
  document.addEventListener("keydown", onLabelKey);
  loadSets();
}

/* ---------- test sets ---------- */
async function loadSets() {
  try {
    const j = await (await fetch("/api/sets", { cache: "no-store" })).json();
    LAB.sets = j.sets || {};
    if (!LAB.set || !LAB.sets[LAB.set]) LAB.set = j.active;
    renderSets();
  } catch (_) { /* offline: the tab still labels nothing, and says so on Build */ }
}

function renderSets() {
  const names = Object.keys(LAB.sets).sort();
  const opts = (sel) => names.map((n) =>
    `<option value="${esc(n)}"${n === sel ? " selected" : ""}>${esc(n)}</option>`).join("");
  $("#label-set").innerHTML = opts(LAB.set);
  // "Add to" offers every OTHER set — filing a query where it already is, is a no-op.
  const others = names.filter((n) => n !== LAB.set);
  $("#label-addset").innerHTML = others.length
    ? others.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("")
    : `<option value="">(no other set yet)</option>`;

  const s = LAB.sets[LAB.set] || {};
  const members = s.members || [];
  $("#label-setmeta").textContent = members.length
    ? `${members.length} quer${members.length === 1 ? "y" : "ies"} · ` +
      `${s.complete || 0} complete · ${s.judgments || 0} judgments` +
      (s.pool_depth ? ` · depth ${s.pool_depth}` : "")
    : "No queries yet — type one and build its pool.";

  const q = s.queries || {};
  $("#label-members").innerHTML = members.map((qid) => {
    const m = q[qid] || {};
    return `<button type="button" class="dchip${qid === LAB.qid ? " active" : ""}"
       data-qid="${esc(qid)}" data-text="${esc(m.text || "")}">
      <span class="dchip-q">${esc(m.text || qid)}</span>
      <span class="dchip-t">${qid} · ${m.decided || 0}/${m.pool_size || 0} decided ·
        ${m.gold || 0} gold${m.complete ? " · ✓" : ""}</span>
    </button>`;
  }).join("") || `<p class="placeholder">Nothing filed here yet.</p>`;
  refreshAddTo();
}

function refreshAddTo() {
  const target = $("#label-addset").value;
  const already = target && (LAB.sets[target]?.members || []).includes(LAB.qid);
  const can = Boolean(LAB.qid && target && !already);
  $("#label-add").disabled = !can;
  $("#label-addset").disabled = !LAB.qid;
  $("#label-addmsg").textContent = LAB.qid && already ? `already in ${target}` : "";
}

async function createSet() {
  const name = (prompt("Name for the new test set (letters, digits, . _ -):") || "").trim();
  if (!name) return;
  const r = await fetch("/api/sets", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    $("#label-addmsg").textContent = (await r.json()).detail || "could not create set";
    return;
  }
  LAB.set = name;
  await loadSets();
}

// Files the CURRENT query into another set. Nothing is copied — the set gains a reference
// to the qid and both sets read the same judgments, so a later correction fixes both.
async function addToSet() {
  const target = $("#label-addset").value;
  if (!LAB.qid || !target) return;
  const r = await fetch(`/api/sets/${encodeURIComponent(target)}/members`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qid: LAB.qid }),
  });
  $("#label-addmsg").textContent = r.ok
    ? `added to ${target} — same judgments, no copy`
    : ((await r.json()).detail || "could not add");
  if (r.ok) await loadSets();
}

function onLabelKey(e) {
  const page = $("#page-label");
  if (!page || page.hidden) return;                       // only while the tab is open
  // SELECT matters now that the sidebar has set pickers: typing "s" to jump an option
  // must not also record a Skip on the active card.
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)
      || e.metaKey || e.ctrlKey || e.altKey) return;
  if (!LAB.pool.length) return;
  if (LKEYS[e.key]) {
    e.preventDefault();
    const doc = LAB.pool[LAB.active];
    if (doc) applyLabel(doc.chunk_id, LKEYS[e.key]);
  } else if (e.key === "u" || e.key === "Backspace") {
    // Step back rather than erase. A judgment is never returned to "undecided" — every
    // pooled document is meant to end up decided (contract 4), and a mis-keyed label is
    // corrected by pressing the right key on the card, which contract 2 makes free.
    e.preventDefault();
    setActive(Math.max(0, LAB.active - 1));
  } else if (e.key === "ArrowDown" || e.key === "j") {
    e.preventDefault(); setActive(Math.min(LAB.pool.length - 1, LAB.active + 1));
  } else if (e.key === "ArrowUp" || e.key === "k") {
    e.preventDefault(); setActive(Math.max(0, LAB.active - 1));
  }
}

/* ---------- build the pool ---------- */
async function buildLabelPool() {
  const q = $("#label-query").value.trim();
  if (!q) return;
  if (!LIVE) {
    $("#label-list").innerHTML = `<p class="placeholder">Labeling needs the live backend —
      run <code>./ui/run.sh --live</code>, then build a pool here.</p>`;
    return;
  }
  $("#label-list").innerHTML = `<p class="placeholder">Building pool…</p>`;
  $("#label-progress").textContent = "";
  try {
    // Contract 3: the pool is always merged with the stored judgments, so a re-typed
    // query resumes with its existing labels already applied. The query-seeded order
    // from the backend keeps a resumed session's cards in the same places.
    const [poolRes, judgeRes] = await Promise.all([
      fetch(`/api/pool?q=${encodeURIComponent(q)}`, { cache: "no-store" }),
      fetch("/api/judgments", { cache: "no-store" }),
    ]);
    if (!poolRes.ok) throw 0;
    const data = await poolRes.json();
    const store = judgeRes.ok ? await judgeRes.json() : { by_text: {} };

    LAB.query = q;
    LAB.pool = data.pool || [];
    LAB.legs = data.legs || {};
    // Entries are keyed by a stable qid; we only know the typed text, so look up through
    // the server's by_text index. Normalization here must match api.py's _norm().
    const key = q.trim().replace(/\s+/g, " ").toLowerCase();
    const known = (store.by_text || {})[key] || {};
    LAB.qid = known.qid || "";          // empty until the first judgment assigns one
    LAB.labels = Object.assign({}, known.labels || {});
    LAB.terms = queryTerms(q);
    LAB.active = firstUndecided();
    renderLabelPool();
    renderSets();                        // reflect the newly-active query in the sidebar
  } catch (_) {
    $("#label-list").innerHTML =
      `<p class="placeholder">Could not build the pool — is the live backend running?</p>`;
  }
}

const firstUndecided = () => {
  const i = LAB.pool.findIndex((d) => !LAB.labels[String(d.chunk_id)]);
  return i === -1 ? Math.max(0, LAB.pool.length - 1) : i;
};

/* ---------- render ---------- */
function renderLabelPool() {
  const host = $("#label-list");
  // Contract 5: an empty or partial pool is an explicit state, never a blank list.
  if (!LAB.pool.length) {
    host.innerHTML = `<p class="placeholder">No results for this query — nothing to label.
      Nothing was saved.</p>`;
    $("#label-progress").textContent = "";
    return;
  }
  host.innerHTML = LAB.pool.map(labelCard).join("");
  renderLabelProgress();
  setActive(LAB.active);
}

function labelCard(d, i) {
  const cid = String(d.chunk_id);
  const lab = LAB.labels[cid];
  const title = d.title || d.snippet || "";
  const cls = ["lcard", lab ? "lcard-labeled" : "", lab ? "lcard-" + lab : "",
    i === LAB.active ? "lcard-active" : ""].filter(Boolean).join(" ");
  const buttons = LORDER.map((k) =>
    `<button type="button" class="lbtn lbtn-${k}" data-label="${k}"
       aria-pressed="${String(lab === k)}">${LNAME[k]} <kbd>${LGRADE[k]}</kbd></button>`).join("");
  return `<article class="${cls}" data-cid="${esc(cid)}">
    ${coverImg(d)}
    <div class="lbody">
      <div class="ltitle">${highlight(esc(title), LAB.terms)}</div>
      ${d.author ? `<div class="lby">by ${esc(d.author)}</div>` : ""}
      ${d.description ? `<div class="rdesc ldesc">${highlight(esc(d.description), LAB.terms)}</div>` : ""}
    </div>
    <div class="lactions">${buttons}
      ${lab ? `<span class="lchip lchip-${lab}">${LNAME[lab]}</span>` : ""}</div>
  </article>`;
}

// Contract 4: two numbers. `decided` counts every judgment including skips (the pool is
// complete when all of them are decided); `skipped` is tracked separately because skips
// are the revisit queue, and because the exporter treats them as gaps, not judgments.
function renderLabelProgress() {
  const at = (k) => LAB.pool.filter((d) => LAB.labels[String(d.chunk_id)] === k).length;
  const decided = LAB.pool.filter((d) => LAB.labels[String(d.chunk_id)]).length;
  const skipped = at("skip");
  const grades = `<b>${at("highly_relevant")}</b> highly · <b>${at("relevant")}</b> relevant`;
  const total = LAB.pool.length;
  const done = decided === total;
  const legs = LAB.legs || {};
  const live = ["lexical", "vector"].filter((k) => (legs[k] || 0) > 0).length;
  const partial = live === 1
    ? ` · pool built from 1 of 2 retrievers` : "";
  const where = LAB.set ? `<span class="lset">${esc(LAB.set)}</span> · ` : "";
  $("#label-progress").innerHTML = where +
    `<b>${decided}</b> decided / ${total} in pool · ${grades} · ` +
    `<b>${skipped}</b> skipped${esc(partial)}` +
    (done ? ` <span class="lcomplete">✓ complete</span>`
          : ` <span class="lincomplete">in progress</span>`);
}

function setActive(i) {
  if (i < 0 || i >= LAB.pool.length) return;
  LAB.active = i;
  const cards = $("#label-list").querySelectorAll(".lcard");
  cards.forEach((c, n) => c.classList.toggle("lcard-active", n === i));
  const card = cards[i];
  if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* ---------- label a document ---------- */
async function applyLabel(cid, label) {
  if (LAB.busy) return;
  LAB.busy = true;
  const key = String(cid);
  const previous = LAB.labels[key];
  LAB.labels[key] = label;                     // optimistic: the click must feel instant
  paintCard(cid);
  renderLabelProgress();
  try {
    const r = await fetch("/api/judgments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: LAB.query, cid: cid, label: label,
                             pool_size: LAB.pool.length, set: LAB.set }),
    });
    if (!r.ok) throw 0;
    // The first judgment on a new query is what assigns its qid and files it into the
    // active set; pick both up so the sidebar and "Add to test set" go live immediately.
    const body = await r.json();
    if (body.qid && body.qid !== LAB.qid) { LAB.qid = body.qid; loadSets(); }
  } catch (_) {
    // Roll the optimistic paint back: a label that silently failed to save is the one
    // failure mode that costs real work, so it has to be visible immediately.
    if (previous) LAB.labels[key] = previous; else delete LAB.labels[key];
    paintCard(cid);
    renderLabelProgress();
    $("#label-progress").innerHTML +=
      ` <span class="lerror">— not saved! check the server</span>`;
    LAB.busy = false;
    return;
  }
  LAB.busy = false;
  // Contract 1: the card stays in place (collapsed); the cursor moves to the next
  // undecided one so the pool stays scannable and earlier judgments remain revisable.
  const idx = LAB.pool.findIndex((d) => d.chunk_id === cid);
  if (idx === LAB.active) {
    const next = LAB.pool.findIndex((d, n) => n > idx && !LAB.labels[String(d.chunk_id)]);
    setActive(next === -1 ? firstUndecided() : next);
  }
}

// Repaint one card in place. Contract 1 again: labeling collapses a card, it never
// removes it — re-rendering the whole list would also lose the scroll position.
function paintCard(cid) {
  const card = $(`#label-list .lcard[data-cid="${cid}"]`);
  if (!card) return;
  const lab = LAB.labels[String(cid)];
  LORDER.forEach((k) => card.classList.remove("lcard-" + k));
  card.classList.toggle("lcard-labeled", Boolean(lab));
  if (lab) card.classList.add("lcard-" + lab);
  card.querySelectorAll(".lbtn").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.label === lab)));
  const actions = card.querySelector(".lactions");
  const chip = actions.querySelector(".lchip");
  if (chip) chip.remove();
  if (lab) actions.insertAdjacentHTML("beforeend",
    `<span class="lchip lchip-${lab}">${LNAME[lab]}</span>`);
}

labelBoot();
