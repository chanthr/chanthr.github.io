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
      <div class="mt-6 muted">Prediction failed: ${String(p.error)}</div>
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

function fmtTime(ts){
  try {
    if (!ts) return '';
    const d = new Date(Number(ts) * 1000);
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  } catch { return ''; }
}
function newsList(items = []){
  if(!Array.isArray(items) || items.length === 0){
    return `<li class="muted">No recent headlines.</li>`;
  }
  return items.map(n => {
    const t = (n.title || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const link = n.link || '#';
    const when = fmtTime(n.providerPublishTime || n.pubTime || n.time || n.pub_time);
    return `<li><a href="${link}" target="_blank" rel="noopener">${t}</a>${when ? ` <time>· ${when}</time>`:''}</li>`;
  }).join('');
}

// --- Analysis card for media sentiment ---
function renderNewsAnalysis(na, lang = 'ko') { 
  if (!na || !na.overall) return `<div class="muted">No media analysis.</div>`;
  const o = na.overall || {};
  const lbl = String(o.label || 'mixed');
  const lblText = (lang.startsWith('ko'))
    ? (lbl === 'bullish' ? '긍정적' : lbl === 'bearish' ? '부정적' : '혼재')
    : lbl;

  const score = (o.score ?? 0);
  const impact = (o.impact_score ?? 0);
  const pos = o.pos ?? 0, neg = o.neg ?? 0, neu = o.neu ?? 0;
  const kws = (o.top_keywords || []).slice(0, 10);

  const badgeCls = lbl === 'bullish' ? 'BUY' : (lbl === 'bearish' ? 'SELL' : 'HOLD');

  const items = (na.items || []).slice(0, 5).map(it => {
    const s = it.sentiment ?? 0;
    const emoji = s > 0.25 ? '📈' : (s < -0.25 ? '📉' : '➖');
    const tags = (it.impact_tags || []).map(t => `<span class="chip">${t}</span>`).join(' ');
    const safeTitle = String(it.title || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const when = it.ts ? new Date(it.ts * 1000).toLocaleString() : '';
    return `
      <li class="media-item">
        <a href="${it.link || '#'}" target="_blank" rel="noopener">${emoji} ${safeTitle}</a>
        ${when ? `<time> · ${when}</time>` : ''}
        ${tags ? `<div class="mt-4">${tags}</div>` : ''}
      </li>`;
  }).join('');

  return `
    <div class="media-wrap">
      <div class="row align-center">
        <strong>${lang.startsWith('ko') ? '언론 톤' : 'Media sentiment'}</strong>
        <span class="badge ${badgeCls}" style="margin-left:8px;">${lblText}</span>
        <span class="muted" style="margin-left:8px;">score ${score >= 0 ? '+' : ''}${Number(score).toFixed(3)}</span>
        <span class="muted" style="margin-left:8px;">impact ${impact >= 0 ? '+' : ''}${Number(impact).toFixed(3)}</span>
      </div>

      <div class="mt-8 muted">
        ${lang.startsWith('ko') ? '기사 분포' : 'Articles'}:
        <span class="pos">+${pos}</span> /
        <span class="neu">~${neu}</span> /
        <span class="neg">-${neg}</span>
      </div>

      ${kws.length ? `<div class="mt-8">
        ${(lang.startsWith('ko') ? '핵심 키워드' : 'Top keywords')}:
        ${kws.map(k=>`<span class="chip">${k}</span>`).join(' ')}
      </div>` : ''}

      ${items ? `<ul class="news-list mt-12">${items}</ul>` : `<div class="muted mt-8">No representative items.</div>`}
      ${na.note ? `<div class="mt-8 muted">${na.note}</div>` : ''}
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

// ---------- Loading progress (smooth fake) ----------
function startProgressIn(el) {
  // el can be a <div> or a <ul>. We inject valid markup for both.
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
      el.innerHTML = `<div class="muted">${msg}</div>`;
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

  // show sections so progress is visible
  if (prefs.pred) $("#pred-section")?.classList.remove('hidden');
  if (prefs.sum)  $("#sum-section") ?.classList.remove('hidden');
  if (prefs.news) $("#news-section")?.classList.remove('hidden');

  // progress instances
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

    // 🧠 Analyst summary
    if (prefs.sum && sumEl && sumProg)  {
      const txt = (ag?.summary || '').trim()
        || (lang === 'ko' ? '요약 없음' : 'No summary');
      sumProg.finish(`<div class="summary muted">${txt}</div>`);
    }

    // 🗞 News / Analysis
    if (prefs.news && newsEl && newsProg) {
      let html = '';
      let na = (ag && ag.news_analysis && ag.news_analysis.overall) ? ag.news_analysis : null;
      if (!na && ag && ag.news && !Array.isArray(ag.news) && ag.news.overall) na = ag.news;

      if (na) {
        html = renderNewsAnalysis(na, lang);
      } else if (Array.isArray(ag?.news) && ag.news.length) {
        html = newsList(ag.news);
      } else {
        html = `<div class="muted">${lang==='ko'?'분석/뉴스 없음':'No media analysis available.'}</div>`;
      }
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
