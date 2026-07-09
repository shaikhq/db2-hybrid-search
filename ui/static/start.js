"use strict";
/* "Start here" — a StoryBrand doorway tab. One screen, dark-navy flat, sentence case.
   Static content; the before/after is a snapshot of a VERIFIED real run — a clean
   "semantic finds, keyword misses" case:

     query : "getting deep focused work done without distraction"
     before (keyword #1) : Getting to Yes       — matched the word "getting", wrong book
     after  (hybrid  #1) : Slow Productivity     — the real top hit (chunk 91)

   IMPORTANT — verify against the LIVE /api/search, not a one-off script: the vector
   leg's ANN pool (FETCH APPROX) varies per Db2 session, so a borderline query can
   rank differently in the live server than in a script. This query is stable on the
   live API. Re-verify there if the corpus changes.
*/

const START_QUERY = "getting deep focused work done without distraction";
const sq = (s) => document.querySelector(s);

const HP = `<svg class="glyph-hp" viewBox="0 0 32 32" width="15" height="15" fill="none" aria-hidden="true">
  <path d="M7 19v-3a9 9 0 0 1 18 0v3" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" />
  <rect x="4.4" y="18.4" width="5.2" height="8.2" rx="2.3" stroke="currentColor" stroke-width="2.3" />
  <rect x="22.4" y="18.4" width="5.2" height="8.2" rx="2.3" stroke="currentColor" stroke-width="2.3" /></svg>`;
const CHECK = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" aria-hidden="true">
  <path d="M3 8.5l3.2 3.2L13 4.2" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>`;

function startView() {
  return `
  <div class="door">
    <div class="door-hero">
      <div class="eyebrow">${HP} searching your audiobook library</div>
      <h2 class="door-head">You've forgotten more<br>than you can find</h2>
      <p class="door-sub">Hybrid search gives back the library you already own.</p>
    </div>

    <div class="door-grid">
      <div class="door-left">
        <div class="door-problem">
          <div class="prob"><span class="kicker">what breaks</span><p>You remember the idea, not the title, and keyword search needs the words you don't have.</p></div>
          <div class="prob"><span class="kicker">how it feels</span><p>You paid for these. You learned from these. Now they're lost to you.</p></div>
          <div class="prob"><span class="kicker">why it matters</span><p>In 2026, you should be able to find a book just by describing it.</p></div>
        </div>
        <div class="door-ctas">
          <button id="start-cta-try" class="cta cta-primary" type="button">Try it on your library</button>
          <button id="start-cta-arch" class="cta cta-secondary" type="button">See how it's built</button>
        </div>
      </div>

      <div class="door-right">
        <div class="ba-wrap">
          <div class="ba-query">you describe &middot; <span>&ldquo;${START_QUERY}&rdquo;</span></div>
          <div class="ba">
            <div class="ba-panel ba-before">
              <div class="ba-label">before &middot; keyword</div>
              <div class="ba-title">Getting to Yes</div>
              <div class="ba-verdict miss">not what you meant</div>
            </div>
            <div class="ba-arrow" aria-hidden="true"></div>
            <div class="ba-panel ba-after">
              <div class="ba-label">after &middot; hybrid</div>
              <div class="ba-title">${HP} Slow Productivity</div>
              <div class="ba-by">Cal Newport</div>
              <div class="ba-verdict found">${CHECK} found it</div>
            </div>
          </div>
        </div>
        <ol class="door-plan">
          <li><span class="pnum">1</span><span>Describe what you remember.</span></li>
          <li><span class="pnum">2</span><span>It searches both ways at once, by keyword and by meaning.</span></li>
          <li><span class="pnum">3</span><span>The match surfaces. It never comes back empty.</span></li>
        </ol>
      </div>
    </div>

    <p class="door-guide">Built by an AI architect who lost his own library the same way.</p>
  </div>`;
}

function startBoot() {
  const host = sq("#start-canvas");
  if (!host) return;
  host.innerHTML = startView();

  // Primary CTA: close the loop — switch to Search, pre-fill the SAME query, run it.
  // (setPage + run live in app.js, loaded before this module. Offline, run() lands on
  //  Search and shows the "needs live backend" note — the prefilled query stays visible.)
  const tryBtn = sq("#start-cta-try");
  if (tryBtn) tryBtn.addEventListener("click", () => {
    const box = document.querySelector("#searchbox");
    if (box) box.value = START_QUERY;
    if (typeof setPage === "function") setPage("search");
    if (typeof run === "function") run();
  });

  // Secondary CTA: switch to the Architecture tab.
  const archBtn = sq("#start-cta-arch");
  if (archBtn) archBtn.addEventListener("click", () => {
    if (typeof setPage === "function") setPage("arch");
  });
}

startBoot();
