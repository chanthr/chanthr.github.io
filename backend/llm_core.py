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


# ── 유틸
def _norm_lang(s: str) -> str:
    try:
        return "ko" if str(s or "").lower().startswith("ko") else "en"
    except Exception:
        return "en"

def model_ready() -> bool:
    return bool(_MODEL)

def _shrink_summary(text: Optional[str], lang: str, max_words: int) -> str:
    """회사 개요를 단어 수 기준으로 축약."""
    if not text:
        return "회사 소개 정보를 가져오지 못했습니다." if lang == "ko" else "Business description not available."
    # 코드/마크다운 제거
    s = re.sub(r"```.*?```", " ", text, flags=re.S)
    s = re.sub(r"`[^`]*`", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    if len(words) <= max_words:
        return s
    return " ".join(words[:max_words]).rstrip(",.;") + ("…" if lang != "ko" else "…")


def _detect_lang_from_titles(titles: List[str]) -> str:
    """헤드라인 모음에서 ko/en 추정."""
    text = " ".join(titles)[:2000]
    hangul = len(re.findall(r"[가-힣]", text))
    latin  = len(re.findall(r"[A-Za-z]", text))
    return "ko" if hangul > latin else "en"


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
         "Deliver 3–4 concise sentences covering liquidity and leverage/solvency. "
         "Start directly with the insight (no fillers). Plain text only."),
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
def _summarize_headlines(items: List[Dict], language: str = "auto") -> str:
    titles = [str(it.get("title", "")).strip() for it in (items or []) if it.get("title")]
    titles = [t for t in titles if t]
    if not titles:
        return ""

    # 언어 결정: 명시값 > 자동 감지
    norm = _norm_lang(language) if language and language != "auto" else _detect_lang_from_titles(titles)
    ask = "Korean" if norm == "ko" else "English"

    if _MODEL is not None:
        try:
            prompt = ChatPromptTemplate.from_messages([  # type: ignore[attr-defined]
                ("system",
                 "You are an investment-banking equity analyst. Write in {lang}. "
                 "Summarize these headlines into 2 concise sentences focusing on drivers and risks. "
                 "Avoid fluff; plain text only."),
                ("human", "HEADLINES:\n{blob}")
            ])
            chain = prompt | _MODEL | StrOutputParser()  # type: ignore[operator]
            blob = "\n".join(f"- {t}" for t in titles[:12])
            txt = chain.invoke({"lang": ask, "blob": blob})
            return re.sub(r"\s+", " ", str(txt)).strip()[:600]
        except Exception:
            pass

    # 폴백: 상위 2~3개 이어붙이기
    return " / ".join(titles[:3])


# ── 역호환/다중시그니처 지원: summarize_media
def summarize_media(
    arg1: Union[List[Dict], Dict],
    pred: Optional[dict] = None,
    language: str = "auto"
) -> str:
    """
    지원 형태
      1) summarize_media(items: List[Dict], language='auto')
         -> 기사 리스트/헤드라인 리스트를 받아 미디어 요약
      2) summarize_media(analysis: dict, pred: dict, language='auto')
         -> (진짜로) 재무분석 dict일 때만 IB 톤 요약
    """
    # 리스트(헤드라인)면 그대로 헤드라인 요약
    if isinstance(arg1, list):
        return _summarize_headlines(arg1, language=language)

    # 딕셔너리면 기사/헤드라인 키 우선 → 없으면 IB요약
    if isinstance(arg1, dict):
        candidates = []
        for key in ("headlines", "titles", "items", "articles", "top"):
            if key in arg1 and isinstance(arg1[key], list):
                candidates = arg1[key]
                break
        if candidates:
            return _summarize_headlines(candidates, language=language)
        return summarize_ib(arg1, pred, language)

    # 알 수 없는 타입
    return ""


# ── Narrative: LLM → 실패 시 Markdown 폴백
def summarize_narrative(payload: Dict, language: str = "ko", business_summary: Optional[str] = None) -> str:
    """
    Narrative(Markdown) 생성: LLM 성공 시 섹션/불릿 그대로, 실패 시 동일 템플릿 폴백.
    - 회사 개요: 최대 35 단어
    - 각 지표는 별도 불릿, 값은 소수 둘째 자리 반올림, 없으면 N/A
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
             "Do not add or remove sections."),
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

        # 후처리: 코드펜스 제거 + 줄바꿈 보존
        md = str(md).strip()
        md = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", md, flags=re.S)  # fenced code 제거
        md = re.sub(r"[ \t]+\n", "\n", md)  # 줄 끝 공백만 제거

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
    "gen_narrative",
]
