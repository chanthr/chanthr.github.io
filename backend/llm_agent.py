# llm_agent.py
import os, json, time, re, urllib.parse
from typing import Optional, List, Dict

import numpy as np
import pandas as pd
import yfinance as yf

# ───────── LLM (옵션) ─────────
try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    _HAVE_LLM = True
except Exception:
    _HAVE_LLM = False

from finance_agent import run_query as fa_run_query, pick_valid_ticker

# ───────── price_now (옵션: 없으면 폴백) ─────────
try:
    from brokers import price_now  # 프로젝트에 있으면 사용
except Exception:
    def price_now(symbol: str) -> Optional[float]:
        try:
            fi = (yf.Ticker(symbol).fast_info or {})
            lp = fi.get("last_price")
            return float(lp) if lp is not None else None
        except Exception:
            return None

# ───────── LLM 상태 ─────────
_LLM_PROVIDER = "none"
_LLM_REASON = None
def _build_model():
    global _LLM_PROVIDER, _LLM_REASON
    if not _HAVE_LLM:
        _LLM_REASON = "langchain_groq not installed"
        _LLM_PROVIDER = "none"
        return None
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model_name = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    if not key:
        _LLM_REASON = "GROQ_API_KEY missing"
        _LLM_PROVIDER = "none"
        return None
    try:
        m = ChatGroq(model=model_name, temperature=0.2, api_key=key)
        _LLM_PROVIDER = "groq"
        return m
    except Exception as e:
        _LLM_REASON = f"ChatGroq init failed: {e}"
        _LLM_PROVIDER = "none"
        return None

_model = _build_model()

def get_model_status() -> dict:
    return {"provider": _LLM_PROVIDER, "ready": bool(_model), "reason": _LLM_REASON}

# ───────── 간단 1D 예측 폴백 ─────────
def _predict_fallback(symbol: str) -> dict:
    df = yf.download(symbol, period="1y", interval="1d", auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df:
        raise RuntimeError("fallback: no price data")
    close = pd.to_numeric(df["Close"], errors="coerce").astype(float).dropna().values
    if close.size < 20:
        raise RuntimeError("fallback: not enough data")
    rets = np.diff(close) / close[:-1]
    tail = rets[-10:] if rets.size >= 10 else rets
    pred_ret = float(np.nanmean(tail))
    last = float(close[-1])
    pred_close = last * (1.0 + pred_ret)
    signal = "BUY" if pred_ret > 0.01 else ("SELL" if pred_ret < -0.01 else "HOLD")
    return {
        "symbol": symbol,
        "last_close": round(last, 4),
        "pred_ret_1d": round(pred_ret, 6),
        "pred_close_1d": round(pred_close, 4),
        "signal": signal,
        "ts": int(time.time()),
    }

# ───────── Google News RSS 파서 ─────────
def _unwrap_gnews_link(link: Optional[str]) -> Optional[str]:
    if not link: return link
    try:
        if "news.google.com" not in link: return link
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        u = (qs.get("url") or qs.get("u") or [None])[0]
        return u or link
    except Exception:
        return link

def _fetch_google_news_rss(query: str, language: str, k: int = 12) -> List[Dict]:
    is_ko = str(language).lower().startswith("ko")
    hl = "ko" if is_ko else "en-US"
    gl = "KR" if is_ko else "US"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    )
    try:
        import feedparser as _fp
    except Exception:
        return []
    feed = _fp.parse(url)
    out: List[Dict] = []
    for e in getattr(feed, "entries", [])[:k]:
        title = e.get("title")
        link = e.get("link") or (e.get("links", [{}])[0].get("href"))
        link = _unwrap_gnews_link(link)
        ts = None
        try:
            pp = getattr(e, "published_parsed", None)
            up = getattr(e, "updated_parsed", None)
            if pp: ts = int(time.mktime(pp))
            elif up: ts = int(time.mktime(up))
        except Exception:
            ts = None
        if title and link:
            out.append({"title": title, "link": link, "providerPublishTime": ts})
    return out

