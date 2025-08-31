# api.py
import os
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf

# finance agent (LLM 없음)
from finance_agent import (
    run_query as fin_run_query,
    compute_ratios_for_ticker,
    get_llm_status as finance_llm_status,  # 헬스 표시용
)

# LLM 코어 (Groq 연결/IB 요약/미디어 요약)
from llm_core import (
    get_model_status as agent_llm_status,
    summarize_ib,
    summarize_media,
)

# 예측 모듈
from predict_agent import predict

# (선택) 뉴스 집계기
try:
    from news_agent import get_news_analysis
    _HAVE_NEWS_AGENT = True
except Exception:
    _HAVE_NEWS_AGENT = False

app = FastAPI(title="LSA Agent API", version="1.1")

# ---- CORS (한 번만!) ----
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

# ============= Schemas =============
class AnalyseReq(BaseModel):
    query: str
    language: str = "ko"

class PredictReq(BaseModel):
    # 프론트는 symbol을 보내지만, 하위호환 위해 ticker도 허용
    symbol: Optional[str] = None
    ticker: Optional[str] = None

class SummaryReq(BaseModel):
    ticker: str
    language: str = "ko"

class MediaReq(BaseModel):
    ticker: str
    language: str = "ko"
    company: Optional[str] = None


# ============= Routes =============
@app.get("/health")
def health():
    return {
        "status": "ok",
        "finance_llm": finance_llm_status(),  # finance_agent는 LLM 없음
        "agent_llm": agent_llm_status(),      # llm_core(Groq) 상태
    }

@app.post("/analyse")
def analyse(req: AnalyseReq):
    try:
        return fin_run_query(req.query, language=req.language)
    except Exception as e:
        return {"error": f"analyse_failed:{type(e).__name__}: {e}"}

@app.post("/predict")
def do_predict(req: PredictReq):
    # symbol 우선, 없으면 ticker, 모두 없으면 에러
    sym = (req.symbol or req.ticker or "").strip()
    if not sym:
        return {"symbol": None, "signal": "HOLD", "error": "predict_failed:ValueError: empty symbol"}
    try:
        out = predict(sym)
        if isinstance(out, dict) and not out.get("symbol"):
            out["symbol"] = sym
        return out
    except Exception as e:
        return {"symbol": sym, "signal": "HOLD", "error": f"predict_failed:{type(e).__name__}: {e}"}

@app.post("/ibsummary")
def ib_summary(req: SummaryReq):
    try:
        # ratios만 넘겨도 summarize_ib가 포맷을 알아서 처리
        ratios = compute_ratios_for_ticker(req.ticker).get("ratios", {})
        ana = {"core": {"ratios": ratios}}
        p = predict(req.ticker.strip())
        return {"summary": summarize_ib(ana, p, req.language), "prediction": p}
    except Exception as e:
        # 절대 500로 나가지 않게
        return {"summary": None, "error": f"ibsummary_failed:{type(e).__name__}: {e}"}

@app.post("/media")
def media(req: MediaReq):
    """
    news_agent가 있으면 그걸 사용하고, 없으면 yfinance 뉴스로 폴백.
    서버에서 summarize_media로 간단 요약(note)까지 붙여줌.
    """
    try:
        # 회사명 보강 (없어도 동작)
        company = req.company
        if not company:
            try:
                meta = compute_ratios_for_ticker(req.ticker)
                company = meta.get("company")
            except Exception:
                company = None

        if _HAVE_NEWS_AGENT:
            na = get_news_analysis(req.ticker.strip(), req.language, company_name=company, k=40)
        else:
            # 폴백: yfinance 뉴스
            try:
                arr = (getattr(yf.Ticker(req.ticker.strip()), "news", []) or [])[:40]
            except Exception:
                arr = []
            na = {
                "articles": arr,
                "overall": {"label": "mixed", "score": 0.0, "impact_score": 0.0, "pos": 0, "neg": 0, "neu": len(arr)},
            }

        # 헤드라인 요약만 생성 (IB 요약이 섞이지 않도록 summarize_media가 리스트/기사만 요약)
        try:
            note = summarize_media(na, language=req.language)
            if isinstance(na, dict):
                na["note"] = note
        except Exception:
            pass

        return {"news_analysis": na}
    except Exception as e:
        return {"news_analysis": None, "error": f"media_failed:{type(e).__name__}: {e}"}

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs"}
