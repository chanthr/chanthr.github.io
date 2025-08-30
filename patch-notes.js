/* Patch Notes widget - lightweight, no deps */
(function(){
  const htmlSkeleton = `
  <div id="pn-root" class="pn">
    <button id="pn-fab" class="pn-fab" type="button" aria-haspopup="dialog" aria-controls="pn-modal">
      ✨ <span class="pn-fab-text">What’s new</span>
      <span id="pn-dot" class="pn-dot" aria-hidden="true"></span>
    </button>
    <div id="pn-modal" class="pn-modal" aria-hidden="true">
      <div id="pn-overlay" class="pn-overlay" tabindex="-1"></div>
      <div class="pn-card" role="dialog" aria-modal="true" aria-labelledby="pn-title">
        <header class="pn-header">
          <div class="pn-title-wrap">
            <h2 id="pn-title">What’s new</h2>
            <span id="pn-version" class="pn-version"></span>
          </div>
          <button id="pn-close" class="pn-icon" type="button" aria-label="Close">✕</button>
        </header>
        <section id="pn-list" class="pn-list" aria-live="polite"></section>
        <footer class="pn-footer">
          <button id="pn-mark" class="pn-btn pn-primary" type="button">Mark all as read</button>
          <button id="pn-dismiss" class="pn-btn" type="button">Close</button>
        </footer>
      </div>
    </div>
  </div>`;

  // Ensure skeleton exists
  if (!document.querySelector("#pn-root")) {
    const wrap = document.createElement("div");
    wrap.innerHTML = htmlSkeleton;
    document.body.appendChild(wrap.firstElementChild);
  }

  const $ = (s, el=document)=>el.querySelector(s);
  const root = $("#pn-root");
  const fab = $("#pn-fab");
  const dot = $("#pn-dot");
  const modal = $("#pn-modal");
  const card = $(".pn-card", modal);
  const overlay = $("#pn-overlay");
  const closeBtn = $("#pn-close");
  const dismissBtn = $("#pn-dismiss");
  const markBtn = $("#pn-mark");
  const listEl = $("#pn-list");
  const verEl = $("#pn-version");

  const scriptEl = document.currentScript;
  const KEY = (scriptEl?.dataset?.key) || "pn_last_seen_ts";

  // Load notes: global -> data-src JSON -> fallback
  const start = async () => {
    let notes = (window.PATCH_NOTES || null);
    if (!notes && scriptEl?.dataset?.src) {
      try {
        const res = await fetch(scriptEl.dataset.src, { cache: "no-store" });
        notes = await res.json();
      } catch {}
    }
    if (!Array.isArray(notes)) {
      notes = [{
        version: "v0.0.1",
        date: new Date().toISOString().slice(0,10),
        title: "Patch notes ready",
        changes: [{ kind: "added", text: "You can now manage updates via patch-notes.js." }]
      }];
    }
    init(notes);
  };

  function init(PATCH_NOTES){
    // Latest timestamp for unread dot
    const latestTs = Math.max(...PATCH_NOTES.map(n => Date.parse(n.date||0) || 0), 0);
    const lastSeen = Number(localStorage.getItem(KEY) || 0);
    const hasNew = latestTs > lastSeen;
    if (hasNew) dot.removeAttribute("hidden");

    renderNotes(PATCH_NOTES);

    // Events
    fab.addEventListener("click", openModal);
    closeBtn.addEventListener("click", closeModal);
    dismissBtn.addEventListener("click", closeModal);
    overlay.addEventListener("click", closeModal);
    markBtn.addEventListener("click", ()=>{ markAllRead(latestTs); closeModal(); });
    document.addEventListener("keydown", (e)=>{ if(e.key==="Escape") closeModal(); });
  }

  function renderNotes(notes){
    const latest = notes[0];
    if (latest?.version) verEl.textContent = latest.version;

    listEl.innerHTML = notes.map((n, i) => {
      const delay = 40 * i;
      const badges = (n.changes || [])
        .slice(0, 4)
        .map(c => `<span class="pn-badge ${c.kind}">${(c.kind||"").toUpperCase()}</span>`)
        .join("");
      const desc = (n.changes || [])
        .map(c => `• ${escapeHTML(c.text||"")}`)
        .join("<br>");
      return `
        <article class="pn-item" style="--delay:${delay}ms">
          <div class="pn-tl">
            <span class="pn-dot2"></span>
            <span class="pn-line"></span>
          </div>
          <div>
            <div class="pn-head">
              <span class="pn-date">${formatDate(n.date)}</span>
              <div class="pn-badges">${badges}</div>
            </div>
            <h3 class="pn-title">${escapeHTML(n.title || 'Update')}</h3>
            <p class="pn-desc">${desc}</p>
          </div>
        </article>`;
    }).join("");
  }

  function openModal(){ modal.classList.add("pn-open"); document.body.classList.add("pn-lock"); card.focus?.(); }
  function closeModal(){ modal.classList.remove("pn-open"); document.body.classList.remove("pn-lock"); }
  function markAllRead(ts){ localStorage.setItem(KEY, String(ts)); $("#pn-dot")?.setAttribute("hidden","hidden"); }

  // Utils
  function formatDate(s){ const d = new Date(s); return isNaN(d) ? "" : new Intl.DateTimeFormat(undefined,{dateStyle:"medium"}).format(d); }
  function escapeHTML(str){ return String(str).replace(/[&<>"']/g, s=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[s])); }

  // Go
  start();
})();
