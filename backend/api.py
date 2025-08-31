# api.py (update)
import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from finance_agent import (
    run_query as fin_run_query, 
    get_llm_status as fin_llm_status, 
    compute_ratios_for_ticker,
)
from llm_core import get_model_status as agent_llm_status, summarize_ib
from predict_agent import predict
from news_agent import get_news_analysis

app = FastAPI(title="LSA Agent API", version="1.0")
app.add_middleware( 
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub Pages / 로컬 개발 도메인 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chanthr.github.io"],      # 운영: 이 한 줄만 두고
    #allow_origin_regex=r"https://.*\.github\.io$",    # 또는 깃헙페이지 전체 허용
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
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

# ---------- Routes ----------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "finance_llm": fin_llm_status(),
        "agent_llm": agent_llm_status(),
    }

@app.post("/analyse")
def analyse(req: AnalyseReq):
    # finance_agent의 기존 전체 분석(서버가 Narrative 포함 생성)
    return fin_run_query(req.query, language=req.language)

@app.post("/predict")
def do_predict(req: PredictReq):
    return predict(req.ticker.strip())

@app.post("/ibsummary")
def ib_summary(req: SummaryReq):
    # ratios는 finance_agent에서 가져오되 무겁지 않은 경로 사용
    ana = {"core": {"ratios": compute_ratios_for_ticker(req.ticker).get("ratios", {})}}
    pred = predict(req.ticker.strip())
    return {"summary": summarize_ib(ana, pred, req.language), "prediction": pred}

@app.post("/media")
def media(req: MediaReq):
    company = req.company
    # company 미지정 시 finance_agent에서 한 번만 가져와 품질 향상 (실패해도 괜찮음)
    try:
        if not company:
            company = compute_ratios_for_ticker(req.ticker).get("company")
    except Exception:
        pass
    na = get_news_analysis(req.ticker.strip(), req.language, company_name=company, k=40)
    return {"news_analysis": na}

# (선택) 루트
@app.get("/")
def root():
    return {"ok": True, "docs": "/docs"}

# Uvicorn entrypoint:
# uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}
