// 🔧 API base
const API_BASE = "https://chanthr-github-io.onrender.com";
const $ = (s, el = document) => el.querySelector(s);

// ---------- Global error hooks ----------
window.onerror = (m, src, line, col, err) => {
  console.error("[window.onerror]", m, src, line, col, err);
  const hl = $("#health"); if (hl) hl.textContent = "Script error";
};
window.onunhandledrejection = (e) => {
  console.error("[unhandledrejection]", e?.reason || e);
};

// ---------- Small utils ----------
const escapeHTML = (s='') => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ---------- UI helpers ----------
function ratioCard(title, node){
  if(!node) return '';
  const raw = node.value;
  const num = Number(raw);
  const value = (raw == null || Number.isNaN(num)) ? (raw ?? 'N/A') : num.toFixed(2);
  const band = node.band || 'N/A';
  return `
    <div class="ratio">
      <div><strong>${title}</strong> <span class="badge ${band}">${band}</span></div>
      <div class="mt-6">Value: ${value}</div>
    </div>`;
}

const fmtPct = (x) => (x == null || isNaN(x))
  ? 'N/A'
  : (x >= 0 ? '+' : '') + (Number(x) * 100).toFixed(2) + '%';

function predCard(p = {}){
  if (p && p.error) {
    return `<div class="ratio">
      <div><strong>${p.symbol || '-'}</strong></div>
      <div class="mt-6 muted">Prediction failed: ${escapeHTML(String(p.error))}</div>
    </div>`;
  }
  const signal = (p.signal || 'HOLD').toUpperCase();
  const badgeClass = signal === 'BUY' ? 'BUY' : (signal === 'SELL' ? 'SELL' : 'HOLD');
  return `
    <div class="ratio">
      <div><strong>${p.symbol || '-'}</strong> <span class="badge ${badgeClass}">${signal}</span></div>
      ${p.last_close != null ? `<div class="mt-6">Last close: ${p.last_close}</div>` : ''}
      ${p.live_price != null ? `<div class="mt-6">Live price: ${p.live_price}</div>` : ''}
      ${p.pred_ret_1d != null ? `<div class="mt-6">Pred. 1D return: ${fmtPct(p.pred_ret_1d)}</div>` : ''}
      ${p.pred_close_1d != null ? `<div class="mt-6">Pred. 1D close: ${p.pred_close_1d}</div>` : ''}
    </div>`;
}

// --- Analysis card for media sentiment (NO article list) ---
function renderNewsAnalysis(na, lang = 'ko') { 
  if (!na || !na.overall) return `<div class="muted">No media analysis.</div>`;
  const o = na.overall || {};
  const lbl = String(o.label || 'mixed');
  const lblText = (lang.startsWith('ko'))
    ? (lbl === 'bullish' ? '긍정적' : lbl === 'bearish' ? '부정적' : '혼재')
    : lbl;

  const score  = Number(o.score ?? 0);
  const impact = Number(o.impact_score ?? 0);
  const pos = o.pos ?? 0, neg = o.neg ?? 0, neu = o.neu ?? 0;
  const kws = (o.top_keywords || []).slice(0, 10);

  const badgeCls = lbl === 'bullish' ? 'BUY' : (lbl === 'bearish' ? 'SELL' : 'HOLD');

  return `
    <div class="ratio">
      <div class="row align-center">
        <strong>${lang.startsWith('ko') ? '언론 톤' : 'Media sentiment'}</strong>
        <span class="badge ${badgeCls}" style="margin-left:8px;">${lblText}</span>
      </div>
      <div class="mt-6 muted">
        ${lang.startsWith('ko') ? '점수' : 'Score'}: ${score >= 0 ? '+' : ''}${score.toFixed(3)}
        &nbsp;•&nbsp; Impact: ${impact >= 0 ? '+' : ''}${impact.toFixed(3)}
      </div>
      <div class="mt-6 muted">
        ${lang.startsWith('ko') ? '기사 분포' : 'Articles'}:
        <span class="pos">+${pos}</span> /
        <span class="neu">~${neu}</span> /
        <span class="neg">-${neg}</span>
      </div>
      ${kws.length ? `<div class="mt-8">
        ${(lang.startsWith('ko') ? '핵심 키워드' : 'Top keywords')}:
        ${kws.map(k=>`<span class="chip">${escapeHTML(k)}</span>`).join(' ')}
      </div>` : ''}
      ${na.note ? `<div class="mt-8 muted">${escapeHTML(na.note)}</div>` : ''}
    </div>
  `;
}

