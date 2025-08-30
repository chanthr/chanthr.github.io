# llm_agent.py
import os, json, time, re, urllib.parse
from typing import Optional, List, Dict

import numpy as np
import pandas as pd
import yfinance as yf
import feedparser

# 외부 모듈(LLM)은 선택사항: 없으면 요약은 규칙기반으로
try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    _HAVE_LLM = True
except Exception:
    _HAVE_LLM = False

# 로컬 모듈
from finance_agent import run_query as fa_run_query, pick_valid_ticker

# brokers.price_now는 선택사항 (없으면 None 반환)
try:
    from brokers import price_now
except Exception:
    def price_now(symbol: str) -> Optional[float]:
        return None


# ---------------- LLM 모델 (옵션) ----------------
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
        _LLM_PROVIDER = "groq"   # ✅ Groq 사용
        return m
    except Exception as e:
        _LLM_REASON = f"ChatGroq init failed: {e}"
        _LLM_PROVIDER = "none"
        return None

_model = _build_model()

# ✅ 추가: 에이전트 LLM 상태
def get_model_status() -> dict:
    return {"provider": _LLM_PROVIDER, "ready": bool(_model), "reason": _LLM_REASON}
    

# ---------------- 안전한 1D 예측 폴백 ----------------
def _predict_fallback(symbol: str) -> dict:
    """
    간단한 통계 기반 1D 예측(의존성 최소화).
    최근 10개 일간 수익률 평균을 다음 날 기대수익률로 사용.
    """
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


# ---------------- 뉴스 수집 (폴백) ----------------
# ---------------- Google News helpers (링크 언랩/피드 파싱) ----------------
def _unwrap_gnews_link(link: Optional[str]) -> Optional[str]:
    """Google News RSS 링크를 실제 퍼블리셔 기사 URL로 언랩."""
    if not link:
        return link
    try:
        if "news.google.com" not in link:
            return link
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        u = (qs.get("url") or qs.get("u") or [None])[0]
        return u or link
    except Exception:
        return link


def _fetch_google_news_rss(query: str, language: str, k: int = 12) -> List[Dict]:
    """Google News RSS에서 최대 k개 가져오기 (published/updated 모두 처리)."""
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
            if pp:
                ts = int(time.mktime(pp))
            elif up:
                ts = int(time.mktime(up))
        except Exception:
            ts = None
        if title and link:
            out.append({"title": title, "link": link, "providerPublishTime": ts})
    return out


# ---------------- 회사명 기반 쿼리 생성 ----------------
_CORP_SUFFIX_RE = re.compile(
    r"\b(Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?|Limited|PLC|S\.?A\.?|N\.?V\.?|SE|AG|KK|GmbH|LLC|LP|Holdings?|Group|Company)\b\.?",
    flags=re.I,
)

def _clean_company_name(name: str) -> str:
    """법인 접미사/괄호 제거, 여백 정리."""
    s = re.sub(r"[\(\)（）]", " ", name or "")
    s = _CORP_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or name


def _make_company_queries(company_name: str, symbol: str, language: str) -> List[str]:
    """
    우선순위:
    1) "정확 회사명" (큰따옴표)
    2) "정리된 회사명" (법인접미사 제거)
    3) 일반 이슈 키워드 확장 (주가/stock 제외)
    4) (마지막 수단) 심볼 단독
    """
    q: List[str] = []
    base = company_name.strip()
    clean = _clean_company_name(base)

    # 1) 정확 매칭 우선
    q.append(f"\"{base}\"")
    if clean and clean.lower() != base.lower():
        q.append(f"\"{clean}\"")

    # 2) 일반 이슈 토픽 확장 (언어별)
    if language.lower().startswith("ko"):
        topics = "발표 OR 출시 OR 인수 OR 합병 OR 제휴 OR 투자 OR 규제 OR 소송 OR 공급망 OR 실적발표"
    else:
        topics = "announcement OR launch OR acquisition OR merger OR partnership OR investment OR regulatory OR lawsuit OR supply chain OR earnings call"
    q.append(f"\"{base}\" ({topics})")
    if clean and clean.lower() != base.lower():
        q.append(f"\"{clean}\" ({topics})")

    # 3) 마지막 수단: 티커 자체 (주가/stock 같은 단어는 붙이지 않음)
    if symbol:
        q.append(symbol)

    # 중복 제거, 순서 유지
    seen = set()
    uniq = []
    for s in q:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq


