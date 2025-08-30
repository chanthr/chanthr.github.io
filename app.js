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
  const narr = $("#opt-narr")?.checked ?? false; 
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

// ---------- Loading progress (fake but smooth) ----------
function startProgressIn(el) {
  // el can be a <div> or a <ul>. We inject valid markup for both cases.
  const isUL = el && el.tagName === 'UL';
  const wrap = isUL
    ? document.createElement('li')
    : document.createElement('div');
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
    // accelerate to ~90% then wait for finish()
    pct += Math.random() * 12 + 6;
    if (pct > 90) pct = 90;
    bar.style.width = pct.toFixed(0) + '%';
    pctEl.textContent = `Loading ${pct.toFixed(0)}%`;
  }, 220);

  return {
    finish(text) {
      clearInterval(timer);
      pct = 100;
      bar.style.width = '100%';
      pctEl.textContent = 'Loading 100%';
      // slight delay so users see it hit 100
      setTimeout(() => { if (text) el.innerHTML = text; }, 150);
    },
    fail(msg='Failed to load') {
      clearInterval(timer);
      el.innerHTML = `<div class="muted">${msg}</div>`;
    }
  };
}

// ========== 유틸리티 ==========
async function fetchJSON(url, opts = {}, timeoutMs = 9000) {
  // 외부에서 전달한 AbortSignal이 있으면 그걸 우선 사용
  const externalSignal = opts.signal;
  const ctrl = externalSignal || new AbortController();
  const signal = ctrl.signal;

  // 외부 신호가 없을 때만 내부 타임아웃으로 abort
  const timer = externalSignal ? null : setTimeout(() => ctrl.abort(), timeoutMs);

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

    // 📝 Narrative only if selected
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

// ========== 에이전트 섹션 (/agent) ==========
let _agentCtrl = null;  // 직전 요청 취소용 컨트롤러

function renderNewsAnalysis(na, lang) {
  // 서버가 돌려주는 분석 오브젝트를 카드로 표시
  // na.overall: {score, label, pos, neg, neu, impact_score, top_keywords[]}
  const o = na?.overall || {};
  const label = (o.label || 'mixed').toUpperCase();
  const kw = (o.top_keywords || []).slice(0, 10).join(', ') || (lang==='ko'?'키워드 없음':'No keywords');
  const pos = o.pos ?? 0, neg = o.neg ?? 0, neu = o.neu ?? 0;

  return `
    <div class="ratio">
      <div><strong>${lang==='ko'?'언론 톤 요약':'Media Sentiment'}</strong>
        <span class="badge ${label==='BULLISH'?'BUY':label==='BEARISH'?'SELL':'HOLD'}">${label}</span>
      </div>
      <div class="mt-6">${lang==='ko'?'점수':'Score'}: ${o.score ?? 0}  •  Impact: ${o.impact_score ?? 0}</div>
      <div class="mt-6">${lang==='ko'?'기사 분포':'Articles'}: +${pos} / 0${neu} / -${neg}</div>
      <div class="mt-6">${lang==='ko'?'핵심 키워드':'Top keywords'}: ${kw}</div>
      ${na.note ? `<div class="mt-6 muted">${na.note}</div>` : ''}
    </div>
  `;
}

async function renderAgentExtras(ticker, lang, prefs){
  const predEl = $("#pred"), sumEl = $("#sum"), newsEl = $("#news");

  // 프리 상태 표시
  if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Loading prediction…</div>`;
  if (prefs.sum  && sumEl)  sumEl.textContent = '';
  if (prefs.news && newsEl) newsEl.innerHTML = `<li class="muted">Loading…</li>`;

  // 직전 요청 취소(연타/옵션 변경 대비)
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
    if (prefs.pred && predEl) {
      predEl.innerHTML = predCard(ag?.prediction || { symbol: ticker });
      predEl.closest('section')?.classList.remove('hidden');
    }

    // 🧠 Analyst summary
    if (prefs.sum && sumEl)  {
      const txt = (ag?.summary || '').trim();
      sumEl.textContent = txt || (lang === 'ko' ? '요약 없음' : 'No summary');
      sumEl.closest('section')?.classList.remove('hidden');
    }

    // 🗞 News / Analysis
    if (prefs.news && newsEl) {
      let html = '';
      // 1) 선호: 분석 객체(news_analysis)
      let na = (ag && ag.news_analysis && ag.news_analysis.overall) ? ag.news_analysis : null;
      // 2) 백업: 서버가 분석을 news에 담아 보내는 경우
      if (!na && ag && ag.news && !Array.isArray(ag.news) && ag.news.overall) na = ag.news;

      if (na) {
        // 분석 카드 렌더
        html = renderNewsAnalysis(na, lang);
      } else if (Array.isArray(ag?.news) && ag.news.length) {
        // 옛 포맷(헤드라인 배열)도 지원
        html = newsList(ag.news);
      } else {
        html = `<div class="muted">${lang==='ko'?'분석/뉴스 없음':'No media analysis available.'}</div>`;
      }
      newsEl.innerHTML = html;
      newsEl.closest('section')?.classList.remove('hidden');
    }

  }catch(e){
    if (e?.name === 'AbortError') {
      console.warn('[/agent] aborted');
    } else {
      console.error("[/agent] error", e);
    }
    if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Prediction unavailable.</div>`;
    if (prefs.sum  && sumEl)  sumEl.textContent = '';
    if (prefs.news && newsEl) newsEl.innerHTML  = `<li class="muted">News unavailable.</li>`;
  } finally {
    _agentCtrl = null;
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
