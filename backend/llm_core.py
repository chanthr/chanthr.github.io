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
    name = _normalize_model_name(os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))

    if not key:
        _PROVIDER, _REASON, _MODEL = "none", "GROQ_API_KEY missing", None
        return

    try:
        # LangChain 버전에 따라 인자명이 다를 수 있어 이중 시도
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


# 버그 수정
def _norm_lang(s: str) -> str:
    try:
        return "ko" if str(s or "").lower().startswith("ko") else "en"
    except Exception:
        return "en"

def model_ready() -> bool:
    return bool(_MODEL)

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

    if _norm_lang(language) == "ko":
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
         "You are a senior equity research analyst. Write in {lang}. "
         "Deliver 4-5 concise sentences covering liquidity, leverage/solvency. "
         "Please do research online and only take data from Yahoo Finance"
         "Start directly with the insight (no fillers like 'Based on the provided data'). "
         "Avoid markdown and bullets; plain prose only."),
        ("human", "DATA(JSON): {blob}")
    ])
    chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]

    try:
        txt = chain.invoke({
            "lang": "Korean" if _norm_lang(language) == "ko" else "English",
            "blob": json.dumps({"analysis": ana, "prediction": pred}, ensure_ascii=False)
        })
        txt = re.sub(r"\s+", " ", str(txt)).strip() or _rule_summary(ana, pred, language)
        return txt[:600]
    except Exception:
        return _rule_summary(ana, pred, language)


# ── 뉴스 헤드라인 요약(LLM → 폴백)
def _summarize_headlines(items: List[Dict], language: str) -> str:
    titles = [str(it.get("title", "")).strip() for it in (items or []) if it.get("title")]
    titles = [t for t in titles if t]
    if not titles:
        return ""

    if _MODEL is not None:
        try:
            prompt = ChatPromptTemplate.from_messages([  # type: ignore[attr-defined]
                ("system",
                 "You are an investment-banking equity analyst. Write in {lang}. "
                 "Please don't end the sentence in the middle of talking."
                 "Please only take the keywords that can actually impact the business"
                 "Summarize these headlines into 2 concise sentences focusing on drivers/risks. Plain text only."),
                ("human", "HEADLINES:\n{blob}")
            ])
            chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]
            lang = "Korean" if _norm_lang(language) == "ko" else "English"
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
    if isinstance(arg1, list):
        return _summarize_headlines(arg1, language=language)

    if isinstance(arg1, dict):
        candidates = []
        for key in ("headlines", "titles", "items", "articles", "top"):
            if key in arg1 and isinstance(arg1[key], list):
                candidates = arg1[key]
                break
        if candidates:
            return _summarize_headlines(candidates, language=language)
        return summarize_ib(arg1, pred, language)

    return ""


