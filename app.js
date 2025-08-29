// 🔧 API base
const API_BASE = "https://chanthr-github-io.onrender.com";
const $ = (s, el = document) => el.querySelector(s);

// ========== UI helpers ==========
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

// ========== 옵션 읽기 & 섹션 표시 ==========
function getPrefs(){
  const pred = $("#opt-pred")?.checked ?? false;
  const sum  = $("#opt-sum")?.checked  ?? false;
  const news = $("#opt-news")?.checked ?? false;
  return { pred, sum, news };
}
function applySectionVisibility(p){
  const S = {
    pred: $("#pred-section"),
    sum:  $("#sum-section"),
    news: $("#news-section"),
  };
  if (S.pred) S.pred.classList.toggle('hidden', !p.pred);
  if (S.sum)  S.sum.classList.toggle('hidden',  !p.sum);
  if (S.news) S.news.classList.toggle('hidden', !p.news);
}

// ========== Health ==========
async function checkHealth(){
  try{
    const r = await fetch(`${API_BASE}/health`, { cache: 'no-store' });
    const data = await r.json();
    $("#health").textContent = data?.status === 'ok' ? 'OK' : '오류';
  }catch(e){
    $("#health").textContent = '접속 실패';
  }
}

// ========== 기본 분석 (/analyse) ==========
async function analyse(){
  const goBtn = $("#go");
  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;
  if(!t){ alert('Ticker Symbol of the company.'); return; }

  goBtn.disabled = true; 
  goBtn.textContent = '⏳ Analysing...';
  $("#out").classList.add('hidden');

  try{
    const res = await fetch(`${API_BASE}/analyse`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ query: `${t} 유동성/건전성 평가`, language: lang })
    });
    if(!res.ok){ throw new Error(`HTTP ${res.status}`); }
    const data = await res.json();

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
    alert('분석 실패: ' + e.message + '\n(API_BASE 확인 및 /health 체크)');
  }finally{
    goBtn.disabled = false; 
    goBtn.textContent = '🔎 Analyse';
  }
}

// ========== 에이전트 섹션 (/agent) ==========
async function renderAgentExtras(ticker, lang, prefs){
  const predEl = $("#pred"), sumEl = $("#sum"), newsEl = $("#news");
  // 준비 상태
  if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Loading prediction…</div>`;
  if (prefs.sum  && sumEl)  sumEl.textContent = '';
  if (prefs.news && newsEl) newsEl.innerHTML = '';

  try{
    const r = await fetch(`${API_BASE}/agent`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        query: `${ticker} 유동성/건전성 + 1D 예측`,
        language: lang,
        include_news: !!prefs.news
      })
    });
    const ag = await r.json();
    console.log("[/agent]", ag);

    if (prefs.pred && predEl) predEl.innerHTML = predCard(ag.prediction || { symbol: ticker });
    if (prefs.sum  && sumEl)  sumEl.textContent = (ag.summary || '').trim() || (lang === 'ko' ? '요약 없음' : 'No summary');

    if (prefs.news && newsEl) {
      if (Array.isArray(ag.news) && ag.news.length) {
        newsEl.innerHTML = newsList(ag.news);
      } else {
        newsEl.innerHTML = `<li class="muted">No recent headlines.</li>`;
      }
    }
  }catch(e){
    console.error("agent error", e);
    if (prefs.pred && predEl) predEl.innerHTML = `<div class="muted">Prediction unavailable.</div>`;
    if (prefs.sum  && sumEl)  sumEl.textContent = '';
    if (prefs.news && newsEl) newsEl.innerHTML  = `<li class="muted">News unavailable.</li>`;
  }
}

// ========== 메인 플로우 ==========
async function analyseWithExtras(){
  const prefs = getPrefs();
  applySectionVisibility(prefs);      // ✅ 클릭 즉시 섹션 show/hide 반영

  await analyse();                    // 재무 분석

  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;

  // 아무것도 선택 안 했으면 추가 호출 X
  if (!prefs.pred && !prefs.sum && !prefs.news) return;

  // 선택된 항목만 렌더
  await renderAgentExtras(t, lang, prefs);
}

// ========== Boot ==========
document.addEventListener('DOMContentLoaded', () => {
  // 초기 상태: 체크 해제 → 섹션 숨김
  applySectionVisibility(getPrefs());
  checkHealth();

  // 🔴 중복 바인딩 없이 오직 analyseWithExtras만 연결
  $("#go").addEventListener('click', analyseWithExtras);
  $("#ticker").addEventListener('keydown', (e)=>{ if(e.key==='Enter') analyseWithExtras(); });

  // JSON 토글
  const toggle = $("#toggle-json");
  if (toggle) {
    toggle.addEventListener('change', (e)=>{
      $("#jsonWrap").classList.toggle('hidden', !e.target.checked);
    });
  }

  // 체크박스 바꾸면 섹션 가시성 즉시 반영(검색 전에 미리 보여주고/숨김)
  ["#opt-pred","#opt-sum","#opt-news"].forEach(id=>{
    const el = $(id);
    if (el) el.addEventListener('change', ()=> applySectionVisibility(getPrefs()));
  });
});
