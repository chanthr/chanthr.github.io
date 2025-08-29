# finance_agent.py
import os
import re
import json
from typing import Dict, Optional, List

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# --- LangChain / Groq ---
load_dotenv()
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain.tools import tool

# 파일 상단 import 바로 아래에 추가
try:
    import streamlit as st
    _HAVE_ST = True
except Exception:
    _HAVE_ST = False

def _get_groq_key() -> str:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key and _HAVE_ST:
        try:
            key = str(st.secrets.get("GROQ_API_KEY", "")).strip()
        except Exception:
            pass
    return key

# ---------------------------
# Safe LLM builder (Groq)
# ---------------------------
_GROQ_REASON = None  # ← 전역 사유 저장

def _build_llm():
    global _GROQ_REASON
    try:
        key = _get_groq_key()
        model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
        if not key:
            _GROQ_REASON = "GROQ_API_KEY not found (env nor st.secrets)."
            return None
        # langchain_groq는 api_key= 사용 (groq_api_key 아님)
        return ChatGroq(model=model, temperature=0.2, api_key=key)
    except Exception as e:
        _GROQ_REASON = f"ChatGroq init failed: {e}"
        return None

llm = _build_llm()

# =========================
# yfinance helpers
# =========================
def _safe_info(t: yf.Ticker) -> Dict:
    try:
        info = t.get_info() if hasattr(t, "get_info") else (getattr(t, "info", {}) or {})
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}

def _get_company_summary(ticker: str) -> Optional[str]:
    try:
        t = yf.Ticker(ticker.strip())
        info = _safe_info(t)
        return info.get("longBusinessSummary") or info.get("longDescription")
    except Exception:
        return None

def _latest_value_from_df(df: pd.DataFrame, aliases: List[str]) -> Optional[float]:
    if df is None or getattr(df, "empty", True):
        return None
    lower_index_map = {str(idx).strip().lower(): idx for idx in df.index}
    try:
        cols_sorted = sorted(df.columns, reverse=True)
    except Exception:
        cols_sorted = list(df.columns)
    for alias in aliases:
        alias_l = alias.strip().lower()
        for row_lower, row_orig in lower_index_map.items():
            if alias_l in row_lower:
                series = df.loc[row_orig]
                for c in cols_sorted:
                    val = series.get(c, None)
                    if pd.notnull(val):
                        try:
                            return float(val)
                        except Exception:
                            continue
    return None

def _sum_if_present(*vals: Optional[float]) -> Optional[float]:
    present = [v for v in vals if v is not None]
    return sum(present) if present else None

def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    try:
        return float(a) / float(b)
    except Exception:
        return None

