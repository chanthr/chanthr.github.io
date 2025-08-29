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


# ---------------- 뉴스(yfinance + Google News) ----------------
def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 10) -> List[Dict]:
    items: List[Dict] = []

    # 1) yfinance
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[:k]:
            items.append({
                "title": n.get("title"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime"),
            })
    except Exception:
        pass

    # 2) Google News 보강
    def _google(q: str):
        is_ko = str(language).lower().startswith("ko")
        hl = "ko" if is_ko else "en-US"
        gl = "KR" if is_ko else "US"
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote_plus(q)
               + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries[:k]:
            link = e.get("link") or (e.get("links", [{}])[0].get("href"))
            ts = int(time.mktime(e.published_parsed)) if getattr(e, "published_parsed", None) else None
            out.append({"title": e.get("title"), "link": link, "providerPublishTime": ts})
        return out

    if len(items) < 3:
        q = f"{symbol} 주가 OR {symbol} 실적 OR {symbol} 주식" if language[:2]=="ko" else f"{symbol} stock OR earnings"
        try:
            items.extend(_google(q))
        except Exception:
            pass

    if len(items) < 3 and company_name:
        q2 = f"{company_name} 주가 OR {company_name} 실적 OR {company_name} 주식" if language[:2]=="ko" else f"{company_name} stock OR earnings"
        try:
            items.extend(_google(q2))
        except Exception:
            pass

    # 3) 클린업(제목 없음/중복 링크 제거)
    clean, seen = [], set()
    for it in items:
        t = (it or {}).get("title") or ""
        lk = (it or {}).get("link")
        if not t.strip():
            continue
        if lk and lk in seen:
            continue
        if lk:
            seen.add(lk)
        clean.append(it)
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

__all__ = ["run_manager", "get_model_status"]  # ✅ 내보내기
