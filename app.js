// 🔧 API base
const API_BASE = "https://chanthr-github-io.onrender.com";
const $ = (s, el = document) => el.querySelector(s);

// 전역 에러 캐치(스크립트 초기 에러도 화면에 노출)
window.onerror = (m, src, line, col, err) => {
  console.error("[window.onerror]", m, src, line, col, err);
  const hl = $("#health"); if (hl) hl.textContent = "Script error";
};
window.onunhandledrejection = (e) => {
  console.error("[unhandledrejection]", e.reason || e);
};

// ========== Helper Tools for UI + FUC ==========
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

// News  Added
function NewsAnalysis(na, lang = 'ko') { 
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

  // 상위 5개 항목만 샘플로 노출 (제목 + 감성 + 태그)
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
        <strong>Media sentiment</strong>
        <span class="badge ${badgeCls}" style="margin-left:8px;">${lblText}</span>
        <span class="muted" style="margin-left:8px;">score ${score >= 0 ? '+' : ''}${score.toFixed(3)}</span>
        <span class="muted" style="margin-left:8px;">impact ${impact >= 0 ? '+' : ''}${impact.toFixed(3)}</span>
      </div>

      <div class="mt-8 muted">
        ${lang.startsWith('ko') ? '기사 분포' : 'Articles'}:
        <span class="pos">+${pos}</span> /
        <span class="neg">-${neg}</span> /
        <span class="neu">~${neu}</span>
      </div>

      ${kws.length ? `<div class="mt-8">
        ${(lang.startsWith('ko') ? '핵심 키워드' : 'Top keywords')}:
        ${kws.map(k=>`<span class="chip">${k}</span>`).join(' ')}
      </div>` : ''}

      ${items ? `<ul class="news-list mt-12">${items}</ul>` : `<div class="muted mt-8">No representative items.</div>`}
    </div>
  `;
}

// ========== 옵션 읽기 & 섹션 표시 ==========
function getPrefs(){
  const pred = $("#opt-pred")?.checked ?? false;
  const sum  = $("#opt-sum")?.checked  ?? false;
  const news = $("#opt-news")?.checked ?? false;
  return { pred, sum, news };
}

function findWrap(childSel, preferredIdSel){
  const byId = document.querySelector(preferredIdSel);
  if (byId) return byId;
  const child = document.querySelector(childSel);
  if (child && child.closest) {
    const sec = child.closest('section');
    if (sec) return sec;
  }
  return child ? child.parentElement : null;
}

function applySectionVisibility(p){
  const predWrap = findWrap('#pred', '#pred-section');
  const sumWrap  = findWrap('#sum',  '#sum-section');
  const newsWrap = findWrap('#news', '#news-section');

  if (predWrap) predWrap.classList.toggle('hidden', !p.pred);
  if (sumWrap)  sumWrap.classList.toggle('hidden',  !p.sum);
  if (newsWrap) newsWrap.classList.toggle('hidden', !p.news);
}

// ========== 유틸리티 ==========
async function fetchJSON(url, opts={}, timeoutMs=15000){
  const ctrl = new AbortController();
  const t = setTimeout(()=>ctrl.abort(), timeoutMs);
  try{
    const res = await fetch(url, {cache:"no-store", mode:"cors", signal:ctrl.signal, ...opts});
    clearTimeout(t);
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  }catch(e){
    clearTimeout(t);
    throw e;
  }
}

// ========== Health ==========
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

// ========== 기본 분석 (/analyse) ==========
async function analyse(){
  const goBtn = $("#go");
  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;

  console.log("[click] Analyse pressed", { t, lang });

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

    console.log("[/analyse] ok", data);

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

    const md = (data.explanation || '').trim();
    if (window.marked) { $("#narr").innerHTML = marked.parse(md); }
    else { $("#narr").textContent = md; }

    $("#raw").textContent = JSON.stringify(data, null, 2);
    $("#out").classList.remove('hidden');
  }catch(e){
    console.error("[/analyse] error", e);
    alert('분석 실패: ' + (e?.message || e) + '\n(API_BASE 및 /health 확인)');
  }finally{
    goBtn.disabled = false; 
    goBtn.textContent = '🔎 Analyse';
  }
}

// ========== 에이전트 섹션 (/agent) ==========
async function renderAgentExtras(ticker, lang, prefs){
  const predEl = $("#pred"), sumEl = $("#sum"), newsEl = $("#news");
  if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Loading prediction…</div>`;
  if (prefs.sum  && sumEl)  sumEl.textContent = '';
  if (prefs.news && newsEl) newsEl.innerHTML = '';

  try{
    console.time('/agent');
    const ag = await fetchJSON(`${API_BASE}/agent?t=${Date.now()}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        query: `${ticker} 유동성/건전성 + 1D 예측`,
        language: lang,
        include_news: !!prefs.news
      })
    });
    }, 30000); // ← 30초로 늘림
    console.timeEnd('/agent');
    console.log("[/agent] ok", ag);

    if (prefs.pred && predEl) {
      predEl.innerHTML = predCard(ag.prediction || { symbol: ticker });
      predEl.closest('section')?.classList.remove('hidden');
    }
    if (prefs.sum  && sumEl)  {
      sumEl.textContent = (ag.summary || '').trim() || (lang === 'ko' ? '요약 없음' : 'No summary');
      sumEl.closest('section')?.classList.remove('hidden');
    }
    
    if (prefs.news && newsEl) {
      try {
        // 서버가 news_analysis를 주면 그걸 우선 사용
        const na =
          ag.news_analysis ||
          ((!Array.isArray(ag.news) && ag.news && ag.news.overall) ? ag.news : null);

        if (na && typeof renderNewsAnalysis === 'function') {
          newsEl.innerHTML = renderNewsAnalysis(na, lang);
        } else if (Array.isArray(ag.news) && ag.news.length) {
            // 폴백: 헤드라인 리스트만 왔을 때
          newsEl.innerHTML = newsList(ag.news);
        } else {
          newsEl.innerHTML = `<div class="muted">No media analysis available.</div>`;
        }
      } catch (e) {
        console.error('render news error', e);
        newsEl.innerHTML = `<div class="muted">Media analysis unavailable.</div>`;
      }
      newsEl.closest('section')?.classList.remove('hidden');
    }
  }catch(e){
    console.error("[/agent] error", e);
    if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Prediction unavailable.</div>`;
    if (prefs.sum  && sumEl)  sumEl.textContent = '';
    if (prefs.news && newsEl) newsEl.innerHTML  = `<li class="muted">News unavailable.</li>`;
  }
}

// ========== 메인 플로우 ==========
async function analyseWithExtras(){
  const prefs = getPrefs();
  applySectionVisibility(prefs);
  await analyse();

  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;

  if (!prefs.pred && !prefs.sum && !prefs.news) return;
  await renderAgentExtras(t, lang, prefs);
}

// ========== Boot ==========
document.addEventListener('DOMContentLoaded', () => {
  console.log("[boot] DOM ready");
  applySectionVisibility(getPrefs());
  checkHealth();

  const go = $("#go");
  if (!go) {
    console.error("[boot] #go not found!");
    return;
  }
  go.addEventListener('click', analyseWithExtras);
  $("#ticker").addEventListener('keydown', (e)=>{ if(e.key==='Enter') analyseWithExtras(); });

  const toggle = $("#toggle-json");
  if (toggle) {
    toggle.addEventListener('change', (e)=>{
      $("#jsonWrap").classList.toggle('hidden', !e.target.checked);
    });
  }

  ["#opt-pred","#opt-sum","#opt-news"].forEach(id=>{
    const el = $(id);
    if (el) el.addEventListener('change', ()=> applySectionVisibility(getPrefs()));
  });
});
