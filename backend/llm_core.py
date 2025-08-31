# llm_core.py
import os, re, json
from typing import Optional, Dict, Any

# dotenv (선택)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Groq (선택)
_HAVE_LLM = True
try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
except Exception:
    _HAVE_LLM = False
    ChatGroq = None
    ChatPromptTemplate = None
    StrOutputParser = None

_LLM_PROVIDER = "none"
_LLM_REASON = None
_model = None

def _build_model():
    global _LLM_PROVIDER, _LLM_REASON
    if not _HAVE_LLM:
        _LLM_PROVIDER, _LLM_REASON = "none", "langchain_groq not installed"
        return None
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model_name = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    if not key:
        _LLM_PROVIDER, _LLM_REASON = "none", "GROQ_API_KEY missing"
        return None
    try:
        m = ChatGroq(model=model_name, temperature=0.2, api_key=key)
        _LLM_PROVIDER, _LLM_REASON = "groq", None
        return m
    except Exception as e:
        _LLM_PROVIDER, _LLM_REASON = "none", f"ChatGroq init failed: {e}"
        return None

_model = _build_model()

def get_model_status() -> dict:
    return {"provider": _LLM_PROVIDER, "ready": bool(_model), "reason": _LLM_REASON}

# ---------- Fallback rules ----------
def _pick(node: Dict[str, Any], key: str) -> Optional[float]:
    try:
        v = node.get(key, {}) or {}
        val = v.get("value", None)
        return None if val is None else float(val)
    except Exception:
        return None

def _extract_core_ratios(analysis: Dict) -> Dict[str, Dict]:
    """
    analysis: finance_agent.run_query() 결과 or raw ratios dict
    """
    if "ratios" in analysis:
        return analysis["ratios"]
    core = analysis.get("core") or {}
    return core.get("ratios") or {}

def _ib_summary_rule(analysis: Dict, pred: Optional[Dict], language: str) -> str:
    ratios = _extract_core_ratios(analysis)
    liq = ratios.get("Liquidity", {}) or {}
    sol = ratios.get("Solvency", {}) or {}

    cr   = _pick(liq, "current_ratio")
    qr   = _pick(liq, "quick_ratio")
    cash = _pick(liq, "cash_ratio")
    de   = _pick(sol, "debt_to_equity")
    dr   = _pick(sol, "debt_ratio")
    ic   = _pick(sol, "interest_coverage")

    if language.lower().startswith("ko"):
        parts = []
        if cr is not None and qr is not None:
            parts.append(f"유동성은 유동비율 {cr:.2f}, 당좌비율 {qr:.2f}로 단기지급능력은 {'양호' if cr>=1.5 else '보통'}합니다.")
        else:
            parts.append("유동성 지표가 제한적으로 제공됩니다.")
        parts.append(f"건전성은 D/E {de if de is not None else 'N/A'}"
                     f", 부채비율 {dr if dr is not None else 'N/A'}"
                     f", 이자보상배율 {ic if ic is not None else 'N/A'}로 {'보수적' if (de and de<=1.0 and (ic and ic>=5)) else '중립'}입니다.")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"]); sig = pred.get("signal","HOLD")
            parts.append(f"단기(1D) 시그널은 {sig}({p*100:+.2f}%)로 참고 지표로만 활용을 권고합니다.")
        return " ".join(parts)
    else:
        parts = []
        if cr is not None and qr is not None:
            parts.append(f"Liquidity is {'solid' if cr>=1.5 else 'adequate'} (Current {cr:.2f}, Quick {qr:.2f}).")
        else:
            parts.append("Liquidity metrics are limited.")
        parts.append(f"Balance sheet looks {'conservative' if (de and de<=1.0 and (ic and ic>=5)) else 'neutral'} "
                     f"(D/E {de if de is not None else 'N/A'}, Debt {dr if dr is not None else 'N/A'}, IC {ic if ic is not None else 'N/A'}).")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"]); sig = pred.get("signal","HOLD")
            parts.append(f"1-day tactical signal: {sig} ({p*100:+.2f}%), for trading color only.")
        return " ".join(parts)

def _media_summary_rule(na: Dict, language: str) -> str:
    o = (na or {}).get("overall", {}) or {}
    label = o.get("label") or "mixed"
    score = float(o.get("score") or 0.0)
    kws = ", ".join((o.get("top_keywords") or [])[:5]) or ("키워드 없음" if language.lower().startswith("ko") else "no clear keywords")
    if language.lower().startswith("ko"):
        tone = "긍정적" if label=="bullish" else ("부정적" if label=="bearish" else "혼재")
        return f"언론 톤은 {tone}(점수 {score:+.3f})이며, 핵심 키워드는 {kws} 입니다."
    else:
        tone = "bullish" if label=="bullish" else ("bearish" if label=="bearish" else "mixed")
        return f"Media tone is {tone} (score {score:+.3f}); key themes: {kws}."

# ---------- LLM summaries ----------
def summarize_ib(analysis: Dict, pred: Optional[Dict], language: str) -> str:
    if not _model or not _HAVE_LLM:
        return _ib_summary_rule(analysis, pred, language)
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an investment-banking equity analyst. Write in {ask_lang}. "
         "Deliver a crisp 2–3 sentence note covering: liquidity stance, solvency/leverage, "
         "and a tactical 1-day signal if provided. Use a professional tone. No bullets/markdown."),
        ("human", "DATA(JSON): {blob}\nReturn only the prose text (2–3 sentences).")
    ])
    chain = prompt | _model | StrOutputParser()
    try:
        txt = chain.invoke({"ask_lang": ask_lang, "blob": json.dumps({"analysis": analysis, "prediction": pred}, ensure_ascii=False)})
        txt = re.sub(r"\s+", " ", re.sub(r"`+|#+", " ", str(txt))).strip()
        return txt[:600] if txt else _ib_summary_rule(analysis, pred, language)
    except Exception:
        return _ib_summary_rule(analysis, pred, language)

def summarize_media(na: Dict, language: str) -> str:
    if not _model or not _HAVE_LLM:
        return _media_summary_rule(na, language)
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an equity analyst. Write 1 concise sentence in {ask_lang} summarizing media tone and themes. No markdown."),
        ("human", "DATA(JSON): {blob}\nReturn one sentence.")
    ])
    chain = prompt | _model | StrOutputParser()
    try:
        txt = chain.invoke({"ask_lang": ask_lang, "blob": json.dumps(na, ensure_ascii=False)})
        txt = re.sub(r"\s+", " ", str(txt)).strip()
        return txt[:280] if txt else _media_summary_rule(na, language)
    except Exception:
        return _media_summary_rule(na, language)

__all__ = ["get_model_status", "summarize_ib", "summarize_media"]
