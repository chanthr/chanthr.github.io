import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from finance_agent import (
    run_query as fin_run_query,
    compute_ratios_for_ticker,
)
from llm_core import get_model_status as agent_llm_status, summarize_ib
from predict_agent import predict
from news_agent import get_news_analysis

app = FastAPI(title="LSA Agent API", version="1.0")

# -------- CORS -------- #
origins_env = os.getenv("CORS_ORIGINS", "https://chanthr.github.io,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,       
    # 필요 시 전체 GitHub Pages 허용:
    # allow_origin_regex=r"https://.*\.github\.io$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_credentials=False,             # "*" 와 함께 쓸 거면 반드시 False 유지
    max_age=86400,
)

# ---------- Schemas ----------
class AnalyseReq(BaseModel):
    query: str
    language: str = "ko"

class PredictReq(BaseModel):
    ticker: str

class SummaryReq(BaseModel):
    ticker: str
    language: str = "ko"

class MediaReq(BaseModel):
    ticker: str
    language: str = "ko"
    company: Optional[str] = None

# ---------- Health ----------
@app.get("/health")
def health():
    # finance_agent는 LLM 없음(폴백 내러티브 사용) → 상태 항목은 agent 쪽만 표기
    return {
        "status": "ok",
        "finance_llm": {"provider": "none", "ready": False, "reason": "not used"},
        "agent_llm": agent_llm_status(),
    }

# ---------- Analyse ----------
@app.post("/analyse")
def analyse(req: AnalyseReq):
    return fin_run_query(req.query, language=req.language)

# ---------- Predict ----------
@app.post("/predict")
def do_predict(req: PredictReq):
    return predict(req.ticker.strip())

# ◀︎◀︎ 백워드 호환: GET /predict?t=AAPL
@app.get("/predict")
def do_predict_get(t: str):
    return predict(t.strip())

# ---------- IB summary (ratios + prediction → 2~3문장 요약) ----------
@app.post("/ibsummary")
def ib_summary(req: SummaryReq):
    ratios = compute_ratios_for_ticker(req.ticker).get("ratios", {})
    ana = {"core": {"ratios": ratios}}
    pred = predict(req.ticker.strip())
    return {"summary": summarize_ib(ana, pred, req.language), "prediction": pred}

# ◀︎◀︎ 백워드 호환: GET /ibsummary?t=AAPL&lang=ko
@app.get("/ibsummary")
def ib_summary_get(t: str, lang: str = "ko"):
    ratios = compute_ratios_for_ticker(t).get("ratios", {})
    ana = {"core": {"ratios": ratios}}
    pred = predict(t.strip())
    return {"summary": summarize_ib(ana, pred, lang), "prediction": pred}

# ---------- Media (뉴스 분석만 반환) ----------
@app.post("/media")
def media(req: MediaReq):
    company = req.company
    try:
        if not company:
            company = compute_ratios_for_ticker(req.ticker).get("company")
    except Exception:
        pass
    na = get_news_analysis(req.ticker.strip(), req.language, company_name=company, k=40)
    return {"news_analysis": na}

# 선택: 루트
@app.get("/")
def root():
    return {"ok": True, "docs": "/docs"}
