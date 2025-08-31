import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from finance_agent import run_query as fin_run_query, compute_ratios_for_ticker
from llm_core import get_model_status as agent_llm_status, summarize_ib
from predict_agent import predict
from news_agent import get_news_analysis

app = FastAPI(title="LSA Agent API", version="1.0")

# ---- CORS: 한 번만! ----
origins_env = os.getenv("CORS_ORIGINS", "https://chanthr.github.io,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # 필요 시 아래 한 줄로 대체 (둘 중 하나만 사용)
    # allow_origin_regex=r"https://.*\.github\.io$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_credentials=False,
    max_age=86400,
)

# ---- Schemas ----
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

# ---- Routes ----
@app.get("/health")
def health():
    return {"status": "ok", "agent_llm": agent_llm_status()}

@app.post("/analyse")
def analyse(req: AnalyseReq):
    try:
        return fin_run_query(req.query, language=req.language)
    except Exception as e:
        return {"error": f"analyse_failed:{type(e).__name__}: {e}"}

@app.post("/predict")
def do_predict(req: PredictReq):
    try:
        return predict(req.ticker.strip())
    except Exception as e:
        return {"symbol": req.ticker, "signal": "HOLD", "error": f"predict_failed:{type(e).__name__}: {e}"}

@app.post("/ibsummary")
def ib_summary(req: SummaryReq):
    try:
        ratios = compute_ratios_for_ticker(req.ticker).get("ratios", {})
        ana = {"core": {"ratios": ratios}}
        p = predict(req.ticker.strip())
        return {"summary": summarize_ib(ana, p, req.language), "prediction": p}
    except Exception as e:
        # 절대 500로 나가지 않게
        return {"summary": None, "error": f"ibsummary_failed:{type(e).__name__}: {e}"}

@app.post("/media")
def media(req: MediaReq):
    try:
        company = req.company or compute_ratios_for_ticker(req.ticker).get("company")
        na = get_news_analysis(req.ticker.strip(), req.language, company_name=company, k=40)
        return {"news_analysis": na}
    except Exception as e:
        return {"news_analysis": None, "error": f"media_failed:{type(e).__name__}: {e}"}

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs"}
