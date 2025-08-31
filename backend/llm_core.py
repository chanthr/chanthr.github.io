import os, re, json
from typing import Dict, Optional

# ── LLM 준비 (없으면 graceful degrade)
try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    _HAVE = True
except Exception:
    ChatGroq = ChatPromptTemplate = StrOutputParser = None
    _HAVE = False

_PROVIDER = "none"
_REASON = "not used"
_MODEL = None

def _build():
    global _PROVIDER, _REASON, _MODEL
    if not _HAVE:
        _PROVIDER, _REASON, _MODEL = "none", "langchain_groq not installed", None
        return
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    name = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    if not key:
        _PROVIDER, _REASON, _MODEL = "none", "GROQ_API_KEY missing", None
        return
    try:
        _MODEL = ChatGroq(model=name, api_key=key, temperature=0.2)
        _PROVIDER, _REASON = "groq", None
    except Exception as e:
        _PROVIDER, _REASON, _MODEL = "none", f"ChatGroq init failed: {e}", None

_build()

def get_model_status() -> dict:
    return {"provider": _PROVIDER, "ready": bool(_MODEL), "reason": _REASON}

# ── 규칙 기반 폴백 요약 (절대 예외 X)
def _rule_summary(ana: dict, pred: Optional[dict], language: str) -> str:
    r = (ana or {}).get("core", {}).get("ratios", {}) or {}
    L = r.get("Liquidity", {}) or {}
    S = r.get("Solvency", {}) or {}
    def band(x): return (x or {}).get("band", "N/A")
    def score(b): return {"Strong": 2, "Fair": 1}.get(b, 0)

    total = sum([
        score(band(L.get("current_ratio"))),
        score(band(L.get("quick_ratio"))),
        score(band(L.get("cash_ratio"))),
        score(band(S.get("debt_to_equity"))),
        score(band(S.get("debt_ratio"))),
        score(band(S.get("interest_coverage"))),
    ])

    if language.lower().startswith("ko"):
        level = "매우 양호" if total >= 9 else "양호" if total >= 6 else "보통" if total >= 3 else "취약"
        tip = ""
        try:
            if pred and pred.get("pred_ret_1d") is not None:
                tip = f" 단기(1D) 신호 {pred.get('signal','HOLD')} ({float(pred['pred_ret_1d'])*100:+.2f}%)."
        except Exception:
            pass
        return f"유동성/건전성 지표를 종합하면 재무건전성은 {level}합니다.{tip}".strip()
    else:
        level = "excellent" if total >= 9 else "good" if total >= 6 else "average" if total >= 3 else "weak"
        tip = ""
        try:
            if pred and pred.get("pred_ret_1d") is not None:
                tip = f" 1-day signal {pred.get('signal','HOLD')} ({float(pred['pred_ret_1d'])*100:+.2f}%)."
        except Exception:
            pass
        return f"Overall balance-sheet quality appears {level}.{tip}".strip()

# ── IB 스타일 요약 (LLM 있으면 사용, 실패 시 폴백)
def summarize_ib(ana: dict, pred: Optional[dict], language: str) -> str:
    if _MODEL is None:
        return _rule_summary(ana, pred, language)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an investment-banking equity analyst. Write in {lang}. "
         "Return 2–3 sentences covering liquidity, leverage/solvency, and optionally a 1-day signal. Plain text only."),
        ("human", "DATA(JSON): {blob}")
    ])
    chain = prompt | _MODEL | StrOutputParser()

    try:
        txt = chain.invoke({
            "lang": "Korean" if language.lower().startswith("ko") else "English",
            "blob": json.dumps({"analysis": ana, "prediction": pred}, ensure_ascii=False)
        })
        txt = re.sub(r"\s+", " ", str(txt)).strip() or _rule_summary(ana, pred, language)
        return txt[:600]
    except Exception:
        return _rule_summary(ana, pred, language)