# =========================
# Core ratio computation
# =========================
def compute_ratios_for_ticker(ticker: str) -> dict:
    t = yf.Ticker(ticker.strip())

    # 재무제표(분기 우선 → 연간 폴백)
    q_bs = getattr(t, "quarterly_balance_sheet", None)
    if q_bs is None or getattr(q_bs, "empty", True):
        q_bs = getattr(t, "balance_sheet", None)

    q_is = getattr(t, "quarterly_financials", None)
    if q_is is None or getattr(q_is, "empty", True):
        q_is = getattr(t, "quarterly_income_stmt", None)
    a_is = getattr(t, "income_stmt", None)

    q_cf = getattr(t, "quarterly_cashflow", None)
    a_cf = getattr(t, "cashflow", None)

    # 회사/가격 정보(가능하면만)
    info = _safe_info(t)
    company_name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector")
    price = None
    try:
        fast = getattr(t, "fast_info", {}) or {}
        lp = fast.get("last_price")
        price = float(lp) if lp is not None else None
    except Exception:
        pass

    # 대차대조표 없으면 조기 반환
    if q_bs is None or getattr(q_bs, "empty", True):
        return {
            "company": company_name,
            "ticker": ticker.upper(),
            "sector": sector,
            "price": price,
            "ratios": {"Liquidity": {}, "Solvency": {}},
            "notes": "대차대조표를 찾지 못했습니다. 거래소 접미사(.KS, .T, .HK 등) 확인."
        }

    # BS
    current_assets = _latest_value_from_df(q_bs, ["total current assets", "current assets"])
    current_liabilities = _latest_value_from_df(q_bs, ["total current liabilities", "current liabilities"])
    inventory = _latest_value_from_df(q_bs, ["inventory"])
    cash = _latest_value_from_df(q_bs, [
        "cash and cash equivalents",
        "cash and cash equivalents including short-term investments",
        "cash and short term investments",
        "cash and short-term investments",
        "cash",
    ])
    short_term_invest = _latest_value_from_df(q_bs, ["short term investments", "short-term investments"])
    cash_like = _sum_if_present(cash, short_term_invest)

    total_assets = _latest_value_from_df(q_bs, ["total assets"])
    total_liabilities = _latest_value_from_df(q_bs, ["total liabilities"])
    equity = _latest_value_from_df(q_bs, ["total stockholder equity", "total shareholders equity", "total equity"])
    short_lt_debt = _latest_value_from_df(q_bs, [
        "short long term debt", "current portion of long term debt", "short-term debt"
    ])
    long_term_debt = _latest_value_from_df(q_bs, ["long term debt"])
    total_debt = _latest_value_from_df(q_bs, ["total debt"]) or _sum_if_present(short_lt_debt, long_term_debt)

    # IS/CF → EBIT & Interest
    def _has_df(df): return (df is not None) and (hasattr(df, "empty") and not df.empty)

    ebit = None
    if _has_df(q_is):
        ebit = _latest_value_from_df(q_is, ["ebit", "operating income", "earnings before interest and taxes"])
    if ebit is None and _has_df(a_is):
        ebit = _latest_value_from_df(a_is, ["ebit", "operating income", "earnings before interest and taxes"])

    interest_expense = None
    if _has_df(q_is):
        interest_expense = _latest_value_from_df(q_is, ["interest expense", "interest expense non operating"])
    if interest_expense is None and _has_df(a_is):
        interest_expense = _latest_value_from_df(a_is, ["interest expense", "interest expense non operating"])
    if interest_expense is None and _has_df(q_cf):
        interest_expense = _latest_value_from_df(q_cf, ["interest paid"])
    if interest_expense is None and _has_df(a_cf):
        interest_expense = _latest_value_from_df(a_cf, ["interest paid"])

    # 비율
    current_ratio = _safe_div(current_assets, current_liabilities)
    quick_ratio = _safe_div(
        (current_assets - inventory) if (current_assets is not None and inventory is not None) else None,
        current_liabilities
    )
    cash_ratio = _safe_div(cash_like, current_liabilities)
    debt_to_equity = _safe_div(total_debt, equity)
    debt_ratio = _safe_div(total_liabilities, total_assets)

    interest_cov = None
    if ebit is not None and interest_expense is not None:
        try:
            denom = abs(float(interest_expense))
            if denom:
                interest_cov = float(ebit) / denom
        except Exception:
            interest_cov = None

    # 라벨링
    def _band(val: Optional[float], good: float, fair: float, higher_is_better: bool = True) -> str:
        if val is None:
            return "N/A"
        if higher_is_better:
            if val >= good: return "Strong"
            if val >= fair: return "Fair"
            return "Weak"
        else:
            if val <= good: return "Strong"
            if val <= fair: return "Fair"
            return "Weak"

    assessment = {
        "Liquidity": {
            "current_ratio": {"value": current_ratio, "band": _band(current_ratio, 1.5, 1.0, True)},
            "quick_ratio":   {"value": quick_ratio,   "band": _band(quick_ratio, 1.0, 0.8, True)},
            "cash_ratio":    {"value": cash_ratio,    "band": _band(cash_ratio, 0.5, 0.2, True)},
        },
        "Solvency": {
            "debt_to_equity":    {"value": debt_to_equity, "band": _band(debt_to_equity, 1.0, 2.0, False)},
            "debt_ratio":        {"value": debt_ratio,     "band": _band(debt_ratio, 0.5, 0.7, False)},
            "interest_coverage": {"value": interest_cov,   "band": _band(interest_cov, 5.0, 2.0, True)},
        }
    }

    return {
        "company": company_name,
        "ticker": ticker.upper(),
        "sector": sector,
        "price": price,
        "ratios": assessment,
        "notes": "Latest quarterly (fallback to annual) statements via yfinance; ratios are approximations."
    }