# ───────── 회사명 중심 쿼리 ─────────
_CORP_SUFFIX_RE = re.compile(
    r"\b(Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?|Limited|PLC|S\.?A\.?|N\.?V\.?|SE|AG|KK|GmbH|LLC|LP|Holdings?|Group|Company)\b\.?",
    flags=re.I,
)
def _clean_company_name(name: str) -> str:
    s = re.sub(r"[\(\)（）]", " ", name or "")
    s = _CORP_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or name

def _make_company_queries(company_name: str, symbol: str, language: str) -> List[str]:
    q: List[str] = []
    base = (company_name or "").strip()
    clean = _clean_company_name(base)
    if base: q.append(f"\"{base}\"")
    if clean and clean.lower() != base.lower():
        q.append(f"\"{clean}\"")
    if language.lower().startswith("ko"):
        topics = "발표 OR 출시 OR 인수 OR 합병 OR 제휴 OR 투자 OR 규제 OR 소송 OR 공급망 OR 실적발표"
    else:
        topics = "announcement OR launch OR acquisition OR merger OR partnership OR investment OR regulatory OR lawsuit OR supply chain OR earnings call"
    if base:  q.append(f"\"{base}\" ({topics})")
    if clean and clean.lower() != base.lower():
        q.append(f"\"{clean}\" ({topics})")
    if symbol: q.append(symbol)
    # de-dup
    seen, uniq = set(), []
    for s in q:
        key = s.lower()
        if key not in seen:
            seen.add(key); uniq.append(s)
    return uniq

def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 10) -> List[Dict]:
    items: List[Dict] = []
    if company_name:
        for q in _make_company_queries(company_name, symbol, language):
            try:
                items.extend(_fetch_google_news_rss(q, language, k=max(20, k * 2)))
            except Exception:
                continue
            if len(items) >= k: break
    else:
        try:
            items.extend(_fetch_google_news_rss(symbol, language, k=max(20, k * 2)))
        except Exception:
            pass
    # yfinance 보강
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[: max(10, k)]:
            title = n.get("title")
            link = _unwrap_gnews_link(n.get("link"))
            ts = n.get("providerPublishTime") or n.get("pubTime")
            try: ts = int(ts) if ts is not None else None
            except Exception: ts = None
            if title and link:
                items.append({"title": title, "link": link, "providerPublishTime": ts})
    except Exception:
        pass
    # 정리
    clean, seen = [], set()
    for it in items:
        title = (it.get("title") or "").strip()
        link  = _unwrap_gnews_link(it.get("link"))
        ts    = it.get("providerPublishTime")
        if not title or not link: continue
        key = (title.lower(), link)
        if key in seen: continue
        seen.add(key)
        if ts is not None and not isinstance(ts, (int, float)):
            try: ts = int(ts)
            except Exception: ts = None
        clean.append({"title": title, "link": link, "providerPublishTime": ts})
    clean.sort(key=lambda x: x.get("providerPublishTime") or 0, reverse=True)
    return clean[:k]

# ───────── 키워드/감성/임팩트 태깅 상수 ───────── #
_STOP_EN = {
    "the","a","an","and","or","for","of","to","in","on","with","at","by","from",
    "company","inc","corp","co","ltd","plc","group","shares","stock","reports",
    "earnings","news","today","update"
}
_STOP_KO = {"및","그리고","또","더","관련","회사","기업","주가","증권","속보","뉴스","발표","오늘","보고"}

