# api.py
import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from finance_agent import run_query as fin_run_query, compute_ratios_for_ticker, pick_valid_ticker
from llm_core import get_model_status as agent_llm_status, summarize_ib
from predict_agent import predict
from news_agent import get_news_analysis

app = FastAPI(title="LSA Agent API", version="1.1")

# ---- CORS ----
origins_env = os.getenv("CORS_ORIGINS", "https://chanthr.github.io,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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
    include_narrative: bool = True  # 프론트가 Narrative 껐으면 토큰 아끼기용

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
    """
    무조건 스키마를 채워서 반환:
      { core:{company,ticker,price,ratios}, notes, explanation, meta }
    실패해도 200으로 빈 필드 채워줌(프론트가 안전하게 렌더)
    """
    try:
        out = fin_run_query(req.query, language=req.language, want_narrative=req.include_narrative)
        # 방어: 핵심 키가 없으면 최소 스켈레톤 구성
        if not isinstance(out, dict) or "core" not in out:
            raise ValueError("bad_analyse_payload")
        return out
    except Exception as e:
        # fallback: 티커만 뽑아 최소한의 ratios라도 채우기
        try:
            sym = pick_valid_ticker(req.query)
            base = compute_ratios_for_ticker(sym)
            core = {
                "company": base.get("company") or "-",
                "ticker": base.get("ticker") or sym or "-",
                "price": base.get("price"),
                "ratios": base.get("ratios") or {"Liquidity": {}, "Solvency": {}},
            }
        except Exception:
            core = {"company": "-", "ticker": "-", "price": None, "ratios": {"Liquidity": {}, "Solvency": {}}}
        return {
            "core": core,
            "notes": None,
            "explanation": "",   # Narrative 섹션은 비워두기
            "meta": {"source": "fallback"},
            "error": f"analyse_failed:{type(e).__name__}: {e}",
        }

@app.post("/predict")
def do_predict(req: PredictReq):
    try:
        return predict(req.ticker.strip())
    except Exception as e:
        # 프론트에서 카드에 원인 보여줄 수 있게
        return {"symbol": req.ticker, "signal": "HOLD", "error": f"predict_failed:{type(e).__name__}: {e}"}

@app.post("/ibsummary")
def ib_summary(req: SummaryReq):
    """
    Analyst Summary 는 prediction 실패와 무관하게 항상 텍스트를 돌려줍니다.
    """
    try:
        ratios = compute_ratios_for_ticker(req.ticker).get("ratios", {})
        ana = {"core": {"ratios": ratios}}
        try:
            p = predict(req.ticker.strip())  # 실패해도 요약은 규칙기반/LLM으로 진행
        except Exception:
            p = None
        txt = summarize_ib(ana, p, req.language) or ""
        return {"summary": txt, "prediction": p}
    except Exception as e:
        return {"summary": "", "error": f"ibsummary_failed:{type(e).__name__}: {e}"}

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