# LangChain Tool (optional)
@tool("finance_health_tool")
def finance_health_tool(ticker: str) -> str:
    """티커를 받아 유동성/건전성 비율을 계산해 JSON 문자열로 반환."""
    data = compute_ratios_for_ticker(ticker)
    return json.dumps(data, ensure_ascii=False)

# =========================
# Ticker parsing
# =========================
def pick_valid_ticker(user_query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9\.\-]{1,15}", (user_query or "").upper())
    candidates = [t for t in tokens if any(c.isalpha() for c in t)]
    if not candidates:
        return (user_query or "").upper().strip() or "AAPL"
    for sym in candidates:
        try:
            t = yf.Ticker(sym.strip())
            bs = getattr(t, "quarterly_balance_sheet", None)
            if isinstance(bs, pd.DataFrame) and not bs.empty:
                return sym.strip()
        except Exception:
            continue
    return candidates[0].strip()

# =========================
# Narrative via LangChain
# =========================
_output_parser = StrOutputParser()
_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     "You are a financial analysis assistant. "
     "Write in {ask_lang}. "
     "Be concise and clear. "
     "When summarizing company description, limit to **30 words maximum (or 30 Korean words if Korean)**."
    ),
    ("human",
     "Return **Markdown only** using **this exact template**:\n\n"
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
     "### ✅ 종합 평가 / Overall financial health\n"
     "Provide a **1–2 sentence** overall judgment combining liquidity and solvency.\n\n"
     "### ℹ️ 핵심 요약 / Takeaway\n"
     "One short plain-language takeaway.\n\n"
     "Use the data below.\n"
     "BUSINESS_SUMMARY:\n{business_summary}\n\n"
     "RATIOS_JSON:\n{ratios_json}"
    ),
    MessagesPlaceholder("agent_scratchpad"),
])