# ── 내러티브: LLM → 실패 시 Markdown 폴백
def _fallback_narrative_markdown(payload: Dict, language: str, business_summary: Optional[str]) -> str:
    ask_lang = "ko" if _norm_lang(language) == "ko" else "en"
    r = (payload or {}).get("ratios", {}) or {}
    liq, sol = r.get("Liquidity", {}) or {}, r.get("Solvency", {}) or {}

    def fmt(node, name):
        v = (node or {}).get("value")
        b = (node or {}).get("band", "N/A")
        return f"{name}: {'N/A' if v is None else f'{float(v):.2f}'} ({b})"

    if ask_lang == "ko":
        lines = []
        lines.append("### 회사 개요 / Company overview")
        lines.append(business_summary or "회사 소개 정보를 가져오지 못했습니다.")
        lines.append("\n### 💧 유동성 / Liquidity")
        lines.append(f"- {fmt(liq.get('current_ratio'),'Current Ratio')}")
        lines.append(f"- {fmt(liq.get('quick_ratio'),'Quick Ratio')}")
        lines.append(f"- {fmt(liq.get('cash_ratio'),'Cash Ratio')}")
        lines.append("\n### 🛡️ 건전성 / Solvency")
        lines.append(f"- {fmt(sol.get('debt_to_equity'),'Debt-to-Equity')}")
        lines.append(f"- {fmt(sol.get('debt_ratio'),'Debt Ratio')}")
        lines.append(f"- {fmt(sol.get('interest_coverage'),'Interest Coverage')}")
        bands = [ (liq.get("current_ratio") or {}).get("band","N/A"),
                  (liq.get("quick_ratio") or {}).get("band","N/A"),
                  (liq.get("cash_ratio") or {}).get("band","N/A"),
                  (sol.get("debt_to_equity") or {}).get("band","N/A"),
                  (sol.get("debt_ratio") or {}).get("band","N/A"),
                  (sol.get("interest_coverage") or {}).get("band","N/A") ]
        score = sum({"Strong":2,"Fair":1}.get(b,0) for b in bands)
        verdict = "매우 양호" if score>=9 else "양호" if score>=6 else "보통" if score>=3 else "취약"
        lines.append("\n### ✅ 종합 평가 / Overall financial health")
        lines.append(f"유동성/건전성 지표를 종합하면 재무건전성은 **{verdict}**한 편입니다.")
        lines.append("\n### ℹ️ 핵심 요약 / Takeaway")
        lines.append("핵심 지표 기반으로 재무 체력이 무난합니다.")
        return "\n".join(lines)
    else:
        lines = []
        lines.append("### Company overview")
        lines.append(business_summary or "Business description not available.")
        lines.append("\n### 💧 Liquidity")
        lines.append(f"- {fmt(liq.get('current_ratio'),'Current Ratio')}")
        lines.append(f"- {fmt(liq.get('quick_ratio'),'Quick Ratio')}")
        lines.append(f"- {fmt(liq.get('cash_ratio'),'Cash Ratio')}")
        lines.append("\n### 🛡️ Solvency")
        lines.append(f"- {fmt(sol.get('debt_to_equity'),'Debt-to-Equity')}")
        lines.append(f"- {fmt(sol.get('debt_ratio'),'Debt Ratio')}")
        lines.append(f"- {fmt(sol.get('interest_coverage'),'Interest Coverage')}")
        bands = [ (liq.get("current_ratio") or {}).get("band","N/A"),
                  (liq.get("quick_ratio") or {}).get("band","N/A"),
                  (liq.get("cash_ratio") or {}).get("band","N/A"),
                  (sol.get("debt_to_equity") or {}).get("band","N/A"),
                  (sol.get("debt_ratio") or {}).get("band","N/A"),
                  (sol.get("interest_coverage") or {}).get("band","N/A") ]
        score = sum({"Strong":2,"Fair":1}.get(b,0) for b in bands)
        verdict = "excellent" if score>=9 else "good" if score>=6 else "average" if score>=3 else "weak"
        lines.append("\n### ✅ Overall financial health")
        lines.append(f"Overall balance-sheet quality appears **{verdict}**.")
        lines.append("\n### ℹ️ Takeaway")
        lines.append("Ratios indicate a resilient balance sheet.")
        return "\n".join(lines)


