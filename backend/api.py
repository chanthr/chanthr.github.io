# api.py
import time, urllib.parse
import pandas as pd
import numpy as np
import feedparser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import re, yfinance as yf
from finance_agent import run_query, llm
from predictor import predict_one
from llm_agent import run_manager

app = FastAPI(title="FIN Agent + Predictions", version="1.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chanthr.github.io"],
    allow_methods=["GET","POST","OPTIONS"],
    allow_headers=["*"],   # ← 여기
    max_age=3600,
)

@app.get("/health")
def health():
    return {"status": "ok"}

class AnalyseIn(BaseModel):
    query: str
    language: str = "ko"

class PredictIn(BaseModel):
    symbol: str
    force: bool = False

class AgentIn(BaseModel):
    query: str
    language: str = "ko"
    include_news: bool = True

def _live_price(sym: str):
    try:
        fi = (yf.Ticker(sym).fast_info or {})
        lp = fi.get("last_price")
        return float(lp) if lp is not None else None
    except Exception:
        return None

# news scrapping
def _news(sym: str, language: str = "en", company_name: str | None = None):
    items = []
    # 1) yfinance
    try:
        arr = getattr(yf.Ticker(sym), "news", []) or []
        for n in arr[:10]:
            items.append({
                "title": n.get("title"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime"),
            })
    except Exception:
        pass

    # 2) Google News RSS (심볼로)
    def _google_news(q: str, lang: str):
        is_ko = str(lang).lower().startswith("ko")
        hl = "ko" if is_ko else "en-US"
        gl = "KR" if is_ko else "US"
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote_plus(q)
            + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
        )
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries[:10]:
            link = e.get("link") or (e.get("links", [{}])[0].get("href"))
            ts = int(time.mktime(e.published_parsed)) if getattr(e, "published_parsed", None) else None
            out.append({"title": e.get("title"), "link": link, "providerPublishTime": ts})
        return out

    if len(items) < 3:
        # 심볼 중심
        q = f'{sym} stock' if not language.lower().startswith("ko") else f'{sym} 주가 OR {sym} 실적 OR {sym} 주식'
        try:
            items.extend(_google_news(q, language))
        except Exception:
            pass

    if len(items) < 3 and company_name:
        # 회사명으로 한 번 더
        q2 = f'{company_name} stock' if not language.lower().startswith("ko") else f'{company_name} 주가 OR {company_name} 실적 OR {company_name} 주식'
        try:
            items.extend(_google_news(q2, language))
        except Exception:
            pass

    # 중복 제거(링크 기준)
    seen, dedup = set(), []
    for it in items:
        lk = it.get("link")
        if lk and lk not in seen:
            seen.add(lk)
            dedup.append(it)
    return dedup[:10]

def _short_summary(text: str, language: str) -> str:
    if not text:
        return ""
    s = re.sub(r"```.*?```", " ", text, flags=re.S)
    s = re.sub(r"`[^`]*`", " ", s)
    # 헤더 라인 전체 제거
    s = re.sub(r"^#{1,6} .*$", " ", s, flags=re.M)
    # 마크다운 잔여 기호 정리
    s = re.sub(r"[*_\[\]()>-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    if language.lower().startswith("ko"):
        parts = re.split(r"(?:다\.|요\.|\.|\?|!)\s", s, maxsplit=2)
    else:
        parts = re.split(r"(?<=[\.\?!])\s", s, maxsplit=2)
    out = " ".join([p for p in parts[:2] if p]).strip()
    return out[:280]
    
@app.post("/analyse")
def analyse(body: AnalyseIn):
    return run_query(body.query, language=body.language)

@app.post("/predict")
def predict(body: PredictIn):
    try:
        out = predict_one(body.symbol, force=body.force)
        out["live_price"] = _live_price(body.symbol)
        return out
    except Exception as e:
        # ❗ 프론트에서 읽을 수 있게 200으로 에러 메시지 제공
        return JSONResponse(status_code=200, content={
            "symbol": body.symbol, "error": f"{type(e).__name__}: {e}"
        })

def _predict_fallback(symbol: str) -> dict:
    """
    sklearn/특정 환경에서 predictor가 실패할 경우를 대비한 초간단 폴백.
    - 6개월 일봉 받아서 10일 EWMA 수익률로 1일 예상수익률 산출
    """
    import yfinance as yf
    df = yf.download(symbol, period="6mo", interval="1d", auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df:
        raise RuntimeError("fallback: no price data")
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 20:
        raise RuntimeError("fallback: not enough data")
    ret = close.pct_change().ewm(span=10, adjust=False).mean().iloc[-1]
    last = float(close.iloc[-1])
    pred_close = last * (1.0 + float(ret))
    signal = "BUY" if ret > 0.01 else ("SELL" if ret < -0.01 else "HOLD")
    return {
        "symbol": symbol,
        "last_close": round(last, 4),
        "pred_ret_1d": round(float(ret), 6),
        "pred_close_1d": round(float(pred_close), 4),
        "signal": signal,
        "ts": int(time.time()),
    }

# 최종 수정 버전 
@app.post("/agent")
def agent(body: AgentIn):
    return run_manager(body.query, language=body.language, include_news=body.include_news)
