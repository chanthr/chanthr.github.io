# finance_agent.py
import os, re, json
from typing import Dict, Optional, List
import pandas as pd
import yfinance as yf

# ✅ llm_core 선택적 사용 (이 파일은 LLM 비의존적으로 동작)
try:
    from llm_core import summarize_narrative as _llm_narrative
    from llm_core import model_ready as _llm_ready
    _HAVE_LLM_CORE = True
except Exception:
    _HAVE_LLM_CORE = False
    _llm_narrative = None
    def _llm_ready() -> bool: return False  # type: ignore

# ---------------- yfinance helpers ----------------
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
        for lower, orig in lower_index_map.items():
            if alias_l in lower:
                series = df.loc[orig]
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

# ---------------- Core ratios ----------------
def compute_ratios_for_ticker(ticker: str) -> dict:
    t = yf.Ticker(ticker.strip())

    q_bs = getattr(t, "quarterly_balance_sheet", None)
    if q_bs is None or getattr(q_bs, "empty", True):
        q_bs = getattr(t, "balance_sheet", None)

    q_is = getattr(t, "quarterly_financials", None)
    if q_is is None or getattr(q_is, "empty", True):
        q_is = getattr(t, "quarterly_income_stmt", None)
    a_is = getattr(t, "income_stmt", None)

    q_cf = getattr(t, "quarterly_cashflow", None)
    a_cf = getattr(t, "cashflow", None)

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

    if q_bs is None or getattr(q_bs, "empty", True):
        return {
            "company": company_name,
            "ticker": ticker.upper(),
            "sector": sector,
            "price": price,
            "ratios": {"Liquidity": {}, "Solvency": {}},
            "notes": "대차대조표를 찾지 못했습니다. 거래소 접미사(.KS, .T, .HK 등) 확인."
        }

    current_assets      = _latest_value_from_df(q_bs, ["total current assets", "current assets"])
    current_liabilities = _latest_value_from_df(q_bs, ["total current liabilities", "current liabilities"])
    inventory           = _latest_value_from_df(q_bs, ["inventory"])
    cash                = _latest_value_from_df(q_bs, [
        "cash and cash equivalents",
        "cash and cash equivalents including short-term investments",
        "cash and short term investments",
        "cash and short-term investments",
        "cash",
    ])
    short_term_invest   = _latest_value_from_df(q_bs, ["short term investments", "short-term investments"])
    cash_like           = _sum_if_present(cash, short_term_invest)

    total_assets        = _latest_value_from_df(q_bs, ["total assets"])
    total_liabilities   = _latest_value_from_df(q_bs, ["total liabilities"])
    equity              = _latest_value_from_df(q_bs, ["total stockholder equity", "total shareholders equity", "total equity"])
    short_lt_debt       = _latest_value_from_df(q_bs, ["short long term debt", "current portion of long term debt", "short-term debt"])
    long_term_debt      = _latest_value_from_df(q_bs, ["long term debt"])
    total_debt          = _latest_value_from_df(q_bs, ["total debt"]) or _sum_if_present(short_lt_debt, long_term_debt)

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

    current_ratio = _safe_div(current_assets, current_liabilities)
    quick_ratio   = _safe_div((current_assets - inventory) if (current_assets is not None and inventory is not None) else None, current_liabilities)
    cash_ratio    = _safe_div(cash_like, current_liabilities)
    debt_to_equity= _safe_div(total_debt, equity)
    debt_ratio    = _safe_div(total_liabilities, total_assets)
    interest_cov  = None
    if ebit is not None and interest_expense is not None:
        try:
            denom = abs(float(interest_expense))
            if denom:
                interest_cov = float(ebit) / denom
        except Exception:
            interest_cov = None

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

# ---------------- ticker picker ----------------
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

# ---------------- Narrative (LLM → 폴백) ----------------
def _fallback_narrative(payload: Dict, language: str, business_summary: Optional[str]) -> str:
    ask_ko = language.lower().startswith("ko")
    r = payload.get("ratios", {}) or {}
    liq, sol = r.get("Liquidity", {}), r.get("Solvency", {})

    def fmt(node, name):
        v = (node or {}).get("value")
        b = (node or {}).get("band", "N/A")
        return f"{name}: {'N/A' if v is None else f'{v:.2f}'} ({b})"

    if ask_ko:
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
            ])
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
            ])
        )

def _make_narrative(payload_core: Dict, language: str, business_summary: Optional[str], want: bool) -> str:
    if not want:
        return ""
    # 1) LLM 가능하면 LLM Markdown 생성
    if _HAVE_LLM_CORE and _llm_ready() and callable(_llm_narrative):
        try:
            md = _llm_narrative(payload_core, language, business_summary)  # type: ignore
            if isinstance(md, str) and md.strip():
                return md
        except Exception:
            pass
    # 2) 실패/미설정 시 폴백
    try:
        return _fallback_narrative(payload_core, language, business_summary)
    except Exception:
        return ""

# ---------------- Public entry ----------------
def run_query(user_query: str, language: str = "ko", want_narrative: bool = True) -> dict:
    ticker = pick_valid_ticker(user_query)
    payload = compute_ratios_for_ticker(ticker)
    business_summary = _get_company_summary(payload["ticker"])

    explanation = _make_narrative(payload, language, business_summary, want=want_narrative)

    return {
        "core": {
            "company": payload["company"],
            "ticker": payload["ticker"],
            "price": payload["price"],
            "ratios": payload["ratios"],
        },
        "notes": payload.get("notes"),
        "explanation": explanation,   # Markdown(LLM) 또는 간단 텍스트(폴백)
        "meta": {
            "source": "Yahoo Finance",
            "narrative_llm": bool(_HAVE_LLM_CORE and _llm_ready())
        },
    }

__all__ = ["run_query", "pick_valid_ticker", "compute_ratios_for_ticker"]
