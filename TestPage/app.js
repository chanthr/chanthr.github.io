// 🔧 Render의 FastAPI 베이스 URL (api.py에 /agent가 있어야 함)
const API_BASE = "https://chanthr-github-io.onrender.com";

const $ = (s, el = document) => el.querySelector(s);

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

const fmtPct = (x) => (x == null || isNaN(x)) ? 'N/A'
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
  // yfinance 뉴스 pubTime(초) 기준
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
    const when = fmtTime(n.pubTime);
    return `<li><a href="${link}" target="_blank" rel="noopener">${t}</a>${when ? ` <time>· ${when}</time>`:''}</li>`;
  }).join('');
}

async function checkHealth(){
  try{
    const r = await fetch(`${API_BASE}/health`, { cache: 'no-store' });
    const data = await r.json();
    $("#health").textContent = data?.status === 'ok' ? 'OK' : '오류';
  }catch(e){
    $("#health").textContent = '접속 실패';
  }
}

async function runAgent(){
  const goBtn = $("#go");
  const t = $("#ticker").value.trim().toUpperCase();
  const lang = $("#lang").value;
  if(!t){ alert('Ticker Symbol of the company.'); return; }

  goBtn.disabled = true;
  goBtn.textContent = '⏳ Analysing...';
  $("#out").classList.add('hidden');

  // 초기화
  $("#liq").innerHTML = "";
  $("#sol").innerHTML = "";
  $("#pred").innerHTML = "";
  $("#narr").innerHTML = "";
  $("#sum").textContent = "";
  $("#news").innerHTML = "";

  try{
    const res = await fetch(`${API_BASE}/agent`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ query: `${t} 유동성/건전성 + 1D 예측`, language: lang, include_news: true })
    });
    if(!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const ana = data.analysis || {};
    const core = ana.core || {};
    const ratios = core.ratios || {};

    // 헤더/메타
    const price = data.price ?? core.price ?? 'N/A';
    $("#title").textContent = `${core.company || '-'} (${core.ticker || data.ticker || '-'})`;
    $("#meta").textContent = `Last Price: ${price}  •  Source: ${ana.meta?.source || '—'}`;

    // 비율 카드
    const liq = ratios.Liquidity || {};
    const sol = ratios.Solvency || {};
    $("#liq").innerHTML = [
      ratioCard('Current Ratio', liq.current_ratio),
      ratioCard('Quick Ratio', liq.quick_ratio),
      ratioCard('Cash Ratio', liq.cash_ratio),
    ].join('');
    $("#sol").innerHTML = [
      ratioCard('Debt-to-Equity', sol.debt_to_equity),
      ratioCard('Debt Ratio', sol.debt_ratio),
      ratioCard('Interest Coverage', sol.interest_coverage),
    ].join('');

    // 예측
    $("#pred").innerHTML = predCard(data.prediction);

    // 요약 (LLM)
    $("#sum").textContent = (data.summary || '').trim() || (lang === 'ko' ? '요약 없음' : 'No summary');

    // 내러티브 (마크다운 지원)
    const md = (ana.explanation || '').trim();
    if (window.marked) { $("#narr").innerHTML = marked.parse(md); }
    else { $("#narr").textContent = md; }

    // 뉴스
    $("#news").innerHTML = newsList(data.news);

    // Raw JSON
    $("#raw").textContent = JSON.stringify(data, null, 2);

    // 표시
    $("#out").classList.remove('hidden');
  }catch(e){
    alert('요청 실패: ' + e.message + '\n(API_BASE와 /agent 배포 상태를 확인하세요)');
  }finally{
    goBtn.disabled = false;
    goBtn.textContent = '🔎 Analyse';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  $("#go").addEventListener('click', runAgent);
  $("#ticker").addEventListener('keydown', (e)=>{ if(e.key==='Enter') runAgent(); });
  $("#toggle-json").addEventListener('change', (e)=>{
    $("#jsonWrap").classList.toggle('hidden', !e.target.checked);
  });
});
