# llm_agent.py
import json, time, re, urllib.parse
from typing import Optional, List, Dict
import numpy as np
import pandas as pd
import yfinance as yf
import feedparser

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq
from langchain.tools import tool
from finance_agent import run_query as fa_run_query, pick_valid_ticker
from predictor import predict_one
from brokers import price_now

# ---------------- Model (optional) ----------------
def build_model():
    import os
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    if not key:
        return None
    return ChatGroq(model=model, temperature=0.2, api_key=key)

model = build_model()

# ---------------- Safe fallback: 1D prediction ----------------
def _predict_fallback(symbol: str) -> dict:
    df = yf.download(symbol, period="1y", interval="1d", auto_adjust=True, progress=False)
    if not isinstance(df, pd.DataFrame) or df.empty or "Close" not in df:
        raise RuntimeError("fallback: no price data")

    # 순수 numpy 기반으로 안전 계산 (오류 원천 차단)
    close = pd.to_numeric(df["Close"], errors="coerce").astype(float).dropna().values
    if close.size < 20:
        raise RuntimeError("fallback: not enough data")

    rets = np.diff(close) / close[:-1]
    tail = rets[-10:] if rets.size >= 10 else rets
    pred_ret = float(np.nanmean(tail))
    last = float(close[-1])
    pred_close = last * (1.0 + pred_ret)
    signal = "BUY" if pred_ret > 0.01 else ("SELL" if pred_ret < -0.01 else "HOLD")

    return {
        "symbol": symbol,
        "last_close": round(last, 4),
        "pred_ret_1d": round(pred_ret, 6),
        "pred_close_1d": round(pred_close, 4),
        "signal": signal,
        "ts": int(time.time()),
    }

# ---------------- News (yfinance + Google News) ----------------
def _news_enriched(symbol: str, language: str, company_name: Optional[str] = None, k: int = 10) -> List[Dict]:
    items: List[Dict] = []
    # 1) yfinance
    try:
        arr = getattr(yf.Ticker(symbol), "news", []) or []
        for n in arr[:k]:
            items.append({
                "title": n.get("title"),
                "link": n.get("link"),
                "providerPublishTime": n.get("providerPublishTime") or n.get("pubTime"),
            })
    except Exception:
        pass

    # 2) Google News 보강
    def _google(q: str):
        is_ko = str(language).lower().startswith("ko")
        hl = "ko" if is_ko else "en-US"
        gl = "KR" if is_ko else "US"
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote_plus(q)
               + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")
        feed = feedparser.parse(url)
        out = []
        for e in feed.entries[:k]:
            link = e.get("link") or (e.get("links", [{}])[0].get("href"))
            ts = int(time.mktime(e.published_parsed)) if getattr(e, "published_parsed", None) else None
            out.append({"title": e.get("title"), "link": link, "providerPublishTime": ts})
        return out

    if len(items) < 3:
        q = f"{symbol} 주가 OR {symbol} 실적 OR {symbol} 주식" if language[:2]=="ko" else f"{symbol} stock OR earnings"
        try: items.extend(_google(q))
        except Exception: pass

    if len(items) < 3 and company_name:
        q2 = f"{company_name} 주가 OR {company_name} 실적 OR {company_name} 주식" if language[:2]=="ko" else f"{company_name} stock OR earnings"
        try: items.extend(_google(q2))
        except Exception: pass

    # 3) 제목 없는 항목/중복 링크 제거
    clean, seen = [], set()
    for it in items:
        t = (it or {}).get("title") or ""
        lk = (it or {}).get("link")
        if not t.strip():
            continue
        if lk and lk in seen:
            continue
        if lk:
            seen.add(lk)
        clean.append(it)
    return clean[:k]

# ---------------- IB-style summary (LLM or rule) ----------------
def _ib_style_summary_rule(ana: dict, pred: Optional[dict], language: str) -> str:
    # 숫자/밴드 꺼내기
    r = (ana or {}).get("core", {}).get("ratios", {})
    liq = r.get("Liquidity", {}) or {}
    sol = r.get("Solvency", {}) or {}

    def val(node): 
        v = (node or {}).get("value")
        return None if v is None else float(v)

    cr, qr, cash = val(liq.get("current_ratio")), val(liq.get("quick_ratio")), val(liq.get("cash_ratio"))
    de, dr, ic = val(sol.get("debt_to_equity")), val(sol.get("debt_ratio")), val(sol.get("interest_coverage"))

    # 간결한 3줄(유동성/건전성/리스크)
    if language[:2] == "ko":
        lines = []
        lines.append(f"유동성은 유동비율 {cr:.2f}, 당좌비율 {qr:.2f} 수준으로 단기지급능력은 {'양호' if (cr and cr>=1.5) else '보통'}합니다." if cr and qr else "유동성 지표가 제한적으로 제공됩니다.")
        lines.append(f"건전성은 D/E {de:.2f}, 부채비율 {dr:.2f}, 이자보상배율 {ic:.2f}로 {'보수적' if (de and de<=1.0 and (ic and ic>=5)) else '중립'}입니다.")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"])
            sig = pred.get("signal","HOLD")
            lines.append(f"단기(1D) 시그널은 {sig}({p*100:+.2f}%)이며 트레이딩 관점의 참고 지표로 활용을 권고합니다.")
        else:
            lines.append("단기(1D) 예측은 참고용이며 데이터 불충분 시 표시되지 않을 수 있습니다.")
        return " ".join(lines)
    else:
        lines = []
        lines.append(f"Liquidity appears {'solid' if (cr and cr>=1.5) else 'adequate'} with Current {cr:.2f} and Quick {qr:.2f}." if cr and qr else "Liquidity metrics are limited.")
        lines.append(f"Balance sheet is {'conservative' if (de and de<=1.0 and (ic and ic>=5)) else 'neutral'} (D/E {de:.2f}, Debt ratio {dr:.2f}, Interest coverage {ic:.2f}).")
        if pred and isinstance(pred, dict) and pred.get("pred_ret_1d") is not None:
            p = float(pred["pred_ret_1d"])
            sig = pred.get("signal","HOLD")
            lines.append(f"1-day tactical signal: {sig} ({p*100:+.2f}%), to be used as trading color only.")
        else:
            lines.append("1-day prediction is advisory and may be unavailable if data is insufficient.")
        return " ".join(lines)

