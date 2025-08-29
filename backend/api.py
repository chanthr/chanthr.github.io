# api.py
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
    allow_headers=["Content-Type"],
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

def _news(sym: str):
    try:
        items = getattr(yf.Ticker(sym), "news", []) or []
        return [{
            "title": n.get("title"),
            "link": n.get("link"),
            "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime"),
        } for n in items[:10]]
    except Exception:
        return []

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

    # 예측은 실패해도 구조 보장
    try:
        prediction = predict_one(symbol, force=False)
    except Exception as e:
        prediction = {"symbol": symbol, "error": f"{type(e).__name__}: {e}"}

    price = _live_price(symbol) or core.get("price")
    news = _news(symbol) if body.include_news else []

    try:
        summary = _short_summary(analysis.get("explanation", ""), body.language)
    except Exception:
        summary = ""

    return {
        "ticker": symbol,
        "price": price,
        "analysis": analysis,
        "prediction": prediction,
        "summary": summary,
        "news": news,
    }
