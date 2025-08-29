# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import yfinance as yf
from finance_agent import run_query, llm  # llm은 요약시 사용(없으면 폴백)
from predictor import predict_one

app = FastAPI(title="FIN Agent + Predictions", version="1.2")

# ✅ CORS (GitHub Pages: chanthr.github.io)
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

# ---------- 스키마 ----------
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

# ---------- 도우미 ----------
def _live_price(sym: str):
    try:
        t = yf.Ticker(sym)
        fi = getattr(t, "fast_info", {}) or {}
        lp = fi.get("last_price")
        return float(lp) if lp is not None else None
    except Exception:
        return None

def _news(sym: str):
    try:
        t = yf.Ticker(sym)
        items = getattr(t, "news", []) or []
        # 필요한 키만 추림
        out = []
        for n in items[:10]:
            out.append({
                "title": n.get("title"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime")
            })
        return out
    except Exception:
        return []

def _short_summary(text: str, language: str) -> str:
    """LLM 있으면 1~2문장 요약, 없으면 첫 문장 폴백."""
    if not text:
        return ""
    try:
        if llm is not None:
            ask_lang = "Korean" if language.lower().startswith("ko") else "English"
            prompt = (
                f"Summarize in {ask_lang}. "
                "Return ONE or TWO short sentences max, plain text only. Text:\n\n" + text
            )
            return llm.invoke(prompt).content.strip()
    except Exception:
        pass
    # 폴백: 첫 문장만
    cut = text.strip().split("\n", 1)[0]
    return cut[:240]

# ---------- 라우트 ----------
@app.post("/analyse")
def analyse(body: AnalyseIn):
    # 기존 프론트가 쓰는 엔드포인트 (그대로)
    return run_query(body.query, language=body.language)

@app.post("/predict")
def predict(body: PredictIn):
    # predictor.py 기반 1일 예측
    return predict_one(body.symbol, force=body.force)

@app.post("/agent")
def agent(body: AgentIn):
    # 1) 재무분석
    analysis = run_query(body.query, language=body.language)
    core = (analysis or {}).get("core") or {}
    symbol = core.get("ticker") or body.query.strip().upper()

    # 2) 예측
    prediction = predict_one(symbol, force=False)

    # 3) 실시간가(가능하면) / 뉴스(옵션)
    price = _live_price(symbol) or core.get("price")
    news = _news(symbol) if body.include_news else []

    # 4) LLM 한줄 요약
    summary = _short_summary(analysis.get("explanation",""), body.language)

    return {
        "ticker": symbol,
        "price": price,
        "analysis": analysis,      # 기존 구조 유지 (core/ratios/explanation/meta)
        "prediction": prediction,  # symbol/last_close/pred_ret_1d/pred_close_1d/signal/ts
        "summary": summary,
        "news": news,
    }