_POS_TERMS_EN = {
    "beat": 1.0, "beats": 1.0, "surge": 1.0, "surges": 1.0, "jump": 0.9, "jumps": 0.9,
    "record": 0.8, "upgrade": 0.8, "raises": 0.7, "raise": 0.7, "strong": 0.6,
    "expand": 0.5, "expands": 0.5, "approval": 1.0, "approved": 1.0, "partnership": 0.6,
    "wins": 0.8, "win": 0.8, "profit": 0.6, "growth": 0.6, "upbeat": 0.6
}
_NEG_TERMS_EN = {
    "miss": -1.0, "misses": -1.0, "plunge": -1.0, "plunges": -1.0, "drop": -0.9, "drops": -0.9,
    "downgrade": -0.8, "cuts": -0.8, "cut": -0.8, "layoff": -0.9, "layoffs": -0.9,
    "lawsuit": -0.9, "recall": -0.9, "investigation": -0.8, "probe": -0.8,
    "warning": -0.7, "ban": -0.7, "halt": -0.7, "bankruptcy": -1.0, "fraud": -1.0, "scandal": -1.0
}
_POS_TERMS_KO = {
    "호실적":1.0,"급등":1.0,"반등":0.9,"상향":0.8,"승인":1.0,"허가":1.0,"수주":0.8,
    "확대":0.6,"성장":0.6,"개선":0.6,"기록":0.6,"합의":0.5,"제휴":0.6,"계약":0.7
}
_NEG_TERMS_KO = {
    "부진":-0.9,"급락":-1.0,"하락":-0.8,"하향":-0.8,"경고":-0.7,"소송":-0.9,"리콜":-0.9,
    "감원":-0.9,"파산":-1.0,"조사":-0.8,"규제":-0.7,"적자":-0.9,"미달":-0.9,"철수":-0.8
}
_IMPACT_TAGS = [
    (r"\b(earnings|results|eps|revenue|guidance|outlook)\b", "Earnings/Guidance", 1.0),
    (r"\b(acquisition|acquires|merger|m&a|deal)\b", "M&A", 1.0),
    (r"\b(partnership|alliance|collaboration)\b", "Partnership", 0.7),
    (r"\b(lawsuit|legal|settlement)\b", "Legal", 0.8),
    (r"\b(recall|ban|regulation|approved|approval)\b", "Regulatory", 0.9),
    (r"\b(layoff|job cuts|restructuring)\b", "Workforce", 0.7),
    (r"\b(supply chain|shortage|disruption)\b", "Supply chain", 0.7),
]
_IMPACT_TAGS_KO = [
    (r"(실적|가이던스|전망)", "Earnings/Guidance", 1.0),
    (r"(인수|합병|m&a|딜)", "M&A", 1.0),
    (r"(제휴|협력|파트너십)", "Partnership", 0.7),
    (r"(소송|법적|합의)", "Legal", 0.8),
    (r"(리콜|규제|승인|허가|금지)", "Regulatory", 0.9),
    (r"(감원|구조조정)", "Workforce", 0.7),
    (r"(공급망|부족|차질)", "Supply chain", 0.7),
]

# ───────── 키워드/감성/임팩트 ─────────
def _extract_keywords(title: str, language: str, max_k: int = 5) -> List[str]:
    if not title: return []
    s = re.sub(r"[^\w가-힣\s\-]+", " ", title.lower())
    toks = [t.strip("-_") for t in s.split() if 2 <= len(t) <= 20 and not t.isdigit()]
    if language.lower().startswith("ko"):
        toks = [t for t in toks if t not in _STOP_KO]
    else:
        toks = [t for t in toks if t not in _STOP_EN]
    freq: Dict[str,int] = {}
    for t in toks: freq[t] = freq.get(t, 0) + 1
    return [k for k,_ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:max_k]]

def _score_title_sentiment(title: str, language: str) -> float:
    if not title: return 0.0
    t = title.lower()
    score = 0.0
    if language.lower().startswith("ko"):
        for k,v in _POS_TERMS_KO.items():
            if k in title: score += v
        for k,v in _NEG_TERMS_KO.items():
            if k in title: score += v
    else:
        for k,v in _POS_TERMS_EN.items():
            if k in t: score += v
        for k,v in _NEG_TERMS_EN.items():
            if k in t: score += v
    try:
        import math
        return math.tanh(score / 3.0)
    except Exception:
        return max(-1.0, min(1.0, score / 3.0))

def _tag_impacts(title: str, language: str) -> List[str]:
    tags = []
    arr = _IMPACT_TAGS_KO if language.lower().startswith("ko") else _IMPACT_TAGS
    for pat, name, _w in arr:
        try:
            if re.search(pat, title, flags=re.I):
                tags.append(name)
        except Exception:
            continue
    return sorted(list(set(tags)))

def _impact_weight_for_tags(tags: List[str], language: str) -> float:
    arr = _IMPACT_TAGS_KO if language.lower().startswith("ko") else _IMPACT_TAGS
    m = {name: w for (_pat, name, w) in arr}
    return sum(m.get(t, 0.0) for t in tags)