// ---------- Section toggles ----------
function getPrefs(){
  const narr = $("#opt-narr")?.checked ?? false; 
  const pred = $("#opt-pred")?.checked ?? false;
  const sum  = $("#opt-sum")?.checked  ?? false;
  const news = $("#opt-news")?.checked ?? false;
  return { narr, pred, sum, news };
}
function applySectionVisibility(p){
  const S = {
    narr: $("#narr-section"),
    pred: $("#pred-section"),
    sum:  $("#sum-section"),
    news: $("#news-section"),
  };
  if (S.narr) S.narr.classList.toggle('hidden', !p.narr);
  if (S.pred) S.pred.classList.toggle('hidden', !p.pred);
  if (S.sum)  S.sum.classList.toggle('hidden',  !p.sum);
  if (S.news) S.news.classList.toggle('hidden', !p.news);
}

// ---------- Loading progress ----------
function startProgressIn(el) {
  const isUL = el && el.tagName === 'UL';
  const wrap = isUL ? document.createElement('li') : document.createElement('div');
  wrap.className = isUL ? 'loading-item' : 'loading';
  wrap.innerHTML = `
    <div class="progress"><div class="bar" style="width:0%"></div></div>
    <span class="pct">Loading 0%</span>
  `;
  el.innerHTML = '';
  el.appendChild(wrap);

  const bar = wrap.querySelector('.bar');
  const pctEl = wrap.querySelector('.pct');
  let pct = 0;
  const timer = setInterval(() => {
    pct += Math.random() * 12 + 6;
    if (pct > 90) pct = 90;
    bar.style.width = pct.toFixed(0) + '%';
    pctEl.textContent = `Loading ${pct.toFixed(0)}%`;
  }, 220);

  return {
    finish(html) {
      clearInterval(timer);
      bar.style.width = '100%';
      pctEl.textContent = 'Loading 100%';
      setTimeout(() => { if (html != null) el.innerHTML = html; }, 150);
    },
    fail(msg='Failed to load') {
      clearInterval(timer);
      el.innerHTML = `<div class="muted">${escapeHTML(msg)}</div>`;
    }
  };
}

// ---------- Fetch helper ----------
async function fetchJSON(url, opts = {}, timeoutMs = 9000) {
  const extSignal = opts.signal;
  const ctrl = extSignal || new AbortController();
  const signal = ctrl.signal;
  const timer = extSignal ? null : setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { cache: "no-store", mode: "cors", ...opts, signal });
    if (timer) clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    if (timer) clearTimeout(timer);
    throw e;
  }
}

// ---------- Health ----------
async function checkHealth(){
  const apiEl = $("#health");
  const llmEl = $("#llm");
  if (apiEl) apiEl.textContent = "Checking…";
  if (llmEl) llmEl.textContent = "Checking…";

  try{
    const h = await fetchJSON(`${API_BASE}/health?t=${Date.now()}`);
    if (apiEl) apiEl.textContent = h?.status === "ok" ? "OK" : "Error";

    const on = (x)=> x && x.ready && x.provider ? `${x.provider.toUpperCase()} ON` : `Fallback (${x?.reason || "no LLM"})`;
    if (llmEl) llmEl.textContent = `Fin: ${on(h?.finance_llm)}  •  Agent: ${on(h?.agent_llm)}`;
    console.log("LLM Status:", h?.finance_llm, h?.agent_llm);
  }catch(e){
    console.error("health error", e);
    if (apiEl) apiEl.textContent = "Offline / Timeout";
    if (llmEl) llmEl.textContent = "Unavailable";
  }
}