def _fallback_narrative(payload: Dict, language: str, business_summary: Optional[str]) -> str:
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    r = payload.get("ratios", {})
    liq, sol = r.get("Liquidity", {}), r.get("Solvency", {})

    def fmt(node, name):
        v = (node or {}).get("value")
        b = (node or {}).get("band", "N/A")
        return f"{name}: {'N/A' if v is None else f'{v:.2f}'} ({b})"

    # ✅ 동적 총평
    def overall_verdict():
        score_map = {"Strong": 2, "Fair": 1, "Weak": 0, "N/A": 0}
        bands = [
            (liq.get("current_ratio") or {}).get("band", "N/A"),
            (liq.get("quick_ratio") or {}).get("band", "N/A"),
            (liq.get("cash_ratio") or {}).get("band", "N/A"),
            (sol.get("debt_to_equity") or {}).get("band", "N/A"),
            (sol.get("debt_ratio") or {}).get("band", "N/A"),
            (sol.get("interest_coverage") or {}).get("band", "N/A"),
        ]
        total = sum(score_map.get(b, 0) for b in bands)
        if ask_lang == "Korean":
            if total >= 9: return "재무건전성은 **매우 양호**한 편입니다."
            if total >= 6: return "재무건전성은 **양호**한 편입니다."
            if total >= 3: return "재무건전성은 **보통** 수준입니다."
            return "재무건전성은 **취약**한 편입니다."
        else:
            if total >= 9: return "Overall financial health is **excellent**."
            if total >= 6: return "Overall financial health is **good**."
            if total >= 3: return "Overall financial health is **average**."
            return "Overall financial health is **weak**."

    if ask_lang == "Korean":
        return (
            f"회사 개요: {business_summary or '회사 소개 정보를 가져오지 못했습니다.'}\n"
            "• 유동성: " + ", ".join([
                fmt(liq.get("current_ratio"), "유동비율"),
                fmt(liq.get("quick_ratio"), "당좌비율"),
                fmt(liq.get("cash_ratio"), "현금비율"),
            ]) + "\n"
            "• 건전성: " + ", ".join([
                fmt(sol.get("debt_to_equity"), "부채비율(D/E)"),
                fmt(sol.get("debt_ratio"), "부채비율(TA)"),
                fmt(sol.get("interest_coverage"), "이자보상배율"),
            ]) + "\n"
            f"한줄평: {overall_verdict()}"
        )
    else:
        return (
            f"Company overview: {business_summary or 'Business description not available.'}\n"
            "• Liquidity: " + ", ".join([
                fmt(liq.get("current_ratio"), "Current Ratio"),
                fmt(liq.get("quick_ratio"), "Quick Ratio"),
                fmt(liq.get("cash_ratio"), "Cash Ratio"),
            ]) + "\n"
            "• Solvency: " + ", ".join([
                fmt(sol.get("debt_to_equity"), "Debt-to-Equity"),
                fmt(sol.get("debt_ratio"), "Debt Ratio"),
                fmt(sol.get("interest_coverage"), "Interest Coverage"),
            ]) + "\n"
            f"Takeaway: {overall_verdict()}"
        )

def _make_narrative_with_langchain(payload: Dict, language: str, business_summary: Optional[str]) -> str:
    if llm is None:
        return _fallback_narrative(payload, language, business_summary)

    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    inputs = {
        "ask_lang": ask_lang,
        "business_summary": business_summary or "(not available)",
        "ratios_json": json.dumps(payload, ensure_ascii=False),
        "agent_scratchpad": [],
    }
    chain = _prompt | llm | _output_parser
    try:
        return chain.invoke(inputs)
    except Exception as e:
        return f"[LLM error: {e}]\n" + _fallback_narrative(payload, language, business_summary)

# =========================
# Public entry
# =========================
def run_query(user_query: str, language: str = "ko") -> dict:
    ticker = pick_valid_ticker(user_query)
    payload = compute_ratios_for_ticker(ticker)
    business_summary = _get_company_summary(payload["ticker"])

    ratios = payload.get("ratios") or {}
    liq = ratios.get("Liquidity") or {}
    sol = ratios.get("Solvency") or {}
    empty_liq = all((liq.get(k, {}).get("value") is None) for k in ["current_ratio","quick_ratio","cash_ratio"])
    empty_sol = all((sol.get(k, {}).get("value") is None) for k in ["debt_to_equity","debt_ratio","interest_coverage"])

    if not ratios or (empty_liq and empty_sol):
        payload["notes"] = f"'{ticker}' 재무제표를 찾지 못했습니다. 거래소 접미사(.KS, .T, .HK 등) 확인."
        explanation = "재무제표가 비어 있어 평가를 생성하지 않았습니다."
    else:
        explanation = _make_narrative_with_langchain(payload, language, business_summary)

    return {
        "core": {
            "company": payload["company"],
            "ticker": payload["ticker"],
            "price": payload["price"],
            "ratios": payload["ratios"],
        },
        "notes": payload.get("notes"),
        "explanation": explanation,
        "meta": {"source": "llm" if (llm is not None) else "fallback"}
    }

if __name__ == "__main__":
    q = input("예: 'AAPL 유동성/건전성 평가' > ").strip()
    out = run_query(q, language="ko")
    print("\n--- Explanation ---\n")
    print(out["explanation"])