def _analyze_news(items: List[Dict], language: str) -> Dict:
    if not items:
        return {"overall":{"score":0.0,"label":"neutral","pos":0,"neg":0,"neu":0,
                           "impact_score":0.0,"top_keywords":[]}, "items":[]}
    import math, time as _time
    now = _time.time()
    rows, pos, neg, neu = [], 0, 0, 0
    all_kw: List[str] = []
    w_sum = w_score = w_impact = 0.0
    for it in items:
        title = (it.get("title") or "").strip()
        ts = it.get("providerPublishTime") or 0
        link = it.get("link")
        s = _score_title_sentiment(title, language)
        lbl = "pos" if s > 0.15 else ("neg" if s < -0.15 else "neu")
        if lbl=="pos": pos += 1
        elif lbl=="neg": neg += 1
        else: neu += 1
        tags = _tag_impacts(title, language)
        impact = _impact_weight_for_tags(tags, language)
        age_days = 0.0
        if ts:
            try: age_days = max(0.0, (now - float(ts))/86400.0)
            except Exception: age_days = 0.0
        w = math.exp(-age_days / 7.0)
        w_sum += w
        w_score += w * s
        w_impact += w * (s + 0.2 * impact)
        kws = _extract_keywords(title, language)
        all_kw.extend(kws)
        rows.append({
            "title": title, "link": link, "ts": ts,
            "sentiment": round(float(s), 3), "label": lbl,
            "impact_tags": tags, "keywords": kws
        })
    avg = (w_score / w_sum) if w_sum else 0.0
    impact_score = (w_impact / w_sum) if w_sum else 0.0
    if   avg > 0.15: label = "bullish"
    elif avg < -0.15: label = "bearish"
    else: label = "mixed"
    kw_freq: Dict[str,int] = {}
    for k in all_kw: kw_freq[k] = kw_freq.get(k, 0) + 1
    top_kw = [k for k,_ in sorted(kw_freq.items(), key=lambda x: (-x[1], x[0]))[:10]]
    return {
        "overall": {
            "score": round(float(avg),3), "label": label,
            "pos": pos, "neg": neg, "neu": neu,
            "impact_score": round(float(impact_score),3),
            "top_keywords": top_kw
        },
        "items": rows
    }

def _news_summary_llm(analysis: Dict, language: str) -> Optional[str]:
    if _model is None: return None
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an equity analyst writing a brief press-tone note. Write in {ask_lang}. "
         "Summarize media sentiment and key themes in one concise sentence."),
        ("human", "DATA(JSON): {blob}\nReturn only one sentence.")
    ])
    chain = prompt | _model | StrOutputParser()
    try:
        txt = chain.invoke({"ask_lang": ask_lang, "blob": json.dumps(analysis, ensure_ascii=False)})
        return re.sub(r"\s+", " ", str(txt)).strip()[:280]
    except Exception:
        return None

# ───────── IB 톤 요약 ─────────
def _ib_style_summary_rule(ana: dict, pred: Optional[dict], language: str) -> str:
    r = (ana or {}).get("core", {}).get("ratios", {})
    liq = r.get("Liquidity", {}) or {}
    sol = r.get("Solvency", {}) or {}
    def val(node):
        v = (node or {}).get("value")
        return None if v is None else float(v)
    cr, qr, cash = val(liq.get("current_ratio")), val(liq.get("quick_ratio")), val(liq.get("cash_ratio"))
    de, dr, ic = val(sol.get("debt_to_equity")), val(sol.get("debt_ratio")), val(sol.get("interest_coverage"))
    if language[:2] == "ko":
        lines = []
        if cr is not None and qr is not None:
            lines.append(f"유동성은 유동비율 {cr:.2f}, 당좌비율 {qr:.2f}로 단기지급능력은 {'양호' if cr>=1.5 else '보통'}합니다.")
        else:
            lines.append("유동성 지표가 제한적으로 제공됩니다.")
        lines.append(f"건전성은 D/E {de:.2f}, 부채비율 {dr:.2f}, 이자보상배율 {ic:.2f}로 {'보수적' if (de and de<=1.0 and (ic and ic>=5)) else '중립'}입니다.")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"]); sig = pred.get("signal","HOLD")
            lines.append(f"단기(1D) 트레이딩 시그널은 {sig}({p*100:+.2f}%)이며, 참고 지표로만 활용을 권고합니다.")
        else:
            lines.append("단기(1D) 예측은 데이터 부족 시 미표시될 수 있습니다.")
        return " ".join(lines)
    else:
        lines = []
        if cr is not None and qr is not None:
            lines.append(f"Liquidity is {'solid' if cr>=1.5 else 'adequate'} (Current {cr:.2f}, Quick {qr:.2f}).")
        else:
            lines.append("Liquidity metrics are limited.")
        lines.append(f"Balance sheet looks {'conservative' if (de and de<=1.0 and (ic and ic>=5)) else 'neutral'} (D/E {de:.2f}, Debt {dr:.2f}, IC {ic:.2f}).")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"]); sig = pred.get("signal","HOLD")
            lines.append(f"1-day tactical signal: {sig} ({p*100:+.2f}%), for trading color only.")
        else:
            lines.append("1-day prediction may be unavailable when data is insufficient.")
        return " ".join(lines)

