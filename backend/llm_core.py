# llm_core.py
import os, re, json
from typing import Dict, Optional, List, Union

# ── LLM 준비 (없으면 graceful degrade)
try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    _HAVE_LLM = True
except Exception:
    ChatGroq = ChatPromptTemplate = StrOutputParser = None  # type: ignore
    _HAVE_LLM = False

_PROVIDER = "none"
_REASON = "not used"
_MODEL = None  # type: Optional["ChatGroq"]


def _normalize_model_name(name: str) -> str:
    """구(舊) 모델명을 신(新) 모델명으로 자동 매핑."""
    n = (name or "").strip()
    aliases = {
        "llama3-8b-8192": "llama-3.1-8b-instant",
        "llama3-70b-8192": "llama-3.1-70b-versatile",
        "llama-3-8b": "llama-3.1-8b-instant",
        "llama-3-70b": "llama-3.1-70b-versatile",
    }
    return aliases.get(n, n)


def _build() -> None:
    """환경/모듈 상황에 맞춰 모델을 안전하게 초기화. 실패해도 예외 미전파."""
    global _PROVIDER, _REASON, _MODEL
    if not _HAVE_LLM:
        _PROVIDER, _REASON, _MODEL = "none", "langchain_groq not installed", None
        return

    key = (os.getenv("GROQ_API_KEY") or "").strip()
    # ✅ 기본값을 최신 권장인 llama-3.1-8b-instant 로 설정
    name = _normalize_model_name(os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))

    if not key:
        _PROVIDER, _REASON, _MODEL = "none", "GROQ_API_KEY missing", None
        return

    try:
        # LangChain 버전에 따라 인자명이 다른 경우가 있어 이중 시도
        try:
            _MODEL = ChatGroq(model=name, api_key=key, temperature=0.2)  # 최신
        except TypeError:
            _MODEL = ChatGroq(model_name=name, groq_api_key=key, temperature=0.2)  # 구버전 호환
        _PROVIDER, _REASON = "groq", None
    except Exception as e:
        _PROVIDER, _REASON, _MODEL = "none", f"ChatGroq init failed: {e}", None


_build()


def get_model_status() -> dict:
    """헬스 체크에서 쓰기 좋은 간단 상태."""
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

    prompt = ChatPromptTemplate.from_messages([  # type: ignore[attr-defined]
        ("system",
         "You are an investment-banking equity analyst. Write in {lang}. "
         "Return 2–3 sentences covering liquidity, leverage/solvency, and optionally a 1-day signal. Plain text only."),
        ("human", "DATA(JSON): {blob}")
    ])
    chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]

    try:
        txt = chain.invoke({
            "lang": "Korean" if language.lower().startswith("ko") else "English",
            "blob": json.dumps({"analysis": ana, "prediction": pred}, ensure_ascii=False)
        })
        txt = re.sub(r"\s+", " ", str(txt)).strip() or _rule_summary(ana, pred, language)
        return txt[:600]
    except Exception:
        return _rule_summary(ana, pred, language)


# ── 뉴스 헤드라인 요약(LLM → 폴백)
def _summarize_headlines(items: List[Dict], language: str = "ko") -> str:
    titles = [str(it.get("title", "")).strip() for it in (items or []) if it.get("title")]
    titles = [t for t in titles if t]
    if not titles:
        return ""

    if _MODEL is not None:
        try:
            prompt = ChatPromptTemplate.from_messages([  # type: ignore[attr-defined]
                ("system",
                 "You are an investment-banking equity analyst. Write in {lang}. "
                 "Summarize these headlines into 2–3 concise sentences focusing on drivers/risks. Plain text only."),
                ("human", "HEADLINES:\n{blob}")
            ])
            chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]
            lang = "Korean" if language.lower().startswith("ko") else "English"
            blob = "\n".join(f"- {t}" for t in titles[:12])
            txt = chain.invoke({"lang": lang, "blob": blob})
            return re.sub(r"\s+", " ", str(txt)).strip()[:600]
        except Exception:
            pass

    # 폴백: 상위 2~3개 이어붙이기
    return " / ".join(titles[:3])


# ── 역호환/다중시그니처 지원: summarize_media
def summarize_media(
    arg1: Union[List[Dict], Dict],
    pred: Optional[dict] = None,
    language: str = "ko"
) -> str:
    """
    지원 형태
      1) summarize_media(items: List[Dict], language='ko')
         -> 기사 리스트/헤드라인 리스트를 받아 미디어 요약
      2) summarize_media(analysis: dict, pred: dict, language='ko')
         -> (진짜로) 재무분석 dict일 때만 IB 톤 요약
    """
    # 1) 이미 리스트면 그대로 헤드라인 요약
    if isinstance(arg1, list):
        return _summarize_headlines(arg1, language=language)

    # 2) 딕셔너리면 '미디어 분석'으로 보이는 키들에서 헤드라인 추출 시도
    if isinstance(arg1, dict):
        candidates = []
        for key in ("headlines", "titles", "items", "articles", "top"):
            if key in arg1 and isinstance(arg1[key], list):
                candidates = arg1[key]
                break
        # 기사/헤드라인 형태면 미디어 요약으로 처리
        if candidates:
            return _summarize_headlines(candidates, language=language)

        # 그 외에는 '재무분석'으로 간주 → IB 요약
        return summarize_ib(arg1, pred, language)

    # 알 수 없는 타입
    return ""

__all__ = ["get_model_status", "summarize_ib", "summarize_media"]