def _ib_style_summary_llm(ana: dict, pred: Optional[dict], language: str) -> Optional[str]:
    if model is None:
        return None
    ask_lang = "Korean" if language.lower().startswith("ko") else "English"
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an investment-banking equity analyst. Write in {ask_lang}. "
         "Deliver a crisp 2–3 sentence note covering: Liquidity stance, solvency/leverage, and a tactical 1-day signal if provided. "
         "Make it professional and numbers-backed (mention key ratios once). No bullet points, no markdown, no headings."),
        ("human", "DATA(JSON):\n{blob}\n\nReturn only the prose text (2–3 sentences).")
    ])
    chain = prompt | model | StrOutputParser()
    try:
        txt = chain.invoke({"ask_lang": ask_lang, "blob": json.dumps({"analysis": ana, "prediction": pred}, ensure_ascii=False)})
        # 가끔 마크다운/여분 공백 제거
        txt = re.sub(r"\s+", " ", re.sub(r"`+|#+", " ", str(txt))).strip()
        return txt[:600]
    except Exception:
        return None

# ---------------- Tools (optional) ----------------
class PredictArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol like AAPL or 005930.KS")
    force: bool = Field(False, description="If true, bypass cache")

@tool("predict_one_day", args_schema=PredictArgs)
def predict_one_day_tool(symbol: str, force: bool = False) -> str:
    """Return 1-day ahead prediction with robust fallback and optional live price."""
    try:
        out = predict_one(symbol, force=force)
    except Exception:
        out = _predict_fallback(symbol)
    live = price_now(symbol)
    if live is not None:
        out["live_price"] = round(float(live), 4)
    return json.dumps(out, ensure_ascii=False)

class AnalyseArgs(BaseModel):
    query: str
    language: str = "ko"

@tool("compute_financials", args_schema=AnalyseArgs)
def compute_financials_tool(query: str, language: str = "ko") -> str:
    data = fa_run_query(query, language=language)
    return json.dumps(data, ensure_ascii=False)

class PriceArgs(BaseModel):
    symbol: str

@tool("get_live_price", args_schema=PriceArgs)
def get_live_price_tool(symbol: str) -> str:
    p = price_now(symbol)
    return json.dumps({"symbol": symbol, "live_price": p}, ensure_ascii=False)

class NewsArgs(BaseModel):
    symbol: str
    language: str = "en"
    k: int = 10

@tool("get_news", args_schema=NewsArgs)
def get_news_tool(symbol: str, language: str = "en", k: int = 10) -> str:
    return json.dumps({"symbol": symbol, "news": _news_enriched(symbol, language, None, k)}, ensure_ascii=False)

TOOLS = [predict_one_day_tool, compute_financials_tool, get_live_price_tool, get_news_tool]

# ---------------- Output schema ----------------
class AgentOutput(BaseModel):
    ticker: str
    company: Optional[str] = None
    price: Optional[float] = None
    analysis: Optional[dict] = None
    prediction: Optional[dict] = None
    news: Optional[List[dict]] = None
    summary: Optional[str] = None

# ---------------- Runner ----------------
def _aggregate(query: str, language: str = "ko", include_news: bool = True) -> AgentOutput:
    sym = pick_valid_ticker(query)
    ana = fa_run_query(query, language=language)

    # prediction (robust)
    try:
        pred = predict_one(sym, force=False)
    except Exception:
        pred = _predict_fallback(sym)

    live = price_now(sym)
    if live is not None:
        pred["live_price"] = round(float(live), 4)

    news = _news_enriched(sym, language, company_name=ana["core"].get("company"), k=10) if include_news else []

    # summary (LLM ➜ rule fallback)
    s_llm = _ib_style_summary_llm(ana, pred, language)
    s = s_llm or _ib_style_summary_rule(ana, pred, language)

    return AgentOutput(
        ticker=ana["core"]["ticker"],
        company=ana["core"]["company"],
        price=ana["core"]["price"],
        analysis=ana,
        prediction=pred,
        news=news,
        summary=s,
    )

def run_manager(query: str, language: str = "ko", include_news: bool = True) -> dict:
    return json.loads(_aggregate(query, language=language, include_news=include_news).model_dump_json())

# (optional) tool-calling agent
def run_manager_with_tools(query: str, language: str = "ko", want_news: bool = True) -> dict:
    try:
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a finance orchestrator. When unsure, call both compute_financials and predict_one_day. "
             "Return a single JSON with keys: ticker, company, price, analysis, prediction, news(optional), summary."),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(model, TOOLS, prompt)
        executor = AgentExecutor(agent=agent, tools=TOOLS, verbose=False)
        resp = executor.invoke({"input": f"{query}\nLanguage:{language}\nInclude news: {want_news}"})
        return json.loads(resp["output"])
    except Exception:
        return run_manager(query, language=language, include_news=want_news)