def _ib_style_summary_llm(ana: dict, pred: Optional[dict], language: str) -> Optional[str]:
    if _model is None: return None
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an investment-banking equity analyst. Write in {ask_lang}. "
         "Deliver a crisp 2–3 sentence note covering: liquidity stance, solvency/leverage, and a tactical 1-day signal if provided. "
         "Use a professional tone and cite key ratios once. No bullet points, no markdown."),
        ("human", "DATA(JSON):\n{blob}\n\nReturn only the prose text (2–3 sentences).")
    ])
    chain = prompt | _model | StrOutputParser()
    try:
        txt = chain.invoke({"ask_lang": ask_lang, "blob": json.dumps({"analysis": ana, "prediction": pred}, ensure_ascii=False)})
        txt = re.sub(r"\s+", " ", re.sub(r"`+|#+", " ", str(txt))).strip()
        return txt[:600]
    except Exception:
        return None

# ───────── 메인 ─────────
def run_manager(query: str, language: str = "ko", include_news: bool = True) -> dict:
    sym = pick_valid_ticker(query)
    ana = fa_run_query(query, language=language)

    # 예측
    try:
        from predictor import predict_one
        try:
            pred = predict_one(sym, force=False)
        except Exception as e_model:
            try:
                pred = _predict_fallback(sym)
            except Exception as e_fb:
                pred = {"symbol": sym, "signal": "HOLD",
                        "error": f"predict_failed:{type(e_model).__name__}; fallback_failed:{type(e_fb).__name__}: {e_fb}"}
    except Exception as e_import:
        try:
            pred = _predict_fallback(sym)
        except Exception as e_fb:
            pred = {"symbol": sym, "signal": "HOLD",
                    "error": f"predict_import_failed:{type(e_import).__name__}; fallback_failed:{type(e_fb).__name__}: {e_fb}"}

    # 라이브가격 (있을 때만)
    try:
        live = price_now(sym)
        if live is not None:
            pred["live_price"] = round(float(live), 4)
    except Exception:
        pass

    # 뉴스
    try:
        news = _news_enriched(sym, language, company_name=(ana.get("core") or {}).get("company"), k=40) if include_news else []
    except Exception:
        news = []

    # 뉴스 분석 + (옵션) LLM 한줄
    news_analysis = _analyze_news(news, language)
    na_note = _news_summary_llm(news_analysis, language)
    if na_note:
        news_analysis["note"] = na_note

    # 재무 요약
    try:
        text = _ib_style_summary_llm(ana, pred, language) or _ib_style_summary_rule(ana, pred, language)
    except Exception:
        text = _ib_style_summary_rule(ana, pred, language)

    return {
        "ticker": ana["core"]["ticker"],
        "company": ana["core"]["company"],
        "price": ana["core"]["price"],
        "analysis": ana,
        "prediction": pred,
        "news":  news_analysis, # ✅ 추가: 미디어 톤/키워드/임팩트
        "summary": text,
        "meta": {
            "llm_provider": _LLM_PROVIDER,
            "llm_ready": bool(_model),
        }
    }

__all__ = ["run_manager", "get_model_status"]
