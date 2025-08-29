# api.py
import time, urllib.parse
import feedparser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import re, yfinance as yf
from finance_agent import run_query, llm
from predictor import predict_one

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

def _news(sym: str, language: str = "en"):
    """yfinance 뉴스 → 부족하면 Google News RSS로 보완"""
    items = []

    # 1) yfinance 시도
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

    # 2) 폴백: Google News RSS
    if len(items) < 3:  # 충분치 않으면 보충
        try:
            # 언어/지역 파라미터
            is_ko = str(language).lower().startswith("ko")
            hl = "ko" if is_ko else "en-US"
            gl = "KR" if is_ko else "US"

            # 검색쿼리: 티커 + stock (한국어일땐 '주가'도 OR)
            q = f'{sym} stock'
            if is_ko:
                q = f'{sym} 주가 OR {sym} 실적 OR {sym} 주식'
            url = (
                "https://news.google.com/rss/search?q="
                + urllib.parse.quote_plus(q)
                + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
            )

            feed = feedparser.parse(url)
            for e in feed.entries[: max(0, 10 - len(items))]:
                link = e.get("link") or (e.get("links", [{}])[0].get("href"))
                ts = int(time.mktime(e.published_parsed)) if getattr(e, "published_parsed", None) else None
                items.append({
                    "title": e.get("title"),
                    "link": link,
                    "providerPublishTime": ts,
                })
        except Exception:
            pass

    return items

def _short_summary(text: str, language: str) -> str:
    if not text:
        return ""
    # 코드블록/마크다운 제거
    s = re.sub(r"```.*?```", " ", text, flags=re.S)
    s = re.sub(r"`[^`]*`", " ", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)  # 헤더 # 제거
    s = re.sub(r"[*_\[\]()>-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    # 한/영 첫 문장
    if language.lower().startswith("ko"):
        m = re.split(r"(?:다\.|요\.|\.|\?|!)\s", s, maxsplit=1)
        first = (m[0] or s).strip()
    else:
        m = re.split(r"(?<=[\.\?!])\s", s, maxsplit=1)
        first = (m[0] or s).strip()
    return first[:240]

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

@app.post("/agent")
def agent(body: AgentIn):
    analysis = run_query(body.query, language=body.language)
    core = (analysis or {}).get("core") or {}
    symbol = core.get("ticker") or body.query.strip().upper()

    # 예측 (에러 무시)
    try:
        prediction = predict_one(symbol, force=False)
    except Exception as e:
        prediction = {"symbol": symbol, "error": f"{type(e).__name__}: {e}"}

    price = _live_price(symbol) or core.get("price")

    # 🔽 언어 기반 뉴스
    news = _news(symbol, language=body.language) if body.include_news else []

    summary = _short_summary(analysis.get("explanation", ""), body.language) or ""
    return {
        "ticker": symbol,
        "price": price,
        "analysis": analysis,
        "prediction": prediction,
        "summary": summary,
        "news": news,
    }
