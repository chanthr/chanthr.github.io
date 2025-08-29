// 🔧 API base
const API_BASE = "https://chanthr-github-io.onrender.com";
const $ = (s, el = document) => el.querySelector(s);

/* ---------- 1) CSS 폴백 (선택) ---------- */
const FALLBACK_CSS = `
:root{--bg:#0f1117;--card:#111827;--text:#e5e7eb;--muted:#9ca3af;--border:#334155}
html,body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;padding:0}
.wrap{max-width:980px;margin:0 auto;padding:24px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;margin-top:16px;box-shadow:0 4px 20px rgba(0,0,0,.25)}
.row{display:flex;gap:8px;flex-wrap:wrap}.align-center{align-items:center}.flex-1{flex:1}
input,select,button{padding:10px 12px;border-radius:10px;border:1px solid var(--border);background:var(--card);color:var(--text)}button{cursor:pointer}
.muted{color:var(--muted);font-size:13px}
.grid{display:grid;gap:12px}.grid-3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.ratio{border:1px solid var(--border);border-radius:12px;padding:12px}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;background:#334155;font-size:12px;margin-left:6px}
.badge.Strong{background:#10b981}.badge.Fair{background:#f59e0b}.badge.Weak{background:#ef4444}
pre{white-space:pre-wrap;background:#0b1220;padding:12px;border-radius:12px;overflow:auto;border:1px solid var(--border)}
a{color:#93c5fd}.hidden{display:none}.mt-6{margin-top:6px}.mt-8{margin-top:8px}.mt-12{margin-top:12px}.mb-8{margin-bottom:8px}
.json-wrap{margin-top:8px}
.json-toggle .checkbox{display:inline-flex;gap:8px;align-items:center;font-size:14px;user-select:none}
.watermark{position:fixed;left:0;right:0;bottom:8px;text-align:center;color:var(--muted);opacity:.35;font-size:12px;letter-spacing:.02em;user-select:none;pointer-events:none}
`;
function ensureCssLoaded(){
  const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  if (!bg) {
    const style = document.createElement('style');
    style.setAttribute('data-fallback', 'true');
    style.textContent = FALLBACK_CSS;
    document.head.appendChild(style);
  }
}

/* ---------- 2) UI helpers ---------- */
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

/* ---------- 3) 에이전트 부가 섹션 ---------- */
const fmtPct = (x) => (x == null || isNaN(x))
  ? 'N/A'
  : (x >= 0 ? '+' : '') + (Number(x) * 100).toFixed(2) + '%';

function predCard(p = {}){
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

async function renderAgentExtras(ticker, lang){
  const predEl = $("#pred"), sumEl = $("#sum"), newsEl = $("#news");
  if (predEl) predEl.innerHTML = `<div class="muted">Loading prediction…</div>`;
  if (sumEl)  sumEl.textContent = '';
  if (newsEl) newsEl.innerHTML = '';
  // 1) /agent 우선
  try{
    const r = await fetch(`${API_BASE}/agent`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ query: `${ticker} 유동성/건전성 + 1D 예측`, language: lang, include_news: true })
    });
    if(!r.ok) throw new Error('agent');
    const ag = await r.json();
    if (predEl) predEl.innerHTML = predCard(ag.prediction || { symbol: ticker });
    if (sumEl)  sumEl.textContent = (ag.summary || '').trim() || (lang === 'ko' ? '요약 없음' : 'No summary');
    if (newsEl) newsEl.innerHTML  = newsList(ag.news);
    return;
  }catch(_){}
  // 2) 폴백: /predict
  try{
    const pr = await fetch(`${API_BASE}/predict`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ symbol: ticker, force: false })
    });
    if (pr.ok) {
      const p = await pr.json();
      if (predEl) predEl.innerHTML = predCard(p);
    } else if (predEl) {
      predEl.innerHTML = `<div class="muted">Prediction unavailable.</div>`;
    }
  }catch(e){
    if (predEl) predEl.innerHTML = `<div class="muted">Prediction unavailable.</div>`;
  }
}

/* ---------- 4) 기존 analyse 그대로 ---------- */
async function checkHealth(){
  try{
    const r = await fetch(`${API_BASE}/health`, { cache: 'no-store' });
    const data = await r.json();
    $("#health").textContent = data?.status === 'ok' ? 'OK' : '오류';
  }catch(e){
    $("#health").textContent = '접속 실패';
  }
}

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

/* ---------- 5) 기존 유지 + 에이전트 추가 호출 ---------- */
async function analyseWithExtras(){
  await analyse();  // 기존 흐름 유지
  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;
  renderAgentExtras(t, lang); // 추가 섹션 비동기 렌더
}

/* ---------- 6) Boot ---------- */
document.addEventListener('DOMContentLoaded', () => {
  ensureCssLoaded();              // 폴백 스타일 보강(선택)
  checkHealth();

  // ✅ 중복 바인딩 방지: analyseWithExtras만 연결
  $("#go").addEventListener('click', analyseWithExtras);
  $("#ticker").addEventListener('keydown', (e)=>{ if(e.key==='Enter') analyseWithExtras(); });

  const toggle = $("#toggle-json");
  if (toggle) {
    toggle.addEventListener('change', (e)=>{
      $("#jsonWrap").classList.toggle('hidden', !e.target.checked);
    });
  }
});