def summarize_narrative(payload: Dict, language: str = "ko", business_summary: Optional[str] = None) -> str:
    """
    Narrative(Markdown) 생성: LLM 성공 시 섹션/불릿 그대로, 실패 시 동일 템플릿 폴백.
    """
    lang = _norm_lang(language)

    # 폴백 빌더 (Markdown)
    def _fallback(payload: Dict, business_summary: Optional[str]) -> str:
        r = (payload or {}).get("ratios", {}) or {}
        L, S = r.get("Liquidity", {}) or {}, r.get("Solvency", {}) or {}

        def fmt(node, name):
            v = (node or {}).get("value")
            b = (node or {}).get("band", "N/A")
            return f"- {name}: {'N/A' if v is None else f'{float(v):.2f}'} ({b})"

        bs = _shrink_summary(business_summary, lang, 35)
        if lang == "ko":
            lines = [
                "### 회사 개요 / Company overview",
                bs,
                "",
                "### 💧 유동성 / Liquidity",
                fmt(L.get("current_ratio"), "Current Ratio"),
                fmt(L.get("quick_ratio"), "Quick Ratio"),
                fmt(L.get("cash_ratio"), "Cash Ratio"),
                "",
                "### 🛡️ 건전성 / Solvency",
                fmt(S.get("debt_to_equity"), "Debt-to-Equity"),
                fmt(S.get("debt_ratio"), "Debt Ratio"),
                fmt(S.get("interest_coverage"), "Interest Coverage"),
            ]
        else:
            lines = [
                "### Company overview",
                bs,
                "",
                "### 💧 Liquidity",
                fmt(L.get("current_ratio"), "Current Ratio"),
                fmt(L.get("quick_ratio"), "Quick Ratio"),
                fmt(L.get("cash_ratio"), "Cash Ratio"),
                "",
                "### 🛡️ Solvency",
                fmt(S.get("debt_to_equity"), "Debt-to-Equity"),
                fmt(S.get("debt_ratio"), "Debt Ratio"),
                fmt(S.get("interest_coverage"), "Interest Coverage"),
            ]
        return "\n".join(lines)

    # LLM이 없으면 즉시 폴백
    if _MODEL is None:
        return _fallback(payload, business_summary)

    try:
        prompt = ChatPromptTemplate.from_messages([  # type: ignore[attr-defined]
            ("system",
             "You are a senior equity analyst. Write in {ask_lang}. "
             "Return **Markdown** using EXACTLY this structure and preserve line breaks. "
             "Keep the company overview to MAX 35 words. "
             "For metrics, print each on its own bullet line and round values to two decimals. "
             "If a value is missing, print 'N/A' for <value> but still keep the band in parentheses. "
             "Do not merge headings into one line. No extra sections."),
            ("human",
             "### 회사 개요 / Company overview\n"
             "{business_summary}\n\n"
             "### 💧 유동성 / Liquidity\n"
             "- Current Ratio: <value> (<band>)\n"
             "- Quick Ratio: <value> (<band>)\n"
             "- Cash Ratio: <value> (<band>)\n\n"
             "### 🛡️ 건전성 / Solvency\n"
             "- Debt-to-Equity: <value> (<band>)\n"
             "- Debt Ratio: <value> (<band>)\n"
             "- Interest Coverage: <value> (<band>)\n\n"
             "DATA(JSON):\n{blob}")
        ])
        chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]

        ask_lang = "Korean" if lang == "ko" else "English"
        bs_short = _shrink_summary(business_summary, lang, 35)
        blob = json.dumps((payload or {}).get("ratios", {}), ensure_ascii=False)

        md = chain.invoke({
            "ask_lang": ask_lang,
            "business_summary": bs_short,
            "blob": blob
        })

        # 🔧 후처리: 코드펜스 제거 + 줄바꿈 보존 + 트레일링 스페이스만 정리
        md = str(md).strip()
        md = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", md, flags=re.S)  # fenced code 제거
        md = re.sub(r"[ \t]+\n", "\n", md)  # 줄 끝 공백만 제거

        # LLM이 양식 어기면 폴백
        return md if "###" in md else _fallback(payload, business_summary)
    except Exception:
        return _fallback(payload, business_summary)

# 호환용 별칭: 과거 gen_narrative 시그니처 지원
def gen_narrative(ratios_payload: Dict, language: str, business_summary: Optional[str]) -> str:
    payload = {"ratios": ratios_payload}
    return summarize_narrative(payload, language, business_summary)


__all__ = [
    "get_model_status",
    "model_ready",
    "summarize_ib",
    "summarize_media",
    "summarize_narrative",
]