# ---------------- 뉴스(yfinance + Google News, 회사명 우선) ----------------
def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 10) -> List[Dict]:
    """
    회사명 중심으로 최신 이슈 뉴스 수집:
      - Google News: 회사명 정확 매칭 + 일반 이슈 토픽 확장
      - 부족 시 yfinance 뉴스 보강
      - 제목/링크 중복 제거, 시간 역순 정렬
    """
    items: List[Dict] = []

    # 1) 회사명 우선 Google News
    if company_name:
        for q in _make_company_queries(company_name, symbol, language):
            try:
                items.extend(_fetch_google_news_rss(q, language, k=max(20, k * 2)))
            except Exception:
                continue
            if len(items) >= k:
                break
    else:
        # 회사명이 없는 경우 심볼로만 시도
        try:
            items.extend(_fetch_google_news_rss(symbol, language, k=max(20, k * 2)))
        except Exception:
            pass

    # 2) yfinance 뉴스 보강 (마켓 뉴스가 섞여도 최근성 측면에서 유용)
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[: max(10, k)]:
            title = n.get("title")
            link = _unwrap_gnews_link(n.get("link"))
            ts = n.get("providerPublishTime") or n.get("pubTime")
            try:
                ts = int(ts) if ts is not None else None
            except Exception:
                ts = None
            if title and link:
                items.append({"title": title, "link": link, "providerPublishTime": ts})
    except Exception:
        pass

    # 3) 정리: 중복 제거 + 최신순 정렬
    clean: List[Dict] = []
    seen = set()
    for it in items:
        title = (it.get("title") or "").strip()
        link = _unwrap_gnews_link(it.get("link"))
        ts = it.get("providerPublishTime")
        if not title or not link:
            continue
        key = (title.lower(), link)
        if key in seen:
            continue
        seen.add(key)
        # ts 정규화
        if ts is not None and not isinstance(ts, (int, float)):
            try:
                ts = int(ts)
            except Exception:
                ts = None
        clean.append({"title": title, "link": link, "providerPublishTime": ts})

    # 최신순
    clean.sort(key=lambda x: x.get("providerPublishTime") or 0, reverse=True)
    return clean[:k]

# ---------------- IB 애널리스트 톤 요약 ----------------
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
            p = float(pred["pred_ret_1d"])
            sig = pred.get("signal","HOLD")
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
    if _model is None:
        return None
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


# ---------------- 메인 집계기 ----------------
def run_manager(query: str, language: str = "ko", include_news: bool = True) -> dict:
    sym = pick_valid_ticker(query)
    ana = fa_run_query(query, language=language)

    # 1) 예측: 모델 → 폴백 → 최종 안전값
    try:
        from predictor import predict_one  # 로컬 모델이 있으면 사용
        try:
            pred = predict_one(sym, force=False)
        except Exception as e_model:
            try:
                pred = _predict_fallback(sym)
            except Exception as e_fb:
                pred = {
                    "symbol": sym,
                    "signal": "HOLD",
                    "error": f"predict_failed:{type(e_model).__name__}; fallback_failed:{type(e_fb).__name__}: {e_fb}"
                }
    except Exception as e_import:
        # predictor 모듈이 아예 없을 때도 안전하게
        try:
            pred = _predict_fallback(sym)
        except Exception as e_fb:
            pred = {
                "symbol": sym,
                "signal": "HOLD",
                "error": f"predict_import_failed:{type(e_import).__name__}; fallback_failed:{type(e_fb).__name__}: {e_fb}"
            }

    # 2) 라이브가: 완전 방탄
    try:
        live = price_now(sym)
        if live is not None:
            pred["live_price"] = round(float(live), 4)
    except Exception:
        pass

    # 3) 뉴스: 실패해도 항상 리스트
    try:
        news = _news_enriched(
            sym, language,
            company_name=(ana.get("core") or {}).get("company"),
            k=10
        ) if include_news else []
    except Exception:
        news = []

    # 4) 요약: LLM → 규칙기반, 이것도 방탄
    try:
        text = _ib_style_summary_llm(ana, pred, language) or _ib_style_summary_rule(ana, pred, language)
    except Exception:
        text = _ib_style_summary_rule(ana, pred, language)

    # 5) 안전한 리턴(필드 항상 존재)
    core = ana.get("core") or {}
    return {
        "ticker": ana["core"]["ticker"],
        "company": ana["core"]["company"],
        "price": ana["core"]["price"],
        "analysis": ana,
        "prediction": pred,
        "news": news,
        "summary": text,
        "meta": {                         # ✅ 추가
            "llm_provider": _LLM_PROVIDER,
            "llm_ready": bool(_model),
        }
    }

__all__ = ["run_manager", "get_model_status"]  # Result out