// ---------- Analyse (/analyse) ----------
async function analyse(prefs){
  const goBtn = $("#go");
  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;
  if(!t){ alert('Ticker Symbol of the company.'); return; }

  goBtn.disabled = true; 
  goBtn.textContent = '⏳ Analysing...';
  $("#out").classList.add('hidden');

  try{
    const data = await fetchJSON(`${API_BASE}/analyse?t=${Date.now()}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ query: `${t} 유동성/건전성 평가`, language: lang })
    });

    $("#title").textContent = `${data.core?.company || '-'} (${data.core?.ticker || '-'})`;
    $("#meta").textContent  = `Last Price: ${data.core?.price ?? 'N/A'}  •  Source: ${data.meta?.source || '-'}`;

    const liq = data.core?.ratios?.Liquidity || {};
    const sol = data.core?.ratios?.Solvency || {};
    $("#liq").innerHTML = [
      ratioCard('Current Ratio', liq.current_ratio),
      ratioCard('Quick Ratio', liq.quick_ratio),
      ratioCard('Cash Ratio', liq.cash_ratio)
    ].join('');
    $("#sol").innerHTML = [
      ratioCard('Debt-to-Equity', sol.debt_to_equity),
      ratioCard('Debt Ratio', sol.debt_ratio),
      ratioCard('Interest Coverage', sol.interest_coverage)
    ].join('');

    // 📝 Narrative (only if selected)
    const md = (data.explanation || '').trim();
    if (prefs?.narr) {
      if (window.marked) { $("#narr").innerHTML = marked.parse(md); }
      else { $("#narr").textContent = md; }
      $("#narr-section")?.classList.remove('hidden');
    } else {
      $("#narr").textContent = '';
      $("#narr-section")?.classList.add('hidden');
    }

    $("#raw").textContent = JSON.stringify(data, null, 2);
    $("#out").classList.remove('hidden');
  }catch(e){
    alert('분석 실패: ' + e.message + '\n(API_BASE 확인 및 /health 체크)');
  }finally{
    goBtn.disabled = false; 
    goBtn.textContent = '🔎 Analyse';
  }
}

// ---------- Agent (/agent) ----------
let _agentCtrl = null;

async function renderAgentExtras(ticker, lang, prefs){
  const predEl = $("#pred"), sumEl = $("#sum"), newsEl = $("#news");

  // Show sections so progress is visible
  if (prefs.pred) $("#pred-section")?.classList.remove('hidden');
  if (prefs.sum)  $("#sum-section") ?.classList.remove('hidden');
  if (prefs.news) $("#news-section")?.classList.remove('hidden');

  // Progress bars
  let predProg = null, sumProg = null, newsProg = null;
  if (prefs.pred && predEl) predProg = startProgressIn(predEl);
  if (prefs.sum  && sumEl)  sumProg  = startProgressIn(sumEl);
  if (prefs.news && newsEl) newsProg = startProgressIn(newsEl);

  // cancel previous request
  if (_agentCtrl) _agentCtrl.abort();
  _agentCtrl = new AbortController();

  try{
    const ag = await fetchJSON(`${API_BASE}/agent?t=${Date.now()}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        query: `${ticker} 유동성/건전성 + 1D 예측`,
        language: lang,
        include_news: !!prefs.news
      }),
      signal: _agentCtrl.signal
    }, 25000);
    console.log("[/agent] ok", ag);

    // 🔮 Prediction
    if (prefs.pred && predEl && predProg) {
      predProg.finish(predCard(ag?.prediction || { symbol: ticker }));
    }

    // 🧠 Analyst summary (do NOT nest .summary again)
    if (prefs.sum && sumEl && sumProg)  {
      const txt = (ag?.summary || '').trim()
        || (lang === 'ko' ? '요약 없음' : 'No summary');
      sumProg.finish(escapeHTML(txt));
    }

    // 🗞 News / Analysis ONLY (no headline fallback)
    if (prefs.news && newsEl && newsProg) {
      let html = `<div class="muted">${lang==='ko'?'분석 없음':'No media analysis available.'}</div>`;
      let na = (ag && ag.news_analysis && ag.news_analysis.overall) ? ag.news_analysis : null;
      if (!na && ag && ag.news && !Array.isArray(ag.news) && ag.news.overall) na = ag.news;
      if (na) html = renderNewsAnalysis(na, lang);
      newsProg.finish(html);
    }

  }catch(e){
    if (e?.name !== 'AbortError') console.error("[/agent] error", e);
    if (predProg) predProg.fail('Prediction unavailable.');
    if (sumProg)  sumProg.fail('Summary unavailable.');
    if (newsProg) newsProg.fail('News unavailable.');
  } finally {
    _agentCtrl = null;
  }
}

