# api.py
import time, urllib.parse, traceback
import feedparser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import re, yfinance as yf
from predictor import predict_one
from finance_agent import run_query, llm, get_llm_status as fin_llm_status
from llm_agent import run_manager, get_model_status as agent_llm_status

app = FastAPI(title="FIN Agent + Predictions", version="1.4")

# ✅ CORS: 일단 확 풀어서 확인 → 문제 해결 후 도메인만 남겨도 됨
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chanthr.github.io"],      # 운영: 이 한 줄만 두고
    allow_origin_regex=r"https://.*\.github\.io$",    # 또는 깃헙페이지 전체 허용
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# ✅ 프리플라이트(OPTIONS) 강제 허용 (일부 PaaS에서 유용)
@app.options("/{path:path}")
def opts(path: str):
    return JSONResponse({"ok": True})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "finance_llm": fin_llm_status(),   # {'provider': 'groq'|'none', 'ready': bool, 'reason': ...}
        "agent_llm": agent_llm_status(),   # 동일
    }

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


# (뉴스 폴백은 llm_agent 내부에서 처리하므로 유지)
def _news(sym: str, language: str = "en"):
    return []


def _short_summary(text: str, language: str) -> str:
    if not text:
        return ""
    s = re.sub(r"```.*?```", " ", text, flags=re.S)
    s = re.sub(r"`[^`]*`", " ", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"[*_\[\]()>-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
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
        # 프론트에서 읽기 쉬운 형태로 200 반환
        return JSONResponse(status_code=200, content={
            "symbol": body.symbol, "error": f"{type(e).__name__}: {e}"
        })


# ✅ 핵심: /agent는 llm_agent.run_manager만 호출 + 예외를 JSON으로 잡아 내려줌
@app.post("/agent")
def agent(body: AgentIn):
    try:
        return run_manager(body.query, language=body.language, include_news=body.include_news)
    except Exception as e:
        return JSONResponse(status_code=200, content={
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[:2000]
        })