// ---------- Patch Notes (floating button + modal) ----------
function mountPatchNotes(){
  const notes = (window.PATCH_NOTES || []);
  if (!Array.isArray(notes) || !notes.length) return;

  const fab = document.createElement('button');
  fab.className = 'patch-fab';
  fab.innerHTML = `<span class="pulse" aria-hidden="true"></span><span>Patch Notes</span>`;
  document.body.appendChild(fab);

  const modal = document.createElement('div');
  modal.className = 'patch-modal';
  const items = notes.map(n=>{
    const chips = (n.changes||[]).map(c=>{
      const cls = c.kind === 'added' ? 'added' : c.kind === 'fixed' ? 'fixed' : 'changed';
      return `<div class="patch-item"><span class="tag ${cls}">${c.kind}</span>${escapeHTML(c.text)}</div>`;
    }).join('');
    return `
      <div class="patch-card">
        <div class="row align-center" style="justify-content:space-between;">
          <div><strong>${escapeHTML(n.title || '')}</strong></div>
          <div class="muted">${escapeHTML(n.version || '')} • ${escapeHTML(n.date || '')}</div>
        </div>
        ${chips}
      </div>
    `;
  }).join('');

  modal.innerHTML = `<div style="padding:16px; width:100%; display:flex; align-items:center; justify-content:center;">${items}</div>`;
  modal.addEventListener('click', (e)=>{ if (e.target === modal) modal.classList.remove('open'); });
  document.body.appendChild(modal);

  fab.addEventListener('click', ()=> modal.classList.add('open'));
}

// ---------- Orchestration ----------
async function analyseWithExtras(){
  const prefs = getPrefs();
  applySectionVisibility(prefs);
  await analyse(prefs);

  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;

  if (!prefs.pred && !prefs.sum && !prefs.news) return;
  await renderAgentExtras(t, lang, prefs);
}

// ---------- Boot ----------
document.addEventListener('DOMContentLoaded', () => {
  console.log("[boot] DOM ready");
  applySectionVisibility(getPrefs());
  checkHealth();
  mountPatchNotes();

  const go = $("#go");
  if (!go) { console.error("[boot] #go not found!"); return; }
  go.addEventListener('click', analyseWithExtras);
  $("#ticker").addEventListener('keydown', (e)=>{ if(e.key==='Enter') analyseWithExtras(); });

  const toggle = $("#toggle-json");
  if (toggle) {
    toggle.addEventListener('change', (e)=>{
      $("#jsonWrap").classList.toggle('hidden', !e.target.checked);
    });
  }

  ["#opt-narr","#opt-pred","#opt-sum","#opt-news"].forEach(id=>{
    const el = $(id);
    if (el) el.addEventListener('change', ()=> applySectionVisibility(getPrefs()));
  });
});
